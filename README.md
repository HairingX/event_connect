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
| `_timing` | `Timing`: a library's poll intervals, read-back wait, retry wait and grace before a device counts as not answering, with `DEFAULT_TIMING` |
| `_reachability` | `Reachability`: whether a device answers, as its consumers should see it |
| `_events` | `Subscriptions`: who is told what, and when a change is a change |
| `_status` | `Status`: what a client knows of its device apart from its points |
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

**A failed read is tried again soon.** With `retry_after`, a polled key whose read failed is due
again that many seconds later, then twice as long after each further failure, but never later
than its next regular read - so a point read every 15 minutes is not left stale for 15 minutes by
one lost answer.

**One lost answer is not an outage.** `Reachability` says a device answers as soon as it does,
and that it does not only once it has been silent for `offline_after` seconds, counted from the
first unanswered request. Meanwhile its values are stale - the last good ones - and the retries
keep asking.

## Building a protocol package on it

- **Points:** subclass `Point` with where a value lives and how it is encoded; say through
  `readable` and `writable` which sides it has; add the protocol's own checks to `problems()`.
- **Timing:** give the package one `Timing`, measured on its devices: the poll intervals, how
  long a write takes to show, how soon a failed read is tried again, how long a device may be
  silent. A client takes another where a device needs it. How long one request may take, how often
  it is resent at once, and any gap a connection needs between requests belong to the connection,
  not to the timing.
- **Client:** keep one request in flight per device. Read what `due()` lists in as few requests
  as the protocol allows, `record()` every key read with whether it was answered, tell a
  `Reachability` of every request, answered or not, and sleep until `next_due()` - or for a short
  tick, whichever comes first - between passes.
- **Refreshes:** name in `on_change` what a change affects and in `on_write` what a write
  disturbs, with the waits and `until_stable` measured on a device, and a `deadband` on a value that
  jitters, so that it can be seen to settle.
- **Measuring:** time a device's answers into a `Latency`, and the readings after a change into a
  `Settling`; `recommended_refresh` turns the slowest settling into an `after` and an
  `until_stable`.

## License

MIT
