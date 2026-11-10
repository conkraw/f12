"""Clinician-entered airway handoff. No diagnosis, rescue plan or normal finding is inferred."""
from __future__ import annotations
from copy import deepcopy
from html import escape
import re

TITLE = "DIFFICULT AIRWAY"
MASK_OPTIONS = ("Unknown / not assessed", "Yes", "Yes, with difficulty", "No")
PASSAGE_OPTIONS = ("Unknown / not assessed", "No", "Yes", "Unable to pass")
TEXT_LIMITS = {"view": 160, "equipment": 240, "tube_details": 160,
               "issue": 400, "plan": 400, "source": 120}
FIELDS = ("enabled", "mask_ventilation", "tube_passage") + tuple(TEXT_LIMITS)


def empty_airway() -> dict:
    return dict(enabled=False, mask_ventilation=MASK_OPTIONS[0],
                tube_passage=PASSAGE_OPTIONS[0], **{key: "" for key in TEXT_LIMITS})


def validate_airway(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != set(FIELDS) or type(data["enabled"]) is not bool:
        raise ValueError("The difficult-airway record has an invalid structure.")
    if data["mask_ventilation"] not in MASK_OPTIONS or data["tube_passage"] not in PASSAGE_OPTIONS:
        raise ValueError("A difficult-airway response is invalid.")
    for key, limit in TEXT_LIMITS.items():
        value = data[key]
        if not isinstance(value, str) or len(value) > limit or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
            raise ValueError("An airway description is invalid or too long.")


def collect_airway(sheet: dict, widgets) -> dict:
    """Capture only this sheet's widgets, including an edit delivered on room change."""
    data = deepcopy(sheet.get("difficult_airway") or empty_airway())
    prefix = "dairway_" + sheet["id"] + "_"
    for field in FIELDS:
        if prefix + field in widgets:
            value = widgets[prefix + field]
            data[field] = value.strip() if isinstance(value, str) else value
    validate_airway(data)
    return data


def airway_summary(sheet: dict, rich: bool = False, esc=escape) -> str:
    data = sheet.get("difficult_airway")
    validate_airway(data)
    if not data or not data["enabled"]:
        return ""
    clean = lambda value: re.sub(r"\s+", " ", value).strip()
    parts = []
    def add(label, value):
        if value:
            parts.append(("<b>" + esc(label) + ":</b> " + esc(clean(value))) if rich
                         else label + ": " + clean(value))
    mask = {"Yes": "Yes", "Yes, with difficulty": "With difficulty", "No": "No"}.get(data["mask_ventilation"])
    passage = {"No": "Not difficult", "Yes": "Difficult", "Unable to pass": "Unable to pass"}.get(data["tube_passage"])
    add("Bag-mask ventilation", mask)
    add("Tube passage", passage)
    for key, label in (("view", "View"), ("equipment", "Equipment"),
                       ("tube_details", "Tube / route"), ("issue", "Issue"),
                       ("plan", "Team plan"), ("source", "Assessed / source")):
        add(label, data[key])
    return " | ".join(parts) or "Details not entered."
