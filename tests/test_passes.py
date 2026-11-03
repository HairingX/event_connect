"""One pass at a time over what is due on a device."""
from __future__ import annotations

import asyncio

from event_connect import Passes


def test_a_call_during_a_pass_waits_for_it_and_makes_none_if_nothing_is_still_due() -> None:
    passes = Passes()
    ran: list[str] = []

    async def work() -> None:
        ran.append("pass")
        await asyncio.sleep(0.01)

    async def together() -> list[bool]:
        return list(await asyncio.gather(passes.run(work, due=lambda: False),
                                         passes.run(work, due=lambda: False)))

    assert asyncio.run(together()) == [True, False] and ran == ["pass"]


def test_a_call_during_a_pass_makes_its_own_after_it_when_something_is_still_due() -> None:
    passes = Passes()
    ran: list[str] = []
    seen_running: list[bool] = []

    async def work() -> None:
        seen_running.append(passes.running)
        ran.append("pass")
        await asyncio.sleep(0.01)

    async def together() -> None:
        await asyncio.gather(passes.run(work, due=lambda: True), passes.run(work, due=lambda: True))

    asyncio.run(together())
    assert ran == ["pass", "pass"] and seen_running == [True, True] and not passes.running


def test_polls_made_together_during_a_pass_cause_one_pass_after_it() -> None:
    passes = Passes()
    pending = {"a"}
    reads: list[list[str]] = []

    async def work() -> None:
        snapshot = sorted(pending)
        reads.append(snapshot)
        await asyncio.sleep(0.01)
        pending.difference_update(snapshot)

    async def later() -> None:
        await asyncio.sleep(0.001)
        pending.add("b")
        await passes.run(work, due=lambda: bool(pending))

    async def together() -> None:
        await asyncio.gather(passes.run(work, due=lambda: bool(pending)), later(), later(), later())

    asyncio.run(together())
    assert reads == [["a"], ["b"]]
