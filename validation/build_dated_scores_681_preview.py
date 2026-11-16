"""Build two synthetic handoffs for the 6.81 dated-score display."""
from datetime import datetime
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exports import handoffs_html, handoffs_pdf
from importing import import_replacement
from lab_windows import EASTERN, display_clock
from models import automatic_vitals, new_vault, validate_sheet

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)


def block(letter, body):
    return letter * 24 + "\n" + body + "\n" + letter * 24


def build():
    cases = [
        ("P4102", "Pressure Control - Intermittent Mandatory Ventilation", "Endotracheal tube", [
            block("k", "Target Arousal Level:\nSBS Last 24 Hours: Target Arousal Level (SBS): SBS -1 (11/15/26 0630 : Example Recorder, RN)"),
            block("y", "CAPD: 9 (11/14/26 0800 : Example Recorder, RN)\nCAPD: 6 (11/15/26 0800 : Example Recorder, RN)"),
            block("l", "WAT Score:\nWAT-1: 4 (11/16/26 0600 : Example Recorder, RN)\nWAT-1: 2 (11/16/26 0640 : Example Recorder, RN)"),
        ], ["SBS target: -1 (11/15/26)", "CAPD: 6 (11/15/26)", "WAT-1: 2 (11/16/26)"]),
        ("P4104", "", "Nasal cannula", [
            block("k", "Target Arousal Level:\nSBS Last 24 Hours: Target Arousal Level (SBS): SBS 0 (11/15/26 0730 : Example Recorder, RN)"),
            block("y", "CAPD: 4 (11/16/26 0400 : Example Recorder, RN)"),
            block("l", "WAT Score:\nWAT-1: 1 (11/16/26 0900 : Example Recorder, RN)"),
            block("u", "Lines:\nEndotracheal Tube:\n[REMOVED] ETT 5 mm-Secured at (cm): 15 cm"),
        ], ["CAPD: 4 (11/16/26)", "WAT-1: 1 (11/16/26)"]),
    ]
    sheets = []
    with display_clock(NOW):
        for room, mode, delivery, scores, expected in cases:
            ventilation = "Invasive Ventilation:\nMode: " + mode
            if mode:
                ventilation += "\nRespiratory Rate: Resp Rate (Set): 20\nSet PIP: 18 cm H2O\nSet PEEP: PEEP (cm H2O): 5\nFiO2: 30 %"
            support = "Non-invasive Ventilation:\nO2 Delivery Method: " + delivery
            if not mode:
                support += "\nO2 Flow Rate (L/min): 1 L/min"
            source = "\n".join([
                block("a", "Diagnoses:\n1. SYNTHETIC DISPLAY EXAMPLE\n2. Not a patient record"),
                block("c", ventilation), block("d", support), *scores,
            ])
            result = import_replacement(room, source, new_vault()["settings"])
            if result.errors:
                raise ValueError(result.errors)
            sheet = result.sheet
            sheet["fields"]["Goals / Follow-up"] = "Synthetic score formatting example. Source times select the latest entry. Only the score and date appear above."
            validate_sheet(sheet)
            output = automatic_vitals(sheet)["Neurologic"]
            assert all(line in output for line in expected)
            assert "Example Recorder" not in json.dumps(sheet)
            if not mode:
                assert "SBS" not in output
            sheets.append(sheet)
        target = ROOT / "examples"
        (target / "dated_scores_681_preview.pdf").write_bytes(handoffs_pdf(sheets, NOW))
        (target / "dated_scores_681_preview.html").write_text(handoffs_html(sheets, NOW), encoding="utf-8")
        (target / "synthetic_dated_scores_681.json").write_text(json.dumps(sheets, indent=2), encoding="utf-8")
    print("Created two synthetic dated-score handoffs.")


if __name__ == "__main__":
    build()
