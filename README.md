# event_connect

The part of a device client that has nothing to do with the protocol.

Say you write a Python client for a kind of device: a Modbus controller, a ventilation unit that
speaks UDP, anything that is read and written point by point. Talking to the device is the small
part. The rest is the same whatever the protocol:
- deciding what to read when;
- telling subscribers when a value changes;
- reading again what a write or a change affects;
- keeping the last value when an answer is lost;
- deciding when the device counts as gone;
- not hammering a device that has stopped answering.

That rest is this library. Your package adds the protocol: where each value lives, how it is
encoded, and how a request is sent. This library sends nothing, sleeps for nothing and needs
nothing but the standard library, so all of it can be tested without a device.

## Installation

```bash
pip install event-connect
```

In your package's `pyproject.toml`, require a range of versions, not one version:

```toml
dependencies = ["event_connect>=0.3,<0.4"]
```

A Python environment holds one version of each package. An application that uses two packages
built on `event_connect` therefore gets one copy of it, and that copy must satisfy both. If one of
them pinned an exact version, the other would have to want that same version, or the two could
not be installed together. A range, from the version whose features you use up to the next one
that may break something, lets one copy serve every package built on it. Before 1.0 that next
one is the next minor version; from 1.0 on, the next major version.

## Import everything from `event_connect`

```python
from event_connect import Key, Point, Scheduler, Subscriptions
```

Everything you use is importable from `event_connect` itself, or from `event_connect.testing` for
tests. The files in the package start with an underscore (`_point.py`, `_scheduler.py`, ...).
Python's convention says those are private: they are how this library is organised inside, and a
file can be split, merged or renamed in any release. Never import from them. The names they hold
are the public API, and those are what the version numbers protect.

## What you get

| For | Names |
|---|---|
| Describing a value | `Key[T]`, a point's name carrying the type of its value. `Point[T]`, which you subclass. Its parts: `PollRate`, `Limits`, `Unit`, `WriteKind`, `Pulse`, `Transform` |
| A value read | `DataValue[T]`, a value with its `Quality` and when it was read. `stale()`, the last good value kept when an answer is lost |
| Reading on time | `Timing`, a device's poll intervals and waits. `Scheduler`, which keys are due now. `Passes`, one pass at a time |
| Reading again after a write or a change | `Refresh`, `Change`, `Labels`, `select` |
| Telling subscribers | `Subscriptions`, `ValueCallback`. `StatusBoard`, `Status`, for what the client knows apart from the points, such as whether the device answers |
| A device that is busy or silent | `Reachability`, whether it counts as answering. `CircuitBreaker` and `Breaker`, when to stop asking. `Retry`, `Fixed`, `Exponential`, `Steps`, `Jitter`, `Attempts`, `Within`, how to try again |
| Errors a client raises | `ClientError` and its kinds: `CannotConnectError`, `NotConnectedError`, `ReadOnlyError`, `InvalidValueError`, `UnsupportedDeviceError`, `ModelError`, `AuthenticationError` |
| Time | `Clock`, `SystemClock` |
| Tests (`event_connect.testing`) | `FakeClock`, a clock that moves only when told. `FakePoint`, a point without a protocol. `Latency`, `Settling` and `recommended_refresh`, to turn measurements on a real device into waits |

## A client in one page

This is a whole client for an imaginary device that answers a list of register numbers with
their values, or not at all. Everything but `send` is this library's.

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

# 1. Points: subclass Point with where the value lives, and say which sides it has.
@dataclass(frozen=True, eq=False)
class RegisterPoint[T](Point[T]):
    """A value in one register, in tenths."""
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

# 2. Timing: how often each poll rate is read, and how long the device may stay silent.
TIMING = Timing(offline_after=30.0)

Send = Callable[[Sequence[int]], Awaitable[Mapping[int, int] | None]]

class Client:
    def __init__(self, send: Send, clock: Clock | None = None) -> None:
        self._send = send                     # the protocol: registers in, values out, None if silent
        self._clock = clock or SystemClock()
        self._points = {point.key: point for point in POINTS}
        self._values: dict[str, DataValue[Any]] = {}
        self._scheduler = TIMING.scheduler(self._clock)
        self._scheduler.set_points(POINTS)
        self._subscriptions = Subscriptions()
        self._reachability = Reachability(self._clock, TIMING.offline_after, name="The unit")
        self._statuses = StatusBoard(self._clock)
        self._breaker = CircuitBreaker(after=2).breaker()
        self._passes = Passes()

    # 3. Subscribing: a subscribed key is polled, and told of every change.
    def subscribe(self, key: Key[Any], callback: ValueCallback[Any]) -> None:
        self._subscriptions.add(key, callback, polls=True)
        self._scheduler.set_polled(key, True)

    # 4. Polling: read what is due, one pass at a time. Call this again after
    #    self._scheduler.next_due() seconds, as told.
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

    # 5. A request: not sent while the breaker is open, and every outcome told to the
    #    breaker and to reachability, which keeps Status.CONNECTED.
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

