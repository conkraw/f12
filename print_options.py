"""Per-session print preferences, independent of the encrypted clinical archive."""
from __future__ import annotations
import math

MIN_FONT_SIZE = 6.5
MAX_FONT_SIZE = 14.0
DEFAULT_FONT_SIZE = 7.2
PREFERENCES_KEY = "handoff_print_preferences"


def validated_font_size(value: float | None) -> float | None:
    """None preserves the prior automatic layout for existing API callers."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Font size must be a number from 6.5 to 14 points.")
    number = float(value)
    if not math.isfinite(number) or not MIN_FONT_SIZE <= number <= MAX_FONT_SIZE:
        raise ValueError("Font size must be a number from 6.5 to 14 points.")
    return round(number, 2)


def font_candidates(font_size: float, auto_fit: bool) -> tuple[float, ...]:
    """Start at the requested size, reducing only with explicit permission."""
    size = validated_font_size(font_size)
    if size is None or type(auto_fit) is not bool:
        raise ValueError("Choose a numeric font size and an automatic-fitting option.")
    sizes = [size]
    if auto_fit:
        while sizes[-1] - 0.25 > MIN_FONT_SIZE:
            sizes.append(round(sizes[-1] - 0.25, 2))
        if sizes[-1] > MIN_FONT_SIZE:
            sizes.append(MIN_FONT_SIZE)
    return tuple(sizes)


def preferences(state) -> dict:
    """Only non-clinical presentation settings are kept in session memory."""
    defaults = dict(font_size=DEFAULT_FONT_SIZE, auto_fit=False, target_pages=1)
    saved = state.get(PREFERENCES_KEY)
    if isinstance(saved, dict):
        try:
            size = validated_font_size(saved.get("font_size"))
            if size is not None:
                defaults["font_size"] = size
        except ValueError:
            pass
        if type(saved.get("auto_fit")) is bool:
            defaults["auto_fit"] = saved["auto_fit"]
        if type(saved.get("target_pages")) is int and saved["target_pages"] in (1, 2):
            defaults["target_pages"] = saved["target_pages"]
    return defaults


def capture_preferences(state, prefix: str) -> None:
    current = preferences(state)
    for field in ("font_size", "auto_fit", "target_pages"):
        key = prefix + "_" + field
        if key in state:
            current[field] = state[key]
    state[PREFERENCES_KEY] = current
    # Validate before another screen reuses the values. This does not touch
    # room drafts, archive settings, saved timestamps or download snapshots.
    state[PREFERENCES_KEY] = preferences(state)
