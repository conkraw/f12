"""Main-thread print preparation feedback and anonymous readiness metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import time


PREPARATION_KEY = "all_print_preparation"


def preparation_signature(sheets: list[dict], target_pages: int, generation: str,
                          *, shared_storage: bool) -> str:
    """Include current displayed content without retaining a second packet.

    The ready marker is a digest, count and elapsed duration only. A changed
    selection, source, save, renderer, page target, or time-filtered display
    needs a fresh preparation. Actual download still repeats all guards.
    """
    from exports import pdf_content_signature
    instant = datetime.now(timezone.utc)
    payload = {"sheets": sheets, "target_pages": target_pages,
               "generation": generation, "shared_storage": shared_storage,
               "rendered": [pdf_content_signature(sheet, instant, target_pages=target_pages)
                            for sheet in sheets]}
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(data).hexdigest()


def elapsed_text(seconds: float) -> str:
    if seconds < 60:
        return format(max(0.0, seconds), ".1f") + " seconds"
    whole = max(0, int(seconds))
    minutes, remainder = divmod(whole, 60)
    return (str(minutes) + (" minute" if minutes == 1 else " minutes") +
            " " + str(remainder) + (" second" if remainder == 1 else " seconds"))


class PrintFeedback:
    """Use Streamlit's live timer plus counts of completed real operations.

    A successful body count is followed by assembly and the existing final
    archive check. The progress bar reaches 100 percent only after that check.
    This is elapsed preparation time, never a guessed countdown or printer ETA.
    """

    def __init__(self, ui, count: int, *, clock=None):
        self.ui = ui
        self.count = count
        self.clock = clock or time.perf_counter
        self.started = None
        self.elapsed = None
        self.spinner = None
        self.bar = None

    def __enter__(self):
        self.started = self.clock()
        spinner = getattr(self.ui, "spinner", None)
        if callable(spinner):
            try:
                self.spinner = spinner("Preparing print packet", show_time=True)
                self.spinner.__enter__()
            except Exception:
                self.spinner = None
        self._show(0.0, "Checking saved handoffs before preparation")
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
            # Feedback must not change save, generation, or download safety.
            pass

    def update(self, completed: int, total: int, stage: str) -> None:
        if stage == "preparing":
            self._show(completed / (total + 2),
                       "Preparing handoffs: " + str(completed) + " of " + str(total) + " ready")
        elif stage == "assembling":
            self._show(total / (total + 2), "Combining " + str(total) + " handoffs into one PDF")
        elif stage == "complete":
            # cached_handoffs_pdf has assembled the bytes, but guard_download
            # must still verify the current shared archive before readiness.
            self._show((total + 1) / (total + 2), "Checking saved handoffs again before download")

    def finish(self) -> float:
        self.elapsed = max(0.0, self.clock() - self.started)
        self._show(1.0, "Print packet prepared in " + elapsed_text(self.elapsed))
        return self.elapsed

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
