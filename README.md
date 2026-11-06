# event_connect

**event_connect** is a protocol-independent Python library for building device clients. You
describe a device as a set of typed *points*. event_connect then:
- decides when to read each point;
- notifies subscribers when a value changes;
- schedules follow-up reads after a write or a change;
- keeps the last known value, marked stale, when a reply is lost;
- decides when the device counts as offline, and stops asking a device that has gone silent.

You supply the protocol: where each value is stored on the device, how it is encoded, and how a
request is sent. event_connect performs no I/O and never sleeps, so everything it decides can be
tested without a device.

[Source](https://github.com/HairingX/event_connect) ·
[Issues](https://github.com/HairingX/event_connect/issues) ·
[Releases](https://github.com/HairingX/event_connect/releases)

## Requirements

- Python 3.14 or later.
- No dependencies outside the standard library.
- Fully typed (`py.typed`).
- Status: alpha. Until 1.0, a minor version may change the API.

## Installation

```bash
pip install event-connect
```

In your package, require a range of versions up to the next one that may break the API, for
example `event_connect>=0.3,<0.4`. [Versioning](#versioning) explains why.

## Concepts

- **Point**: one value on the device, such as a temperature, a set point or a command. A point
  is identified by a typed `Key` and describes how the value behaves: how often it is read, what
  may be written, and which other points to read again when it changes.
- **Key**: the name of a point, carrying the type of its value. `Key("temperature", float)` is a
  string at runtime, so it works as a dictionary key and in logs.
- **Poll rate**: how often a point is read (`FAST`, `MEDIUM`, `SLOW`, `RARE`, `STATIC`). A
  `Timing` maps each rate to seconds.
- **Pass**: one round in which the client reads everything that is due.
- **Quality**: how far a value can be trusted. `GOOD` means the device answered. `STALE` means
  the last read failed and the value is the last good one.
- **Refresh**: an extra read of other points, a set time after a write or a change.
- **Deadband**: the smallest change of a value that counts as a change. Smaller movements are
  not reported, and they count as settled.

## Quick start

The scheduler tells you which points to read. You read them with your protocol and record the
outcome.

```python
from dataclasses import KW_ONLY, dataclass

from event_connect import DataValue, Key, Point, Quality, Timing
from event_connect.testing import FakeClock


@dataclass(frozen=True, eq=False)
class RegisterPoint[T](Point[T]):
    """A value in one register of the device."""
    _: KW_ONLY
    register: int = 0

    @property
    def readable(self) -> bool:
        return True

    @property
    def writable(self) -> bool:
        return False


TEMPERATURE = Key("temperature", float)

clock = FakeClock()
scheduler = Timing().scheduler(clock)
scheduler.set_points([RegisterPoint(TEMPERATURE, register=1)])
scheduler.set_polled(TEMPERATURE, True)

assert scheduler.due() == ["temperature"]  # never read, so due now

value = DataValue(21.5, Quality.GOOD, clock.now(), raw=(215,))  # as your protocol decoded it
scheduler.record(TEMPERATURE, value, success=True)
assert scheduler.due() == []  # due again after its poll interval
```

## Example: a complete client

The client below reads an imaginary device that answers a list of register numbers with their
values, or not at all. `send` stands in for the protocol; every other call the `Client` class
makes is to event_connect. At the end, `main()` runs it against a fake device and a fake clock.

```python
import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from typing import Any

from event_connect import (
    CircuitBreaker, Clock, DataValue, Key, Passes, Point, Quality, Reachability, Status,
    StatusBoard, Subscriptions, SystemClock, Timing, ValueCallback, stale,
)
from event_connect.testing import FakeClock


# 1. Points: subclass Point to add the value's address, and declare whether it can be
#    read and written.
@dataclass(frozen=True, eq=False)
class RegisterPoint[T](Point[T]):
    """A value in one register of the device, in tenths."""
    _: KW_ONLY
    register: int = 0

    @property
    def readable(self) -> bool:
        return True

    @property
    def writable(self) -> bool:
        return False


TEMPERATURE = Key("temperature", float)
POINTS = [RegisterPoint(TEMPERATURE, register=1)]

# 2. Timing: the interval for each poll rate, and how long the device may be silent before
#    it counts as offline.
TIMING = Timing(offline_after=30.0)

Send = Callable[[Sequence[int]], Awaitable[Mapping[int, int] | None]]


class Client:
    def __init__(self, send: Send, clock: Clock | None = None) -> None:
        self._send = send  # the protocol: register numbers in, values out, None if no reply
        self._clock = clock or SystemClock()
        self._points: dict[str, RegisterPoint[Any]] = {point.key: point for point in POINTS}
        self._values: dict[str, DataValue[Any]] = {}
        self._scheduler = TIMING.scheduler(self._clock)
        self._scheduler.set_points(POINTS)
        self._subscriptions = Subscriptions()
        self._reachability = Reachability(self._clock, TIMING.offline_after, name="The device")
        self._statuses = StatusBoard(self._clock)
        self._breaker = CircuitBreaker(after=2).breaker()
        self._passes = Passes()

    # 3. Subscribing: a subscribed key is polled, and its subscriber is told when the
    #    quality changes or the value moves by at least the point's deadband.
    def subscribe(self, key: Key[Any], callback: ValueCallback[Any]) -> None:
        self._subscriptions.add(key, callback, polls=True)
        self._scheduler.set_polled(key, True)

    # 4. Polling: read what is due, one pass at a time. Call poll() again at the monotonic
    #    time self._scheduler.next_due() returns; None means nothing will be due.
    async def poll(self) -> None:
        await self._passes.run(self._pass, due=lambda: bool(self._scheduler.due()))

    async def _pass(self) -> None:
        points = [self._points[key] for key in self._scheduler.due()]
        if not points:
            return
        answer = await self._request([point.register for point in points])
        for point in points:
            previous = self._values.get(point.key)
            if answer is None:
                data = stale(previous, self._clock.now())
            else:
                raw = answer[point.register]
                data = DataValue(raw / 10, Quality.GOOD, self._clock.now(), raw=(raw,))
            self._values[point.key] = data
            self._subscriptions.report(point, data)
            self._scheduler.record(point.key, data, success=answer is not None)

    # 5. Sending a request: skipped while the circuit breaker is open. Every outcome,
    #    including a skipped request, is reported to the breaker and to Reachability, and
    #    the resulting online state is published as Status.CONNECTED.
    async def _request(self, registers: Sequence[int]) -> Mapping[int, int] | None:
        attempt = self._breaker.attempt(self._clock.monotonic())
        if attempt is None:
            self._statuses.set(Status.CONNECTED, self._reachability.unanswered())
            return None
        with attempt:
            answer = await self._send(registers)
            if answer is None:
                attempt.unanswered(self._clock.monotonic())
                self._statuses.set(Status.CONNECTED, self._reachability.unanswered())
            else:
                attempt.answered()
                self._statuses.set(Status.CONNECTED, self._reachability.answered(self._scheduler))
        return answer


async def device(registers: Sequence[int]) -> Mapping[int, int]:
    return {register: 215 for register in registers}


async def main() -> None:
    client = Client(device, clock=FakeClock())
    seen: list[float | None] = []
    client.subscribe(TEMPERATURE, lambda key, old, new: seen.append(new.value))
    await client.poll()
    assert seen == [21.5]


asyncio.run(main())
```

A real client also:
- runs a loop that sleeps until the time `next_due()` returns;
- handles writes: it validates the value against the point's `limits`, waits
  `Timing.read_back_delay(point)`, and schedules the point's `on_write` refresh;
- compares each new value with the last one using `changed(old, new, point.on_change.when)`,
  and schedules the point's `on_change` refresh when it has changed;
- marks points with `poll_always` as polled, and keeps `set_polled` in step with
  `Subscriptions.polled()` when a subscriber leaves;
- passes `retry_after` to `record()` when its protocol wants a failed read retried sooner.

## How it works

### Points

A `Point[T]` describes how one value behaves:
- `poll_rate`: how often it is read.
- `poll_always`: read even when nobody subscribes, because the client itself needs the value.
- `deadband`: the smallest change that is reported.
- `limits`: what may be written.
- `unit`: the unit of the value.
- `write_kind`: whether a write is a setting or a command. `pulse` makes a command return to
  its idle value by itself: write, wait, write the idle value.
- `read_back_after`: how long a write takes to show, where this point differs from its device.
- `on_write`, `on_change`: the follow-up reads a write or a change triggers.
- `labels`: tags that a `Refresh` can select points by.

A point validates itself when it is created, and raises one error that lists every
inconsistency. Your subclass adds where the value is stored. It overrides `readable` and
`writable` to say which directions it supports, and `problems()` to add its protocol's own
checks.

### Follow-up reads

Devices do not push updates, and points are read at different rates. When one value changes, a
value that depends on it may not be read again for a long time. A `Refresh(targets, after,
until_stable, when=...)` schedules extra reads of those dependent points:
- It reads `targets` `after` seconds after a write (`on_write`) or a change (`on_change`).
- With `until_stable` set, it keeps reading them every `after` seconds until two reads in a row
  agree, for at most `until_stable` seconds from the write or change. Two reads agree when they
  have the same quality and equal values, or values within the point's `deadband` where it has
  one. A failed read neither ends it nor counts.
- `when` limits the trigger to a value that rises or one that falls.

If `after` is `None`, a refresh triggered by a write waits `Timing.read_back_delay(point)`. That
is the point's `read_back_after`, or the device's `Timing.read_back_after` when the point has
none. A refresh triggered by a change runs at once.

### Scheduling

The scheduler decides what to read; your client performs the reads.
- `due()` lists the keys to read now, in this order:
  1. extra reads, both refreshes and retries asked for with `retry_after`, the earliest first;
  2. keys never read;
  3. the most overdue keys.
- After reading, your client calls `record()` for each key. This also advances any
  `until_stable` refresh in progress.
- `next_due()` returns the monotonic time at which something is next due, or `None` if nothing
  ever will be.
- Only keys marked polled with `set_polled(key, True)` are read on their interval or by a
  refresh. A forced refresh (`refresh(..., force=True)`) reads any key.

Three rules hold throughout:
- **One request at a time.** Keep one request in flight per device, and read everything `due()`
  lists in as few requests as the protocol allows. What fell due while a slow reply was awaited
  goes out together in the next request. With `Passes`, a call made during a pass waits for it,
  then makes its own pass only if something is still due.
- **Refreshes don't shift the schedule.** An extra read does not delay the key's next regular
  read, so keys that are polled together stay in the same request.
- **Your protocol decides when to retry.** Only the protocol knows what a failure means: a busy
  device, a gateway that has no data yet, or a device that has stopped answering. Pass
  `retry_after` to `record()` to ask for a failed read to be retried that many seconds later;
  without it, the read waits for its next regular turn. No poll interval and no retry is shorter
  than `Timing.min_poll_interval`; a refresh reads when it says.

### Unresponsive devices

- **One lost reply is not an outage.** `Reachability` reports a device online as soon as it
  answers. It reports it offline at the first unanswered request made at least `offline_after`
  seconds after the first unanswered one. Tell it about every request, including one the
  breaker skips. A device counts as offline until it first answers.
- **Missed reads are caught up when the device answers again.** After a silence,
  `answered(scheduler)` makes every key whose last read failed due at once. If the device had
  counted as offline, it makes every polled key due as if it had never been read, and drops
  pending refreshes and retries. Going offline and coming back online are each logged once, at
  INFO level.
- **A silent device is not asked again and again.** A `Breaker` refuses requests for a pause
  after a number of unanswered requests in a row, then lets one probe through. `attempt()`
  returns a handle for one request, on which you report its outcome. Used as a context manager,
  it releases the probe if no outcome was reported, so a cancelled request does not block later
  ones. With a `retry`, the pauses are its delays, and once it gives up (`gave_up`) nothing goes
  through until `reset()`, as when the device is connected afresh. Before letting a probe go,
  ask `await retry.ready()`; if it says no, `postpone(now)` waits the same pause again.

### Retry policies

These objects only make decisions; your protocol code asks them and acts:

```python
from event_connect import Attempts, CircuitBreaker, Exponential, Fixed, Jitter, Retry, Steps, Within

busy = Retry(wait=Exponential(0.2, factor=2), stop=Attempts(4))                     # a busy reply
no_data_yet = Retry(wait=Steps(0.5, then=Fixed(1)), stop=Within(7.5))               # a gateway with no data yet
silent = CircuitBreaker(after=3, pause=Jitter(Exponential(10, factor=2, max=120)))  # a device that stopped answering
reconnect = CircuitBreaker(after=3, retry=Retry(Exponential(2, max=10), Attempts(8)))  # ask again, 8 times

assert busy.next_delay(attempts=1, elapsed=0.0) == 0.2  # None once it is time to give up
assert Retry(Fixed(10)).next_delay(attempts=1000, elapsed=86400.0) == 10  # no stop: never gives up
```

A retry that checks something before each try is a subclass with its own `ready`:

```python
from dataclasses import dataclass

from event_connect import Exponential, Retry


@dataclass(frozen=True)
class WhenOnline(Retry):
    online: bool = True

    async def ready(self) -> bool:
        return self.online             # ask your own check: a ping, the OS, the app


retry = WhenOnline(Exponential(2, max=10), online=False)
```

| Part | Decides |
|---|---|
| `Fixed(s)`, `Exponential(start, factor, max)`, `Steps(a, b, ..., then=)`, `Jitter(wait, spread)` | how long to wait before the next try |
| `Attempts(n)`, `Within(s)`, combined with `\|` | when to give up |
| `Retry(wait, stop)` | the delay before each retry, until the stop condition is met; without `stop`, forever |
| `RECONNECT` | `Retry(Exponential(2, max=10))`: 2, 4 and 8 s, then every 10 s, never giving up |
| `CircuitBreaker(after, pause, retry)` | when to stop asking a silent device, for how long, and when to let one probe through |

Make these policies part of your device definition, with defaults that users of your client can
override.

## Measuring a device

Base the delays in `Timing` and in each `Refresh` on measurements of a real device, not on
guesses. Record response times in a `Latency`, and the readings after a change in a `Settling`.
`recommended_refresh()` derives `after` and `until_stable` from the slowest settling time:

```python
from event_connect.testing import Latency, Settling, recommended_refresh

latency = Latency(answers=(0.04, 0.05, None, 0.06))  # seconds per request; None: no reply
assert latency.slowest == 0.06 and latency.unanswered == 1

# A fan speed read once a second after it was set: it settles 4 s after the change.
fan = Settling("fan speed 1 to 3", readings=((1, 600), (2, 900), (3, 1180), (4, 1200), (5, 1205)),
               tolerance=20)
assert recommended_refresh((fan,), every=1) == (4, 8)  # after=4, until_stable=8
```

## API overview

Everything is imported from `event_connect`, and test support from `event_connect.testing`.

**Describing points**
- `Key[T]`: the typed name of a point. `is_key()` and `is_state_type()` check a value and a type.
- `Point[T]`: the base class for your points.
- `PollRate`, `Limits`, `Unit`, `WriteKind`, `Pulse`: parts of a point.
- `Transform`, `Transforms`: conversions between the device's value and the value shown.
- `Certainty`: how certain it is that a point's address, conversion and meaning are right.
- `VALUE_TYPES`, `is_instance()`: the types a value may have, and a check for one.

**Values**
- `DataValue[T]`: a value with its `Quality`, the time it was read, and the raw reply.
- `Value`: the type of a point's value.
- `stale()`: the previous value, marked stale, for use when a read fails.

**Scheduling**
- `Timing`, `DEFAULT_TIMING`, `DEFAULT_INTERVALS`: poll intervals and waits for a device.
- `Scheduler`: decides which keys are due.
- `Passes`: runs one polling pass at a time.

**Follow-up reads**
- `Refresh`: extra reads after a write or a change.
- `Change`, `changed()`: which changes trigger a refresh, and the check for one.
- `Labels`, `Selector`, `selector()`, `select()`: choosing the points a refresh reads.

**Notifications**
- `Subscriptions`, `Subscriber`, `ValueCallback`, `tell()`: subscribers to values and the calls
  that notify them.
- `Status`, `StatusBoard`, `StatusCallback`: client state that is not a point, such as whether
  the device is connected.

**Writes**
- `Write[T]`: one write of a sequence.

**Unresponsive devices and retries**
- `Reachability`: whether the device is online.
- `CircuitBreaker`, `Breaker`, `Attempt`: when to stop asking a silent device.
- `Retry`, `NO_RETRY`, `RECONNECT`: how a failed request is retried, and a silent device asked
  again.
- `Wait` with `Fixed`, `Exponential`, `Steps`, `Jitter`: delays between tries.
- `Stop` with `Attempts`, `Within`, `AnyOf`: when to give up.

**Exceptions**
- `ClientError`, and its subclasses `CannotConnectError`, `NotConnectedError`,
  `ReadOnlyError`, `UnsupportedDeviceError` and `AuthenticationError`.
- `InvalidValueError` and `ModelError`, which are `ValueError` subclasses rather than
  `ClientError` ones.

**Time**
- `Clock`: the interface for a clock. `SystemClock` is the real one.

**Testing** (`event_connect.testing`)
- `FakeClock`: a clock that moves only when told.
- `FakePoint`: a point without a protocol.
- `Latency`, `Settling`, `recommended_refresh()`: turning measurements into waits.

## Versioning

event_connect follows semantic versioning. Before 1.0, a minor version may break the API; from
1.0 on, only a major version may.

A Python environment holds one version of each package. An application that uses two packages
built on event_connect therefore gets one copy of it, and that copy must satisfy both. If one of
them pinned an exact version, the other would have to want that same version, or the two could
not be installed together. So require a range: from the version whose features you use, up to
the next version that may break the API.

## License

MIT. See [LICENSE](LICENSE).
