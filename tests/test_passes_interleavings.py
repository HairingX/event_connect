"""Passes under every order of polls, newly due work, and passes that finish, fail or are cancelled.

Each scenario is a sequence of steps run on one event loop without real time: the test decides
when a pass ends, and how. After every step the rules a client relies on are checked.
"""
from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from event_connect import Passes

STEPS = ("call", "call_instant", "due", "tick", "settle", "finish", "fail", "cancel", "cancel_oldest",
         "bad_due")
"""call: a poll starts, whose pass waits until the test ends it. call_instant: a poll starts, whose
pass never waits. due: something falls due. tick: one turn of the event loop. settle: the loop runs
until nothing more can happen. finish, fail: the running pass ends, or raises. cancel,
cancel_oldest: the newest, or the oldest, poll still running is cancelled. bad_due: the next
check of what is due raises."""


class PassFailed(Exception):
    """What a pass the test makes fail raises."""


class DueFailed(Exception):
    """What a check of what is due raises, when the test makes it fail."""


@dataclass
class _Call:
    number: int
    waited: bool
    """Whether another call was inside `run` when this one entered it."""
    due_at_entry: frozenset[int]
    task: asyncio.Task[None] | None
    ran: bool = False
    """Whether its own pass ran to the end."""
    result: bool | None = None
    due_said: list[bool | DueFailed] = field(default_factory=list[bool | DueFailed])
    cancel_asked: bool = False
    failed_own: bool = False


@dataclass
class _Scenario:
    passes: Passes = field(default_factory=Passes)
    pending: set[int] = field(default_factory=set[int])
    next_item: int = 0
    inside: int = 0
    calls: list[_Call] = field(default_factory=list[_Call])
    active: list[asyncio.Future[str]] = field(default_factory=list[asyncio.Future[str]])
    """The gates of the passes running now; more than one is a broken rule."""
    turns: list[int] = field(default_factory=list[int])
    """The calls in the order they took their turn: started their pass, or checked what is due."""
    broken: list[str] = field(default_factory=list[str])
    tasks: list[asyncio.Task[None]] = field(default_factory=list[asyncio.Task[None]])
    due_fails: bool = False

    def due(self, call: _Call) -> bool:
        self.turns.append(call.number)
        if self.active:
            self.broken.append(f"call {call.number} checked what is due while a pass ran")
        if self.due_fails:
            self.due_fails = False
            failure = DueFailed()
            call.due_said.append(failure)
            raise failure
        call.due_said.append(bool(self.pending))
        return bool(self.pending)

    def start_pass(self, call: _Call) -> set[int]:
        if not call.waited:
            self.turns.append(call.number)
        if self.active:
            self.broken.append(f"call {call.number}: a pass started while another ran")
        if call.waited and not self.pending:
            self.broken.append(f"call {call.number} waited, then made a pass with nothing due")
        return set(self.pending)

    async def call(self, instant: bool) -> None:
        call = _Call(len(self.calls) + 1, waited=self.inside > 0, due_at_entry=frozenset(self.pending),
                     task=asyncio.current_task())
        self.calls.append(call)
        self.inside += 1

        async def waiting_work() -> None:
            snapshot = self.start_pass(call)
            gate: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self.active.append(gate)
            try:
                if await gate == "fail":
                    call.failed_own = True
                    raise PassFailed
                self.pending.difference_update(snapshot)
            finally:
                self.active.remove(gate)
            call.ran = True

        async def instant_work() -> None:
            self.pending.difference_update(self.start_pass(call))
            call.ran = True

        try:
            call.result = await self.passes.run(instant_work if instant else waiting_work,
                                                due=lambda: self.due(call))
        except BaseException as error:
            self.check_raised(call, error)
            self.check_due_asked(call)
            if isinstance(error, asyncio.CancelledError):
                raise
        else:
            self.check_returned(call)
            self.check_due_asked(call)
        finally:
            self.inside -= 1

    def check_raised(self, call: _Call, error: BaseException) -> None:
        match error:
            case PassFailed() if not call.failed_own:
                self.broken.append(f"call {call.number} raised the failure of a pass not its own")
            case DueFailed() if not (call.due_said and isinstance(call.due_said[-1], DueFailed)):
                self.broken.append(f"call {call.number} raised the failure of a check not its own")
            case asyncio.CancelledError() if not call.cancel_asked:
                self.broken.append(f"call {call.number} was cancelled without being asked")
            case PassFailed() | DueFailed() | asyncio.CancelledError():
                pass
            case _:
                self.broken.append(f"call {call.number} raised {error!r}")

    def check_returned(self, call: _Call) -> None:
        if call.result is not call.ran:
            self.broken.append(f"call {call.number} returned {call.result}, its pass ran: {call.ran}")
        if not call.waited and not call.ran:
            self.broken.append(f"call {call.number} found no other call inside, yet made no pass")
        if call.cancel_asked and not call.ran:
            self.broken.append(f"call {call.number} was cancelled, yet returned {call.result}")
        if left := call.due_at_entry & self.pending:
            self.broken.append(f"call {call.number} returned with {sorted(left)}, due when it was made, unread")

    def check_due_asked(self, call: _Call) -> None:
        if not call.waited and call.due_said:
            self.broken.append(f"call {call.number} found no other call inside, yet checked what is due")
        if len(call.due_said) > 1:
            self.broken.append(f"call {call.number} checked what is due {len(call.due_said)} times")
        if call.result is not None and call.waited:
            if not call.due_said:
                self.broken.append(f"call {call.number} waited and returned without checking what is due")
            elif call.result is not call.due_said[0]:
                self.broken.append(f"call {call.number}: what is due said {call.due_said[0]}, "
                                   f"it returned {call.result}")

    def check_step(self) -> None:
        if len([gate for gate in self.active if not gate.done()]) > 1:
            self.broken.append("two passes ran at once")
        # Checking what is due cannot span a step, so between steps a held turn is a pass.
        if bool(self.active) is not self.passes.running:
            self.broken.append(f"running said {self.passes.running} while {len(self.active)} pass(es) ran")
        if self.turns != sorted(self.turns):
            self.broken.append(f"calls took their turn out of order: {self.turns}")

    async def step(self, step: str) -> None:
        loop = asyncio.get_running_loop()
        match step:
            case "call" | "call_instant":
                self.tasks.append(loop.create_task(self.call(instant=step == "call_instant")))
            case "due":
                self.pending.add(self.next_item)
                self.next_item += 1
            case "tick":
                await asyncio.sleep(0)
            case "settle":
                await _settle()
            case "finish" | "fail":
                if self.active and not self.active[0].done():
                    self.active[0].set_result(step)
            case "cancel" | "cancel_oldest":
                live = [task for task in self.tasks if not task.done()]
                if live:
                    target = live[-1] if step == "cancel" else live[0]
                    for call in self.calls:
                        if call.task is target:
                            call.cancel_asked = True
                    target.cancel()
            case "bad_due":
                self.due_fails = True
            case _:
                raise AssertionError(step)
        self.check_step()

    async def finish(self) -> None:
        """Let every pass end, checking the rules on the way, then that nothing is left hanging."""
        for _ in range(len(self.calls) + 2):
            await _settle()
            self.check_step()
            for gate in list(self.active):
                if not gate.done():
                    gate.set_result("finish")
        await _settle()
        self.check_step()
        if hung := [task for task in self.tasks if not task.done()]:
            self.broken.append(f"{len(hung)} call(s) never returned")
            for task in hung:
                task.cancel()
            await _settle()
        if self.passes.running:
            self.broken.append("a call still holds the turn after every call returned")
        for task in self.tasks:
            if task.done() and not task.cancelled():
                task.exception()


