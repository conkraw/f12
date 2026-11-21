"""Temporary import progress and anonymous, session-only phase timings."""
from __future__ import annotations

import math
from statistics import median
import time


TIMING_KEY = "handoff_processing_timings"
STAGES = ("Reading SmartPhrase", "Saving handoff", "Preparing PDF")
MAX_SAMPLES = 5


def _samples(state, storage: str) -> list[list[float]]:
    history = state.get(TIMING_KEY, {})
    values = history.get(storage, []) if isinstance(history, dict) else []
    if not isinstance(values, list):
        return []
    return [list(sample) for sample in values[-MAX_SAMPLES:]
            if isinstance(sample, (list, tuple)) and len(sample) == len(STAGES)
            and all(type(value) in (int, float) and math.isfinite(value) and value >= 0
                    for value in sample)]


def _duration(seconds: float) -> str:
    if seconds < 1:
        return "less than 1 second"
    if seconds < 60:
        return "about " + str(math.ceil(seconds)) + " seconds"
    return "about " + str(math.ceil(seconds / 60)) + " minutes"


class ProcessingFeedback:
    """Show completed stages, not a simulated percentage or countdown.

    Streamlit owns the live elapsed timer. Remaining-time estimates are typical
    durations from recent successful imports, updated only at stage boundaries.
    UI failures must not change import or storage behavior. Lightweight callback
    tests may omit these Streamlit facilities entirely.
    """

    def __init__(self, ui, state, *, shared_storage: bool = False, clock=None):
        self.ui = ui
        self.state = state
        self.storage = "shared" if shared_storage else "session"
        self.clock = clock or time.perf_counter
        self.history = _samples(state, self.storage)
        self.durations = []
        self.stage = None
        self.started = None
        self.bar = None
        self.spinner = None

    def __enter__(self):
        spinner = getattr(self.ui, "spinner", None)
        if callable(spinner):
            try:
                self.spinner = spinner("Processing handoff", show_time=True)
                self.spinner.__enter__()
            except Exception:
                self.spinner = None
        self.step(0)
        return self

    def _show(self, value: float, text: str) -> None:
        try:
            if self.bar is not None:
                update = getattr(self.bar, "progress", None)
                if callable(update):
                    update(value, text=text)
            else:
                create = getattr(self.ui, "progress", None)
                if callable(create):
                    self.bar = create(value, text=text)
        except Exception:
            # A missing display must not cancel or repeat a patient-data write.
            pass

    def step(self, index: int) -> None:
        if index != (0 if self.stage is None else self.stage + 1):
            raise ValueError("Processing steps must remain in order.")
        now = self.clock()
        if self.started is not None:
            self.durations.append(max(0.0, now - self.started))
        self.stage = index
        self.started = now
        text = "Step " + str(index + 1) + " of " + str(len(STAGES)) + ": " + STAGES[index]
        if self.history:
            remaining = sum(median(sample[part] for sample in self.history)
                            for part in range(index, len(STAGES)))
            text += (". Typical remaining time: " + _duration(remaining)
                     + " (prior successful imports, updated at each step)")
        self._show(index / len(STAGES), text)

    def finish(self, *, pdf_ready: bool, import_errors: bool = False) -> None:
        if self.stage != len(STAGES) - 1:
            return
        self.durations.append(max(0.0, self.clock() - self.started))
        if import_errors:
            text = "Processing finished. Handoff saved with alerts. Review Alerts before use."
        else:
            text = "Processing finished. Handoff saved."
        text += " PDF ready." if pdf_ready else " PDF preparation will retry when downloaded."
        # Incomplete parsing or PDF preparation must never look fully ready.
        ready = pdf_ready and not import_errors
        self._show(1.0 if ready else self.stage / len(STAGES), text)
        if ready and len(self.durations) == len(STAGES):
            history = {kind: _samples(self.state, kind) for kind in ("session", "shared")}
            history[self.storage] = (history[self.storage] +
                                     [[round(value, 3) for value in self.durations]])[-MAX_SAMPLES:]
            self.state[TIMING_KEY] = history

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            clear = getattr(self.bar, "empty", None)
            if callable(clear):
                clear()
        except Exception:
            pass
        finally:
            if self.spinner is not None:
                try:
                    self.spinner.__exit__(exc_type, exc_value, traceback)
                except Exception:
                    pass
        return False
