"""Build a synthetic two-room preview of the 6.80 medication display."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from categories import apply_category_rules
from exports import handoff_html, handoffs_pdf
from medications import parse_medications, upsert_rule
from models import new_sheet, new_vault, validate_sheet


def build():
    settings = new_vault()["settings"]
    settings["medication_mappings"] = upsert_rule(
        [], "sodium chloride enteral", "FEN / GI")
    cases = [
        ("P4102", "10 kg", "12 kg", [
            ("fentanyl injection 15 mcg", "15 mcg", "Intravenous", "q1h PRN"),
            ("midazolam injection 0.5 mg", "0.5 mg", "Intravenous", "q2h PRN"),
            ("sodium chloride 3 % nebulizer solution 3 mL", "3 mL", "Nebulization", "q12h"),
            ("sodium chloride enteral solution 6 mEq", "6 mEq", "Per G Tube", "q12h"),
            ("furosemide injection 12 mg", "12 mg", "Intravenous", "q6h"),
            ("chlorothiazide injection 95 mg", "10 mg/kg (Dosing Weight)", "Intravenous", "q12h"),
        ]),
        ("P4104", "", "20 kg", [
            ("fentanyl injection 20 mcg", "20 mcg", "Intravenous", "q2h PRN"),
            ("morphine injection 1 mg", "1 mg", "Intravenous", "q4h PRN"),
            ("sodium chloride 3 % nebulizer solution 4 mL", "4 mL", "Nebulization", "q8h"),
            ("furosemide injection 10 mg", "10 mg", "Intravenous", "q12h"),
            ("chlorothiazide injection 100 mg", "100 mg", "Intravenous", "q12h"),
        ]),
    ]
    sheets = []
    for room, dcw, weight, orders in cases:
        sheet = new_sheet(room)
        sheet["fields"]["Diagnoses"] = "SYNTHETIC DISPLAY EXAMPLE\nNot a patient record"
        sheet["fields"]["Goals / Follow-up"] = "Medication formatting demonstration. Amounts are example data."
        sheet["nutrition"] = {"weight": weight, "z_score": "", "include": True}
        sheet["dosing_weight"] = dcw
        parsed = parse_medications(
            "Medication\tDose\tRoute\tFrequency\n" + "\n".join("\t".join(order) for order in orders),
            settings["medication_mappings"],
        )
        if parsed.error:
            raise ValueError(parsed.error)
        sheet["medications"] = apply_category_rules(parsed.rows, settings)
        validate_sheet(sheet)
        sheets.append(sheet)
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    out = ROOT / "examples"
    (out / "medication_doses_680_preview.pdf").write_bytes(handoffs_pdf(sheets, now))
    (out / "medication_doses_680_preview.html").write_text(handoff_html(sheets[0], now), encoding="utf-8")
    (out / "synthetic_medication_doses_680.json").write_text(json.dumps(sheets, indent=2), encoding="utf-8")
    print("Created synthetic medication preview for two rooms.")


if __name__ == "__main__":
    build()
