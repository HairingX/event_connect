"""Whether a device answers, as its consumers should see it: one lost answer is not an outage."""
from __future__ import annotations

import math

from ._clock import Clock


class Reachability:
    """Whether a device answers: at once when it does, and only once it has stayed silent for
    `offline_after` seconds when it does not.

    It counts as not answering until it first answers.
    """

    def __init__(self, clock: Clock, offline_after: float) -> None:
        if not (math.isfinite(offline_after) and offline_after >= 0):
            raise ValueError(f"offline_after must be a finite number >= 0, got {offline_after}")
        self._clock = clock
        self._offline_after = offline_after
        self._reachable = False
        self._silent_since: float | None = None

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

    def answered(self) -> bool:
        """Note an answer, and return whether the device counts as answering: it does."""
        self._silent_since = None
        self._reachable = True
        return True

    def unanswered(self) -> bool:
        """Note a request the device did not answer, and return whether it still counts as
        answering."""
        if self._silent_since is None:
            self._silent_since = self._clock.monotonic()
        if self._reachable and self.silent_for >= self._offline_after:
            self._reachable = False
        return self._reachable
