"""Passes under every order of calls, newly due work, finished, failed and cancelled passes.

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

STEPS = ("call", "due", "tick", "settle", "finish", "fail", "cancel", "bad_due")
"""call: a poll starts. due: something falls due. tick: one turn of the event loop. settle: the
loop runs until nothing more can happen. finish, fail: the running pass ends, or raises. cancel:
the newest poll still running is cancelled. bad_due: the next check of what is due raises."""


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
    task: asyncio.Task[None] | None = None
    ran: bool = False
    """Whether its own pass ran to the end."""
    started: bool = False
    """Whether its own pass started."""
    result: bool | None = None
    error: BaseException | None = None


@dataclass
class _Scenario:
    passes: Passes = field(default_factory=Passes)
    pending: set[int] = field(default_factory=set[int])
    next_item: int = 0
    inside: int = 0
    calls: list[_Call] = field(default_factory=list[_Call])
    active: list[asyncio.Future[str]] = field(default_factory=list[asyncio.Future[str]])
    broken: list[str] = field(default_factory=list[str])
    _tasks: list[asyncio.Task[None]] = field(default_factory=list[asyncio.Task[None]])
    due_fails: bool = False

    def due(self) -> bool:
        if self.due_fails:
            self.due_fails = False
            raise DueFailed
        return bool(self.pending)

    async def call(self) -> None:
        call = _Call(len(self.calls) + 1, waited=self.inside > 0, due_at_entry=frozenset(self.pending))
        self.calls.append(call)
        self.inside += 1

        async def work() -> None:
            call.started = True
            if self.active:
                self.broken.append(f"call {call.number}: a pass started while another ran")
            if call.waited and not self.pending:
                self.broken.append(f"call {call.number} waited, then made a pass with nothing due")
            snapshot = set(self.pending)
            gate: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self.active.append(gate)
            try:
                if await gate == "fail":
                    raise PassFailed
                self.pending.difference_update(snapshot)
            finally:
                self.active.remove(gate)
            call.ran = True

        try:
            call.result = await self.passes.run(work, due=self.due)
        except BaseException as error:
            call.error = error
            if not isinstance(error, (PassFailed, DueFailed, asyncio.CancelledError)):
                self.broken.append(f"call {call.number} raised {error!r}")
            if isinstance(error, asyncio.CancelledError):
                raise
        else:
            self.check_returned(call)
        finally:
            self.inside -= 1

    def check_returned(self, call: _Call) -> None:
        if call.result is not call.ran:
            self.broken.append(f"call {call.number} returned {call.result}, its pass ran: {call.ran}")
        if not call.waited and not call.ran:
            self.broken.append(f"call {call.number} found no pass running, yet made none")
        if left := call.due_at_entry & self.pending:
            self.broken.append(f"call {call.number} returned with {sorted(left)}, due when it was made, unread")

    async def step(self, step: str) -> None:
        loop = asyncio.get_running_loop()
        match step:
            case "call":
                self._tasks.append(loop.create_task(self.call()))
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
            case "bad_due":
                self.due_fails = True
            case "cancel":
                running = [task for task in self._tasks if not task.done()]
                if running:
                    running[-1].cancel()
            case _:
                raise AssertionError(step)
        if len([gate for gate in self.active if not gate.done()]) > 1:
            self.broken.append("two passes ran at once")
        if self.active and not self.passes.running:
            self.broken.append("a pass ran while running said none did")

    async def finish(self) -> None:
        """Let every pass end, then check that nothing is left hanging."""
        for _ in range(len(self.calls) + 2):
            await _settle()
            for gate in list(self.active):
                if not gate.done():
                    gate.set_result("finish")
        await _settle()
        if hung := [task for task in self._tasks if not task.done()]:
            self.broken.append(f"{len(hung)} call(s) never returned")
        if self.passes.running:
            self.broken.append("the lock is still held after every call returned")
        for task in self._tasks:
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
            broken = await _run(steps)
            if broken:
                found.append(f"{' '.join(steps)}: {'; '.join(broken)}")
                if len(found) >= 10:
                    break
        return found

    found = asyncio.run(all_of_them())
    assert not found, "\n".join(found)


@pytest.mark.parametrize("length", range(1, 6))
def test_every_order_of_up_to_five_steps_keeps_the_rules(length: int) -> None:
    _check(list(itertools.product(STEPS, repeat=length)))


def test_long_random_orders_keep_the_rules() -> None:
    rand = random.Random(20261103)
    _check([[rand.choice(STEPS) for _ in range(rand.randint(6, 40))] for _ in range(3000)])


@pytest.mark.parametrize("callers", [1, 2, 3, 10, 100])
def test_many_polls_during_one_pass_cause_one_pass_after_it(callers: int) -> None:
    _check([["call", "settle", *(["call"] * callers), "due", "settle", "finish", "settle"]])
