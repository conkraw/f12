"""Patient-free configuration for the optional administrator note utility."""
from __future__ import annotations

import re


def normalize_phrase_name(value: str) -> str:
    """Accept a copied reference, but store only its exact identifier."""
    if not isinstance(value, str):
        raise ValueError("A phrase name must be text.")
    value = value.strip()
    if value.startswith("@") and value.endswith("@"):
        value = value[1:-1]
    elif value.startswith("."):
        value = value[1:]
    value = value.upper()
    if value and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,119}", value):
        raise ValueError("Use only the Epic phrase name, with letters, numbers, or underscores.")
    return value


def normalize_note_settings(value: dict | None) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"phrase_style", "phrase_overrides"}:
        raise ValueError("The note utility settings are invalid.")
    style = value.get("phrase_style", "at")
    if style not in ("at", "dot"):
        raise ValueError("Choose template references or dot phrases for the note.")
    overrides = value.get("phrase_overrides", {})
    if not isinstance(overrides, dict) or len(overrides) > 100:
        raise ValueError("The note phrase names are invalid.")
    clean = {}
    for key, name in overrides.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", key):
            raise ValueError("A note phrase identifier is invalid.")
        normalized = normalize_phrase_name(name)
        if normalized:
            clean[key] = normalized
    return {"phrase_style": style, "phrase_overrides": clean}


def validate_note_settings(value: dict) -> None:
    if value != normalize_note_settings(value):
        raise ValueError("The saved note utility settings are invalid.")
