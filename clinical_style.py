"""Presentation-only clinical labels and explicit abnormal flags.

No thresholds, conversions, missing values, or medical interpretation are added.
The original text is escaped before adding markup. The helpers are pure and
shared by HTML, SVG lab trees, and ReportLab PDF output.
"""
from __future__ import annotations
from html import escape
import re

HIGH_COLOR = "#b00020"
LOW_COLOR = "#125bba"
FLAG_VALUE = re.compile(
    r"(?<![\w./])(?:[<>≤≥][ \t]*)?[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
    r"(?:[ \t]+(?:mm[ \t]*Hg|cm[ \t]*H2O|[a-zµμ%][a-z0-9µμ/%^.-]*))?"
    r"(?:[ \t]*(?:\((?:HH|LL|HIGH|LOW|H|L)\)|\*))+", re.I)
HIGH = re.compile(r"\((?:H|HH|HIGH)\)", re.I)
LOW = re.compile(r"\((?:L|LL|LOW)\)", re.I)
# Restrict emphasis to generated clinical labels. Arbitrary notes are not
# interpreted as a vital sign, and a colon in a collection time is untouched.
LABEL = re.compile(
    r"^(?:Room|Age|Sex|Admission|Diagnoses|Weight|Z-score|Dosing weight|Height|BSA|BMI|MRSA Screen|EVD|"
    r"SBS(?: target)?|RASS|Target Arousal Level(?: \(SBS\))?|"
    r"WAT(?:-1)?(?: total score)?(?: \(0-12\))?|CAPD|"
    r"ICP(?: Mean)?(?: \(mmHg\))?|CPP|Resp(?:iratory Rate)?|RR|"
    r"FiO2(?:[ \t]*\(%\))?|SpO2|Pulse Ox(?:imetry)?|"
    r"ETCO2(?:[ \t]*\(mmHg\))?|VP|Heart Rate|HR|Pulse(?: rate)?|BP|"
    r"Blood pressure|Systolic|Diastolic|SBP|DBP|MAP(?: \(mmHg\))?|"
    r"Mean arterial pressure|ABP|Arterial(?: line)?(?: BP| pressure| blood pressure)?(?: \(mmHg\))?|"
    r"Central venous pressure(?: \(mean\))?|PAP|Pulmonary artery pressure|"
    r"Respirations|SaO2|Oxygen saturation|O2 saturation|T min|"
    r"CVP(?:[ \t]*\(mean\))?|Temp(?:erature)?|"
    r"In|Out|Net|Intake|Output|Intake/Output|"
    r"MCV|ALC|ANC|Ca|Calcium|Phos|Phosphorus|Mg|Magnesium|"
    r"CRP|Procalcitonin|PROCAL|Theophylline|Vancomycin trough|"
    r"Anti-Xa(?: \(HEPLMW\))?|NT-proBNP|Lactate|Methemoglobin|SvO2|"
    r"Inflammatory markers(?:[ \t]+\[[^]\n]+\])?)$", re.I)


def value_runs(text: str) -> list[tuple[str, str]]:
    """Unmodified text runs paired with a color or empty default color.

    An explicit low flag wins over a nonspecific asterisk for the value's
    color. The asterisk itself is still red. Conflicting explicit directions
    remain visible and use red, without changing the stored result.
    """
    out = []
    cursor = 0
    for m in FLAG_VALUE.finditer(text):
        if m.start() > cursor:
            out.append((text[cursor:m.start()], ""))
        value = m.group()
        color = LOW_COLOR if LOW.search(value) and not HIGH.search(value) else HIGH_COLOR
        for part in re.split(r"(\*+)", value):
            if part:
                out.append((part, HIGH_COLOR if part.startswith("*") else color))
        cursor = m.end()
    if cursor < len(text):
        out.append((text[cursor:], ""))
    # Keep adjacent runs of the same color together. Besides fewer drawing
    # operations, this keeps asterisk-flagged values contiguous in PDF text.
    merged = []
    for value, color in out:
        if merged and merged[-1][1] == color:
            merged[-1] = (merged[-1][0] + value, color)
        else:
            merged.append((value, color))
    return merged or [(text, "")]


def value_markup(text: str, esc=escape) -> str:
    return "".join(('<font color="' + color + '">' + esc(value) + '</font>')
                   if color else esc(value) for value, color in value_runs(text))


def clinical_runs(text: str) -> list[tuple[str, bool, str]]:
    """Plain text segments with bold/color metadata, for vector drawing."""
    label, colon, rest = text.partition(":")
    if colon and LABEL.fullmatch(label.strip()):
        if label.strip().lower().startswith("inflammatory markers") and "[" in label:
            head, date = label.split("[", 1)
            return [(head.rstrip(), True, ""), (" [" + date, False, ""), (colon, True, "")] + [(v, False, c) for v, c in value_runs(rest)]
        return [(label + colon, True, "")] + [(v, False, c) for v, c in value_runs(rest)]
    return [(v, False, c) for v, c in value_runs(text)]


def clinical_markup(text: str, esc=escape) -> str:
    lines = []
    for line in text.split("\n"):
        lines.append("".join(("<b>" + esc(value) + "</b>") if bold else
                     (('<font color="' + color + '">' + esc(value) + '</font>')
                      if color else esc(value)) for value, bold, color in clinical_runs(line)))
    return "\n".join(lines)
