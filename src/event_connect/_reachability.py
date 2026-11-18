"""Whether a device answers, as its consumers should see it: one lost answer is not an outage."""
from __future__ import annotations

import logging
import math

from ._clock import Clock
from ._scheduler import Scheduler

_LOGGER = logging.getLogger(__name__)


class Reachability:
    """Whether a device answers: at once when it does, and only once it has stayed silent for
    `offline_after_intervals` of its `fastest_interval` when it does not, so that it misses that
    many reads of its fastest poll rate before it no longer counts as answering.

    With no `fastest_interval`, as when nothing is read on a timer, the first request it leaves
    unanswered ends its counting as answering. It counts as not answering until it first answers.
    Once it has answered, its stopping and its answering again are each logged once, at INFO,
    under `name`.
    """

    def __init__(self, clock: Clock, *, offline_after_intervals: int, fastest_interval: float | None,
                 name: str = "The device") -> None:
        """Watch a device by `clock`.

        Raises:
            ValueError: `offline_after_intervals` is below 1, or `fastest_interval` is not a finite
                number above 0.
        """
        if offline_after_intervals < 1:
            raise ValueError(f"offline_after_intervals must be at least 1, got {offline_after_intervals}")
        if fastest_interval is not None and not (math.isfinite(fastest_interval) and fastest_interval > 0):
            raise ValueError(f"fastest_interval must be a finite number above 0, got {fastest_interval}")
        self._clock = clock
        self._silence_allowed = 0.0 if fastest_interval is None else offline_after_intervals * fastest_interval
        self._reachable = False
        self._lost = False
        self._silent_since: float | None = None
        self.name = name
        """What the log calls the device."""

    @property
    def reachable(self) -> bool:
        """Whether the device counts as answering."""
        return self._reachable

    @property
    def silent(self) -> bool:
        """Whether the device left the latest request unanswered."""
        return self._silent_since is not None

    @property
    def silent_for(self) -> float:
        """Seconds since the first request it has not answered since it last answered; 0 while it
        answers."""
        if self._silent_since is None:
            return 0.0
        return self._clock.monotonic() - self._silent_since

    def answered(self, scheduler: Scheduler | None = None) -> None:
        """Note an answer: the device counts as answering.

        Args:
            scheduler: made to read at once, if the device was silent, what failed meanwhile;
                if it had counted as not answering, everything it reads.
        """
        silent_for = self.silent_for
        if scheduler is not None and self.silent:
            if self._lost:
                scheduler.reset()
            else:
                scheduler.refresh([key for key in scheduler.keys() if scheduler.consecutive_failures(key)],
                                  force=True)
        if self._lost:
            _LOGGER.info("%s answers again, after %.0f s", self.name, silent_for)
        self._silent_since = None
        self._reachable = True
        self._lost = False

    def unanswered(self) -> None:
        """Note a request the device did not answer; once it has been silent long enough, it no
        longer counts as answering."""
        if self._silent_since is None:
            self._silent_since = self._clock.monotonic()
        if self._reachable and self.silent_for >= self._silence_allowed:
            self._reachable = False
            self._lost = True
            _LOGGER.info("%s stopped answering %.0f s ago", self.name, self.silent_for)
