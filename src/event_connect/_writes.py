"""Writes: one write of a sequence, and the record of the writes sent to a device."""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from enum import Enum, StrEnum
from typing import Any

from ._clock import Clock
from ._key import Key
from ._value import DataValue, Quality


@dataclass(frozen=True)
class Write[T]:
    """One write of a sequence: `value` to the point `key` names."""
    key: Key[T]
    value: T


class WriteOutcome(StrEnum):
    """How a write sent to a device ended. Stored by its text, `WriteOutcome("taken")`."""

    PENDING = "pending"
    """Sent, and not yet ended."""
    TAKEN = "taken"
    """The device answered that it took the value."""
    SENT = "sent"
    """Sent where the protocol gives no answer: taken as far as anyone can tell."""
    REFUSED = "refused"
    """The device answered, and did not take the value: busy, refused it, or does not have the
    point."""
    NO_ANSWER = "no_answer"
    """The device did not answer."""
    OVERTAKEN = "overtaken"
    """A newer value for the point took its place before the device took it, and it was not sent
    again."""
    ERROR = "error"
    """Anything else: an answer that could not be read, or the write was given up while sent."""


@dataclass(frozen=True, kw_only=True)
class WriteRecord:
    """One write sent to a device: what was asked and sent, how it ended, and the first read of the
    point after it ended."""
    key: str
    number: int
    """Its place among the writes the log has recorded, counting from 1, whatever their key."""
    value: object
    """The value asked for."""
    raw: tuple[int, ...]
    """What was sent, in wire order, as the protocol counts it: registers, bits or bytes."""
    secret: bool = False
    """Whether the point is a credential: then `value` is None, `raw` is empty and `read_back`
    stays None, so the record says only that the write was sent, when, how often and how it
    ended."""
    sent_at: datetime
    """When it was first sent - timezone-aware UTC."""
    attempts: int
    """How many times it was sent."""
    outcome: WriteOutcome
    detail: str
    """What the device answered, in the protocol's words, where the outcome alone does not say:
    such as which status it refused the write with."""
    ended_at: datetime | None
    """When it ended; None while `PENDING`."""
    read_back: DataValue[Any] | None
    """The first read of the point after the write ended that the device answered, whatever it
    answered; None until there is one."""

    def diagnostics(self) -> dict[str, object]:
        """The record as plain data: numbers, text, lists and None, with times in ISO 8601 and a
        state by its name; `read_back` holds its `value`, `quality`, `raw` and `at`."""
        read_back = self.read_back
        return {
            "number": self.number,
            "value": _plain(self.value),
            "raw": list(self.raw),
            "sent_at": self.sent_at.isoformat(),
            "attempts": self.attempts,
            "outcome": str(self.outcome),
            "detail": self.detail,
            "ended_at": None if self.ended_at is None else self.ended_at.isoformat(),
            "read_back": None if read_back is None else {
                "value": _plain(read_back.value),
                "quality": read_back.quality.name,
                "raw": list(read_back.raw),
                "at": read_back.timestamp.isoformat(),
            },
        }


class WriteLog:
    """The latest writes sent to each point of one device, how each ended, and the read that came
    after it, so that a write can be shown to have reached the device.

    Only what is sent is recorded: a value refused before sending, or overtaken before it was
    first sent, is not. Of a write to a secret point, neither the value, nor what was sent, nor
    what was read after it is kept.
    """

    def __init__(self, clock: Clock, *, per_key: int) -> None:
        """Keep the latest `per_key` writes of each key, stamped by `clock`.

        Raises:
            ValueError: `per_key` is below 1.
        """
        if per_key < 1:
            raise ValueError(f"per_key must be at least 1, got {per_key}")
        self._clock = clock
        self._per_key = per_key
        self._records: dict[str, deque[WriteRecord]] = {}
        self._count = 0

    def sent(self, key: str, value: object, raw: Sequence[int], *, secret: bool = False) -> WriteRecord:
        """Record `value` sent to `key` as `raw`, now, once and `PENDING`; the oldest record of
        `key` gives way once it has `per_key`.

        Args:
            secret: `key` is a credential: the record keeps neither `value` nor `raw`, and
                takes no read-back.
        """
        self._count += 1
        record = WriteRecord(key=key, number=self._count, value=None if secret else value,
                             raw=() if secret else tuple(raw), secret=secret,
                             sent_at=self._clock.now(), attempts=1, outcome=WriteOutcome.PENDING,
                             detail="", ended_at=None, read_back=None)
        self._records.setdefault(key, deque(maxlen=self._per_key)).append(record)
        return record

    def resent(self, record: WriteRecord) -> WriteRecord:
        """Count one more sending of the pending `record`.

        Returns:
            The record as it now stands.

        Raises:
            ValueError: `record` has ended.
        """
        return self._update(record, lambda current: replace(current, attempts=current.attempts + 1))

    def ended(self, record: WriteRecord, outcome: WriteOutcome, *, detail: str = "") -> WriteRecord:
        """Record how the pending `record` ended, now.

        Returns:
            The record as it now stands.

        Raises:
            ValueError: `outcome` is `PENDING`, or `record` has ended.
        """
        if outcome is WriteOutcome.PENDING:
            raise ValueError("a write cannot end pending")
        now = self._clock.now()
        return self._update(record, lambda current: replace(current, outcome=outcome, detail=detail, ended_at=now))

    def read(self, key: str, value: DataValue[Any]) -> None:
        """Note a read of `key`: the read-back of its latest write, if that has ended, has none,
        and is not secret.

        A read the device did not answer, which is `STALE`, is no read-back.
        """
        records = self._records.get(key)
        if not records or value.quality is Quality.STALE:
            return
        latest = records[-1]
        if latest.outcome is not WriteOutcome.PENDING and latest.read_back is None and not latest.secret:
            records[-1] = replace(latest, read_back=value)

    def records(self, key: str) -> tuple[WriteRecord, ...]:
        """The writes of `key` kept, the newest last."""
        return tuple(self._records.get(key, ()))

    def diagnostics(self) -> dict[str, list[dict[str, object]]]:
        """Every key written to, by its text, with its records as plain data, the newest last."""
        return {str(key): [record.diagnostics() for record in records] for key, records in self._records.items()}

    def _update(self, record: WriteRecord, change: Callable[[WriteRecord], WriteRecord]) -> WriteRecord:
        """The pending `record` as `change` makes it, kept in its place while the log still keeps it."""
        records = self._records.get(record.key, deque[WriteRecord]())
        index = next((i for i, kept in enumerate(records) if kept.number == record.number), None)
        current = record if index is None else records[index]
        if current.outcome is not WriteOutcome.PENDING:
            raise ValueError(f"write {record.number} to '{record.key}' has already ended {current.outcome}")
        updated = change(current)
        if index is not None:
            records[index] = updated
        return updated


def _plain(value: object) -> object:
    """`value` as plain data: a state by its name, a time in ISO 8601."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value