A real client adds writes, which go through `Timing.read_back_delay` and the points' `on_write`.
It also adds a loop that sleeps until `next_due()`.

## How the parts behave

### A point

`Point[T]` holds how a value behaves:
- how often it is read (`poll_rate`);
- what may be written (`limits`);
- its `unit`;
- whether it is a setting or a command (`write_kind`);
- what its write or its change sets off (`on_write`, `on_change`).

It refuses a contradiction when it is built, and names every problem at once. Your subclass adds
where the value lives and how it is encoded. Its `readable` and `writable` say which sides it
has, and its `problems()` adds the protocol's own checks.

### Reading again after a write or a change

A device sends nothing by itself, and its points are read at different rates. So a change of one
point can come long before another point that follows from it is read. `Refresh(targets, after,
until_stable, when=...)` names those other points:
- It reads `targets` `after` seconds after a write (`on_write`) or a change (`on_change`).
- With `until_stable`, it reads them again every `after` seconds while they still change, for at
  most that long. Two reads in a row that agree end it: the same quality, and values no further
  apart than the point's `deadband`.
- `when` limits a change to one that rises or falls.

After a write, an `after` left as None waits as long as the written point takes to read back (its
`read_back_after`). After a change it waits not at all.

### The scheduler

The scheduler decides; your client reads.
- `due()` lists the keys to read now, in this order:
  1. extra reads asked for by a refresh;
  2. keys never read;
  3. the most overdue.
- Your client reads them, then `record()`s each outcome. That also moves a read-until-settled
  along.
- `next_due()` says when there is something to do next.
- Only polled keys are read on their interval or by a refresh: those a subscriber asked for, or
  marked `poll_always`. A forced refresh reads any key.

Three rules hold throughout:
- **One request at a time.** Keep one request in flight per device. Read everything `due()`
  lists in as few requests as the protocol allows: whatever fell due while a slow answer was
  awaited goes out together in the next. `Passes` keeps polls made together to one pass.
- **Each key keeps its rhythm.** A read a refresh asked for does not move the next regular one.
  So keys read together go on being read together, in one request, whatever is read in between.
- **A failed read is tried again when the protocol says so.** Only the protocol knows what a
  failure means: a busy device, a gateway that has nothing yet, or a device gone silent behind
  its own backoff. So the protocol says, when it records a read, how soon it wants it read again
  (`record(..., retry_after=...)`). Without that, the read waits for its next turn. The
  scheduler never reads a key sooner than `min_poll_interval`.

### A device that stops answering

- **One lost answer is not an outage.** `Reachability` says a device answers as soon as it does,
  and that it does not only once it has been silent for `offline_after` seconds, counted from the
  first unanswered request. Meanwhile the values are `stale()`, keeping the last good ones.
- **What was missed is read when it answers.** `answered(scheduler)` makes due at once what
  failed while the device was silent. If the device had counted as not answering, it makes
  everything due. The stop and the return are each logged once, at INFO.
- **A silent device is not asked again and again.** A `Breaker` refuses requests for a pause
  after `after` unanswered ones in a row, then lets one probe through. `attempt()` gives you one
  request to tell the outcome of; used with `with`, it releases a probe whose outcome was never
  told, so a cancelled request does not block the next.

Each of these parts decides and does nothing; your protocol asks it and acts:

```python
from event_connect import Attempts, CircuitBreaker, Exponential, Fixed, Jitter, Retry, Steps, Within

busy = Retry(wait=Exponential(0.2, factor=2), stop=Attempts(4))                     # a busy answer
zeros = Retry(wait=Steps(0.5, then=Fixed(1)), stop=Within(7.5))                     # a gateway with nothing yet
silent = CircuitBreaker(after=3, pause=Jitter(Exponential(10, factor=2, max=120)))  # a device gone silent

assert busy.next_delay(attempts=1, elapsed=0.0) == 0.2   # None once it is time to give up
```

| Part | Decides |
|---|---|
| `Fixed(s)`, `Exponential(start, factor, max)`, `Steps(a, b, ..., then=)`, `Jitter(wait, spread)` | how long to wait before the next try |
| `Attempts(n)`, `Within(s)`, and `a \| b` | when to give up |
| `Retry(wait, stop)` | the wait before each try again, until it gives up |
| `CircuitBreaker(after, pause)` | when to stop asking a silent device, for how long, and to let one probe through after |

Let a device model choose these in its options, and let whoever creates the device override the
model. Then every protocol says them the same way.

## Measuring a device

The waits in `Timing` and in each `Refresh` should come from the device, not from guesses:
- Time its answers into a `Latency`.
- Record the readings after a change into a `Settling`.
- `recommended_refresh` turns the slowest settling into an `after` and an `until_stable`.

## License

MIT
