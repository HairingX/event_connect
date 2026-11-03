"""One pass at a time over what is due on a device."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

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


def test_a_call_with_no_other_inside_makes_a_pass_without_checking_what_is_due() -> None:
    passes = Passes()
    ran: list[str] = []

    async def work() -> None:
        ran.append("pass")

    def due() -> bool:
        raise AssertionError("checked")

    assert asyncio.run(passes.run(work, due=due)) is True and ran == ["pass"]


def test_a_call_made_as_a_pass_ends_waits_behind_the_calls_already_waiting() -> None:
    passes = Passes()
    order: list[str] = []

    def work(name: str) -> Callable[[], Awaitable[None]]:
        async def one_pass() -> None:
            order.append(name)
            await asyncio.sleep(0.01)
        return one_pass

    async def first_twice() -> None:
        await passes.run(work("a1"), due=lambda: True)
        await passes.run(work("a2"), due=lambda: True)

    async def later(name: str) -> None:
        await asyncio.sleep(0)
        await passes.run(work(name), due=lambda: True)

    async def together() -> None:
        await asyncio.gather(first_twice(), later("b"), later("c"))

    asyncio.run(together())
    assert order == ["a1", "b", "c", "a2"]


def test_a_call_made_after_a_pass_ends_but_before_the_next_waiter_wakes_counts_as_waiting() -> None:
    passes = Passes()
    ran: list[str] = []

    async def scenario() -> bool:
        gate: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        async def gated() -> None:
            ran.append("first")
            await gate

        async def quick() -> None:
            ran.append("second")

        first = asyncio.create_task(passes.run(gated, due=lambda: True))
        await asyncio.sleep(0)
        second = asyncio.create_task(passes.run(quick, due=lambda: True))
        await asyncio.sleep(0)
        gate.set_result(None)
        await asyncio.sleep(0)
        assert first.done() and not second.done()
        third = await passes.run(quick, due=lambda: False)
        await second
        return third

    assert asyncio.run(scenario()) is False and ran == ["first", "second"]


def test_running_is_false_once_a_pass_has_returned_while_another_call_waits() -> None:
    passes = Passes()
    seen: list[bool] = []

    async def work() -> None:
        await asyncio.sleep(0)

    async def first() -> None:
        await passes.run(work, due=lambda: True)
        seen.append(passes.running)

    async def together() -> None:
        await asyncio.gather(first(), passes.run(work, due=lambda: False))

    asyncio.run(together())
    assert seen == [False]


def test_a_call_whose_pass_has_finished_is_done_one_turn_later() -> None:
    passes = Passes()

    async def scenario() -> tuple[bool, bool]:
        gate: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        async def work() -> None:
            await gate

        task = asyncio.create_task(passes.run(work, due=lambda: True))
        await asyncio.sleep(0)
        gate.set_result(None)
        await asyncio.sleep(0)
        running = passes.running
        task.cancel()
        return running, await task

    assert asyncio.run(scenario()) == (False, True)


def test_a_pass_that_polls_again_on_the_same_passes_is_refused_rather_than_waiting_for_itself() -> None:
    passes = Passes()

    async def inner() -> None:
        pass

    async def work() -> None:
        await passes.run(inner, due=lambda: True)

    async def scenario() -> None:
        await asyncio.wait_for(passes.run(work, due=lambda: True), timeout=1)

    with pytest.raises(RuntimeError, match="wait for itself"):
        asyncio.run(scenario())
    assert not passes.running


def test_a_task_a_pass_starts_may_poll_and_waits_its_turn() -> None:
    passes = Passes()
    order: list[str] = []

    async def inner() -> None:
        order.append("inner")

    async def work() -> None:
        order.append("outer")
        asyncio.get_running_loop().create_task(passes.run(inner, due=lambda: True))
        await asyncio.sleep(0)

    async def scenario() -> None:
        await passes.run(work, due=lambda: True)
        await asyncio.sleep(0.01)

    asyncio.run(scenario())
    assert order == ["outer", "inner"]


@pytest.mark.parametrize("raised", [ValueError("in the pass"), KeyboardInterrupt(), SystemExit(1)])
def test_whatever_a_pass_raises_reaches_its_own_call_and_frees_the_turn(raised: BaseException) -> None:
    passes = Passes()
    after: list[bool] = []

    async def failing() -> None:
        raise raised

    async def fine() -> None:
        after.append(True)

    async def scenario() -> None:
        with pytest.raises(type(raised)):
            await passes.run(failing, due=lambda: True)
        assert not passes.running
        assert await passes.run(fine, due=lambda: True) is True

    asyncio.run(scenario())
    assert after == [True]


def test_two_passes_objects_do_not_wait_for_each_other() -> None:
    first, second = Passes(), Passes()
    order: list[str] = []

    async def slow() -> None:
        order.append("slow starts")
        await asyncio.sleep(0.02)
        order.append("slow ends")

    async def quick() -> None:
        order.append("quick")

    async def scenario() -> None:
        await asyncio.gather(first.run(slow, due=lambda: True), second.run(quick, due=lambda: True))

    asyncio.run(scenario())
    assert order == ["slow starts", "quick", "slow ends"]


def test_ten_thousand_polls_during_one_pass_cause_one_pass_after_it() -> None:
    passes = Passes()
    pending = {"first"}
    reads: list[list[str]] = []

    async def work() -> None:
        snapshot = sorted(pending)
        reads.append(snapshot)
        await asyncio.sleep(0)
        pending.difference_update(snapshot)

    async def later() -> None:
        pending.add("later")
        await passes.run(work, due=lambda: bool(pending))

    async def scenario() -> None:
        first = asyncio.create_task(passes.run(work, due=lambda: bool(pending)))
        await asyncio.sleep(0)
        await asyncio.gather(*(later() for _ in range(10_000)))
        await first

    asyncio.run(scenario())
    assert reads == [["first"], ["later"]] and not passes.running
