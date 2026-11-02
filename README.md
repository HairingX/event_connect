# event_connect

Devices described by their points, independent of protocol. A protocol package - the one that
knows where a value lives and how it is encoded - builds its points and its client on these.

Nothing here performs I/O, sleeps, or knows a protocol, and it depends on nothing but the
standard library.

## Installation

```bash
pip install event-connect
```

A package built on this one requires a range of versions, such as `event_connect>=0.1,<0.2`:
every package installed in one Home Assistant shares one copy of it.

## What is here

| Module | What it holds |
|---|---|
| `_key` | `Key[T]`: a point's key, its text at runtime, carrying the type of its value |
| `_value` | `DataValue[T]` and `Quality`: a value, how far it can be trusted, when and what the device said |
| `_point` | `Point[T]`, by its behaviour, and its parts: `PollRate`, `Limits`, `Refresh`, `Change`, `Labels`, `Pulse`, `WriteKind`, `Transform` |
| `_scheduler` | `Scheduler`: which keys are due for a read, and when |
| `_timing` | `Timing`: a library's poll intervals, read-back wait and grace before a device counts as not answering, with `DEFAULT_TIMING` |
| `_resilience` | The parts a protocol assembles its riding out of a busy, slow or silent device from: `Fixed`, `Exponential`, `Steps`, `Jitter`; `Attempts`, `Within`; `Retry`; `CircuitBreaker` |
| `_passes` | `Passes`: one pass at a time over what is due; a poll made during one waits for it |
| `_reachability` | `Reachability`: whether a device answers, as its consumers should see it, and what to read when it answers again |
| `_events` | `Subscriptions`: who is told what, and when a change is a change |
| `_status` | `Status` and `StatusBoard`: what a client knows of its device apart from its points, and who is told when it changes |
| `_unit` | `Unit`: units of measurement, with their UCUM codes |
| `_certainty` | `Certainty`: how certain it is that a point is what its model says |
| `_errors` | The errors a client raises |
| `_clock` | `Clock`: the monotonic and the wall clock, behind one replaceable object |
| `_writes` | `Write[T]`: one write of a sequence |
| `testing` | `FakeClock`; `FakePoint`, a point without a protocol; and `Latency`, `Settling` and `recommended_refresh`, for what a measurement on a device says |

## A point

`Point[T]` holds how a value behaves: how often it is read (`poll_rate`), what may be written
(`limits`), its `unit`, whether it is a setting or a command (`write_kind`), and what its write
or its change sets off (`on_write`, `on_change`). It refuses a contradiction when it is built,
naming every problem at once.

A protocol subclasses it with where the value lives and how it is encoded, says through
`readable` and `writable` which sides it has, and adds its own problems to `problems()`.

## Reading again

The device sends nothing by itself, and its points are read at different rates, so a change of
one can come long before another that follows from it is read. `Refresh(targets, after,
until_stable, when=...)` names those: read `targets` `after` seconds after a write (`on_write`) or
a change (`on_change`), and with `until_stable`, again every `after` seconds while they still
change, for at most that long - two reads in a row that agree end it, as the same quality and
values no further apart than the point's `deadband`. `when` limits a change to one that rises or
falls.

After a write, `after` left as None waits as long as the written point takes to read back, its
`read_back_after`; after a change, not at all.

## Polling

The scheduler decides; the client reads. `due()` lists the keys to read now, in order: extra
reads asked for by a refresh, then keys never read, then the most overdue. The client reads them,
then `record()`s each outcome, which also moves a read-until-settled along. `next_due()` says when
there is something to do next. Only polled keys - those a consumer subscribed to, or asked to be
polled - are read on their interval or by a refresh; a forced refresh reads any.

**One request at a time.** A client keeps one request in flight per device, and reads everything
`due()` lists when the line is free in as few requests as the protocol allows: whatever fell due
while a slow answer was awaited goes out together in the next.

