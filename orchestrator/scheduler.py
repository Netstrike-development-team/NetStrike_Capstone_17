"""Monotonic real-time clock adapter for the deterministic scenario controller."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .controller import RunState, ScenarioController


class ScenarioScheduler:
    """Advance a controller from monotonic time without weakening determinism."""

    def __init__(
        self,
        controller: ScenarioController,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.controller = controller
        self.monotonic = monotonic
        self._last_observed: float | None = None
        self._fractional_seconds = 0.0
        self._lock = threading.RLock()

    def start(self) -> None:
        """Start play and anchor the exercise clock to monotonic time."""

        with self._lock:
            self.controller.start()
            self._last_observed = self.monotonic()
            self._fractional_seconds = 0.0

    def tick(self) -> int:
        """Advance by complete elapsed seconds and return controller time."""

        with self._lock:
            if self.controller.state != RunState.RUNNING:
                return self.controller.elapsed_seconds
            now = self.monotonic()
            if self._last_observed is None:
                self._last_observed = now
                return self.controller.elapsed_seconds
            delta = now - self._last_observed
            if delta < 0:
                raise RuntimeError("monotonic clock moved backwards")
            self._last_observed = now
            elapsed = self._fractional_seconds + delta
            complete_seconds = int(elapsed)
            self._fractional_seconds = elapsed - complete_seconds
            if complete_seconds:
                self.controller.advance_to(
                    self.controller.elapsed_seconds + complete_seconds
                )
            return self.controller.elapsed_seconds

    def pause(self) -> None:
        """Capture elapsed time and pause future scheduled delivery."""

        with self._lock:
            self.tick()
            self.controller.pause()
            self._last_observed = None

    def resume(self) -> None:
        """Resume from the current elapsed time without counting paused time."""

        with self._lock:
            self.controller.resume()
            self._last_observed = self.monotonic()

    def advance_to(self, elapsed_seconds: int) -> None:
        """Apply an explicit facilitator time jump and re-anchor real time."""

        with self._lock:
            self.controller.advance_to(elapsed_seconds)
            self._last_observed = self.monotonic()
            self._fractional_seconds = 0.0

    def reset(self) -> None:
        """Clear timing state after the controller has started a new run."""

        with self._lock:
            self._last_observed = None
            self._fractional_seconds = 0.0
