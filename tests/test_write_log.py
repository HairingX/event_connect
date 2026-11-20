"""The record of the writes sent to a device: what was sent, how it ended, and what was read after."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import IntEnum

import pytest

from event_connect import DataValue, Key, Quality, WriteLog, WriteOutcome, WriteRecord
from event_connect.testing import FakeClock


class Mode(IntEnum):
    AUTO = 0
    MANUAL = 1


TARGET = Key("target", float)
MODE = Key("mode", Mode)
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _log(per_key: int = 3) -> tuple[WriteLog, FakeClock]:
    clock = FakeClock()
    return WriteLog(clock, per_key=per_key), clock


def test_a_log_keeps_at_least_one_write_per_key() -> None:
    with pytest.raises(ValueError, match="per_key"):
        WriteLog(FakeClock(), per_key=0)


def test_a_write_sent_is_pending_once_with_what_was_asked_and_sent() -> None:
    log, _ = _log()
    record = log.sent(TARGET, 21.5, [215])
    assert record == WriteRecord(key="target", number=1, value=21.5, raw=(215,), sent_at=START, attempts=1,
                                 outcome=WriteOutcome.PENDING, detail="", ended_at=None, read_back=None)
    assert log.records(TARGET) == (record,)


def test_writes_are_numbered_in_the_order_sent_whatever_their_key() -> None:
    log, _ = _log()
    assert [log.sent(TARGET, 1.0, [10]).number, log.sent(MODE, Mode.AUTO, [0]).number,
            log.sent(TARGET, 2.0, [20]).number] == [1, 2, 3]


def test_a_write_ends_with_its_outcome_detail_and_time() -> None:
    log, clock = _log()
    record = log.sent(TARGET, 21.5, [215])
    clock.advance(2)
    ended = log.ended(record, WriteOutcome.REFUSED, detail="busy (0x06)")
    assert (ended.outcome, ended.detail, ended.ended_at) == (WriteOutcome.REFUSED, "busy (0x06)", clock.now())
    assert log.records(TARGET) == (ended,)


def test_a_write_sent_again_counts_its_attempts() -> None:
    log, _ = _log()
    record = log.sent(TARGET, 21.5, [215])
    log.resent(record)
    assert log.resent(record).attempts == 3
    assert log.ended(record, WriteOutcome.TAKEN).attempts == 3


def test_a_write_cannot_end_pending() -> None:
    log, _ = _log()
    record = log.sent(TARGET, 21.5, [215])
    with pytest.raises(ValueError, match="pending"):
        log.ended(record, WriteOutcome.PENDING)


def test_a_write_ends_once_and_is_not_sent_again_after() -> None:
    log, _ = _log()
    record = log.sent(TARGET, 21.5, [215])
    log.ended(record, WriteOutcome.TAKEN)
    with pytest.raises(ValueError, match="already ended taken"):
        log.ended(record, WriteOutcome.ERROR)
    with pytest.raises(ValueError, match="already ended"):
        log.resent(record)


def test_the_oldest_write_of_a_key_gives_way_and_others_keep_theirs() -> None:
    log, _ = _log(per_key=2)
    first = log.sent(TARGET, 1.0, [10])
    log.sent(MODE, Mode.AUTO, [0])
    log.sent(TARGET, 2.0, [20])
    log.sent(TARGET, 3.0, [30])
    assert [record.value for record in log.records(TARGET)] == [2.0, 3.0]
    assert [record.value for record in log.records(MODE)] == [Mode.AUTO]
    assert log.ended(first, WriteOutcome.TAKEN).outcome is WriteOutcome.TAKEN
    assert [record.number for record in log.records(TARGET)] == [3, 4]


def test_a_key_never_written_has_no_records() -> None:
    log, _ = _log()
    assert log.records(TARGET) == ()


def test_the_first_answered_read_after_a_write_ended_is_its_read_back() -> None:
    log, clock = _log()
    record = log.sent(TARGET, 21.5, [215])
    log.ended(record, WriteOutcome.TAKEN)
    clock.advance(1)
    first = DataValue(21.5, Quality.GOOD, clock.now(), raw=(215,))
    log.read(TARGET, first)
    log.read(TARGET, DataValue(22.0, Quality.GOOD, clock.now(), raw=(220,)))
    assert log.records(TARGET)[0].read_back == first


@pytest.mark.parametrize("quality", [Quality.GOOD, Quality.NO_DATA, Quality.OFFLINE, Quality.MISSING])
def test_any_answer_is_a_read_back(quality: Quality) -> None:
    log, clock = _log()
    log.ended(log.sent(TARGET, 21.5, [215]), WriteOutcome.REFUSED)
    answer = DataValue[float](None, quality, clock.now())
    log.read(TARGET, answer)
    assert log.records(TARGET)[0].read_back == answer


def test_a_read_the_device_did_not_answer_is_no_read_back() -> None:
    log, clock = _log()
    log.ended(log.sent(TARGET, 21.5, [215]), WriteOutcome.TAKEN)
    log.read(TARGET, DataValue(20.0, Quality.STALE, clock.now()))
    assert log.records(TARGET)[0].read_back is None


def test_a_read_while_the_write_is_pending_is_no_read_back() -> None:
    log, clock = _log()
    record = log.sent(TARGET, 21.5, [215])
    log.read(TARGET, DataValue(20.0, Quality.GOOD, clock.now()))
    assert log.ended(record, WriteOutcome.TAKEN).read_back is None


def test_a_read_is_the_read_back_of_the_latest_write_only() -> None:
    log, clock = _log()
    log.ended(log.sent(TARGET, 1.0, [10]), WriteOutcome.TAKEN)
    log.ended(log.sent(TARGET, 2.0, [20]), WriteOutcome.TAKEN)
    log.read(TARGET, DataValue(2.0, Quality.GOOD, clock.now()))
    log.read(TARGET, DataValue(3.0, Quality.GOOD, clock.now()))
    assert [record.read_back for record in log.records(TARGET)] == [
        None, DataValue(2.0, Quality.GOOD, clock.now())]


def test_a_read_of_a_key_never_written_is_ignored() -> None:
    log, clock = _log()
    log.read(TARGET, DataValue(2.0, Quality.GOOD, clock.now()))
    assert log.diagnostics() == {}


def test_the_diagnostics_are_plain_data_per_key_the_newest_last() -> None:
    log, clock = _log()
    mode = log.sent(MODE, Mode.MANUAL, [1])
    clock.advance(1)
    log.ended(mode, WriteOutcome.TAKEN)
    clock.advance(1)
    log.read(MODE, DataValue(Mode.MANUAL, Quality.GOOD, clock.now(), raw=(1,)))
    log.sent(TARGET, 21.5, [215])
    assert log.diagnostics() == {
        "mode": [{
            "number": 1, "value": "MANUAL", "raw": [1], "sent_at": "2026-01-01T00:00:00+00:00", "attempts": 1,
            "outcome": "taken", "detail": "", "ended_at": "2026-01-01T00:00:01+00:00",
            "read_back": {"value": "MANUAL", "quality": "GOOD", "raw": [1], "at": "2026-01-01T00:00:02+00:00"},
        }],
        "target": [{
            "number": 2, "value": 21.5, "raw": [215], "sent_at": "2026-01-01T00:00:02+00:00", "attempts": 1,
            "outcome": "pending", "detail": "", "ended_at": None, "read_back": None,
        }],
    }


@pytest.mark.parametrize(("value", "plain"), [
    (date(2026, 3, 4), "2026-03-04"),
    (time(6, 30), "06:30:00"),
    (datetime(2026, 3, 4, 6, 30, tzinfo=timezone.utc), "2026-03-04T06:30:00+00:00"),
    (True, True),
    ("text", "text"),
    (None, None),
])
def test_a_value_in_the_diagnostics_is_plain(value: object, plain: object) -> None:
    log, _ = _log()
    log.sent(Key("any", str), value, [])
    assert log.diagnostics()["any"][0]["value"] == plain


def test_an_outcome_is_stored_by_its_text() -> None:
    assert WriteOutcome("no_answer") is WriteOutcome.NO_ANSWER