**Each key keeps its rhythm.** A read a refresh or a retry asked for does not move the next
regular one, so keys read together go on being read together, in one request, whatever is read
in between. Nothing is read early to join another request: a refresh waits for a reason.

**A failed read is tried again when the protocol says so.** Only the protocol knows what a
failure means - a busy device, a gateway that has nothing yet, a device gone silent behind its own
backoff - so it says, when it records a read, how soon it wants it read again; without that, the
read waits for its rhythm. A device that answers again after silence is best read in full at once,
which `reset()` does.

**One lost answer is not an outage.** `Reachability` says a device answers as soon as it does,
and that it does not only once it has been silent for `offline_after` seconds, counted from the
first unanswered request. Meanwhile its values are stale - the last good ones. Given the
scheduler, `answered(scheduler)` makes due at once what failed while the device was silent, and
everything once it had counted as not answering; that it stopped answering and answers again is
logged once each.

## Building a protocol package on it

- **Points:** subclass `Point` with where a value lives and how it is encoded; say through
  `readable` and `writable` which sides it has; add the protocol's own checks to `problems()`.
- **Timing:** give the package one `Timing`, measured on its devices: the poll intervals, how
  long a write takes to show, how long a device may be silent. A client takes another where a
  device needs it. How long one request may take and any gap a connection needs between requests
  belong to the connection, not to the timing.
- **Riding out failures:** assemble it from the parts in `_resilience`, so that every protocol
  says it the same way and a model can choose its own: a `Retry` of a `Wait` and a `Stop` for what
  is tried again at once, such as a busy answer; a `CircuitBreaker` for a device gone silent, so
  that it is not asked again and again; and a `retry_after` given to `record()` for a read the
  device should be asked for again soon. Let a model set them in its options, and whoever creates
  the device override the model.
- **Client:** keep one request in flight per device, and run each pass through `Passes`, so
  that polls made together cause one pass. Read what `due()` lists in as few requests
  as the protocol allows, `record()` every key read with whether it was answered, tell a
  `Reachability` of every request, answered or not, keep the statuses in a `StatusBoard`, and
  sleep until `next_due()` - or for a short tick, whichever comes first - between passes.
- **Refreshes:** name in `on_change` what a change affects and in `on_write` what a write
  disturbs, with the waits and `until_stable` measured on a device, and a `deadband` on a value that
  jitters, so that it can be seen to settle.
- **Measuring:** time a device's answers into a `Latency`, and the readings after a change into a
  `Settling`; `recommended_refresh` turns the slowest settling into an `after` and an
  `until_stable`.

## Riding out failures

Each part decides, and does nothing: a protocol asks it and acts.

```python
from event_connect import Attempts, CircuitBreaker, Exponential, Fixed, Jitter, Retry, Steps, Within

busy = Retry(wait=Exponential(0.2, factor=2), stop=Attempts(4))                 # a busy answer
zeros = Retry(wait=Steps(0.5, then=Fixed(1)), stop=Within(7.5))                 # a gateway with nothing yet
silent = CircuitBreaker(after=3, pause=Jitter(Exponential(10, factor=2, max=120)))  # a device gone silent

delay = busy.next_delay(attempts=1, elapsed=0.0)   # 0.2; None once it is time to give up
breaker = silent.breaker()                         # one per device
attempt = breaker.attempt(now)                     # None while it is open
if attempt is not None:
    with attempt:                                  # a probe never told its outcome is released
        ...                                        # send; then attempt.answered() or attempt.unanswered(now)
```

| Part | Decides |
|---|---|
| `Fixed(s)`, `Exponential(start, factor, max)`, `Steps(a, b, ..., then=)`, `Jitter(wait, spread)` | how long to wait before the next try |
| `Attempts(n)`, `Within(s)`, and `a \| b` | when to give up |
| `Retry(wait, stop)` | the wait before each try again, until it gives up |
| `CircuitBreaker(after, pause)` | when to stop asking a silent device, for how long, and to let one probe through after |

## License

MIT