async def _settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


async def _run(steps: Sequence[str]) -> list[str]:
    scenario = _Scenario()
    for step in steps:
        await scenario.step(step)
    await scenario.finish()
    return scenario.broken


def _check(scenarios: Sequence[Sequence[str]]) -> None:
    async def all_of_them() -> list[str]:
        found: list[str] = []
        for steps in scenarios:
            if broken := await _run(steps):
                found.append(f"{' '.join(steps)}: {'; '.join(broken)}")
                if len(found) >= 10:
                    break
        return found

    found = asyncio.run(all_of_them())
    assert not found, "\n".join(found)


@pytest.mark.parametrize("length", range(1, 6))
def test_every_order_of_up_to_five_steps_keeps_the_rules(length: int) -> None:
    _check(list(itertools.product(STEPS, repeat=length)))


@pytest.mark.parametrize("seed", range(5))
def test_long_random_orders_keep_the_rules(seed: int) -> None:
    rand = random.Random(20261103 + seed)
    _check([[rand.choice(STEPS) for _ in range(rand.randint(6, 40))] for _ in range(2000)])


@pytest.mark.parametrize("callers", [1, 2, 3, 10, 100])
def test_many_polls_during_one_pass_cause_one_pass_after_it(callers: int) -> None:
    _check([["call", "settle", *(["call"] * callers), "due", "settle", "finish", "settle"]])


def test_a_waiter_cancelled_as_the_turn_passes_to_it_hands_it_to_the_next() -> None:
    _check([["call", "call", "call", "due", "settle", "finish", "tick", "cancel_oldest", "settle"]])
