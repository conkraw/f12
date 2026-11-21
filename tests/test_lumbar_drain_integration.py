"""Synthetic lumbar drain import, placement, editing, and saved-output checks."""
from copy import deepcopy
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

from batching import available_handoffs
from devices import devices_text, evd_text, lumbar_drain_text
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_replacement, import_sections
from medications import upsert_rule
from models import automatic_vitals, fields_with_medications, new_vault, save_sheet_in, validate_sheet
from security import generate_key, open_vault, seal_vault
from style_assert_helpers import without_style_tags
from test_callbacks import app, open_room


LUMBAR = "Lumbar Drain-Drain Status: Clamped"
EVD = "Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Open to drain"
ICP = "Intracranial Pressure/Ventriculostomy Intraparenchymal ICP monitor-Status: Monitoring"
MEDICINE = "synthetic neuro medicine"


def block(letter, body):
    return letter * 12 + "\n" + body + "\n" + letter * 12


def settings():
    value = new_vault()["settings"]
    value["medication_mappings"] = upsert_rule([], MEDICINE, "Neurologic")
    return value


def imported(source):
    result = import_replacement("P4102", source, settings())
    assert not result.errors, result.errors
    assert result.sheet is not None
    return result.sheet


def lumbar_source(wat="WAT-1 total score (0-12): 2"):
    return "\n".join([
        block("a", "Diagnoses:\n1. Synthetic integration example"),
        block("b", "Medications:\n• " + MEDICINE + "\t2 mg\tOral\tDaily"),
        block("y", "CAPD: 4"),
        block("l", "WAT Score:\n" + wat),
        block("m", "ICP Trends:\nICP Mean (mmHg): 7 mmHg\nCPP: 61 mmHg"),
        block("u", "Peripheral IV Right Hand-Site Assessment: Clean"),
        block("v", "Intracranial Pressure Monitor:\n" + "\n".join([LUMBAR, EVD, ICP])),
    ])


def pdf_text(sheet):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages)


@pytest.mark.parametrize("render", [handoff_text,
                                    lambda sheet: without_style_tags(handoff_html(sheet)),
                                    pdf_text], ids=["text", "html", "pdf"])
def test_full_import_places_six_hyphens_and_lumbar_status_after_wat_in_every_export(render):
    sheet = imported(lumbar_source())
    before = deepcopy(sheet)
    neuro = fields_with_medications(sheet)["Neurologic"]
    assert "WAT-1 total score (0-12): 2\n------\nLumbar Drain: Clamped\nICP" in neuro

    text = render(sheet)

    assert text.count("Lumbar Drain: Clamped") == 1
    neuro_output = text[text.index("CAPD: 4"):text.index(MEDICINE)]
    assert len(re.findall(r"(?m)^------$", neuro_output)) == 1
    assert "------\nLumbar Drain: Clamped" in neuro_output
    assert text.index("CAPD: 4") < text.index("WAT-1") < text.index("------")
    assert text.index("------") < text.index("Lumbar Drain: Clamped") < text.index("ICP Mean")
    assert text.index("ICP Mean") < text.index("CPP:") < text.index("EVD: Open to drain") < text.index(MEDICINE)
    assert "Lumbar" not in devices_text(sheet)
    assert "Intraparenchymal ICP monitor" in devices_text(sheet)
    assert sheet == before


@pytest.mark.parametrize("wat", [None, "", "excluded"], ids=["absent", "blank", "excluded"])
def test_no_displayed_wat_uses_capd_position_without_inventing_a_score(wat):
    source = block("v", "Intracranial Pressure Monitor:\n" + LUMBAR)
    source += "\n" + block("m", "ICP Trends:\nICP Mean (mmHg): 7 mmHg\nCPP: 61 mmHg")
    if wat is not None:
        body = "WAT Score:\n" + ("WAT-1 total score (0-12): 2" if wat == "excluded" else "")
        source += "\n" + block("l", body)
    sheet = imported(source)
    if wat == "excluded":
        sheet["neuro_vitals"]["l"][0]["include"] = False

    neuro = automatic_vitals(sheet)["Neurologic"]

    assert neuro.startswith("CAPD: None\n------\nLumbar Drain: Clamped\nICP Mean")
    assert "WAT" not in neuro
    assert len(re.findall(r"(?m)^------$", neuro)) == 1


def test_lumbar_follows_last_reported_wat_line():
    sheet = imported(lumbar_source("WAT-1 total score (0-12): 2\nWAT Score: 3"))

    neuro = automatic_vitals(sheet)["Neurologic"]

    assert "WAT Score: 3\n------\nLumbar Drain: Clamped" in neuro
    assert neuro.rindex("WAT") < neuro.index("------") < neuro.index("ICP Mean")
    assert neuro.count("Lumbar Drain:") == 1


@pytest.mark.parametrize("legacy", [False, True], ids=["recognized-drain", "saved-other"])
def test_saved_lumbar_status_survives_encrypted_reload_without_schema_change(legacy):
    sheet = imported(block("v", "Intracranial Pressure Monitor:\n" + LUMBAR))
    row = sheet["neuro_devices"]["rows"][0]
    assert row["kind"] == "Drain"
    if legacy:
        row["kind"] = "Other"
    validate_sheet(sheet)
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()

    blob = seal_vault(vault, key)
    restored = open_vault(blob, key)

    assert b"Lumbar" not in blob and b"Clamped" not in blob
    assert restored == vault
    saved = restored["rooms"]["P4102"]
    assert lumbar_drain_text(saved) == "Lumbar Drain: Clamped"
    assert "Lumbar" not in devices_text(saved)
    assert automatic_vitals(saved)["Neurologic"] == "CAPD: None\n------\nLumbar Drain: Clamped"
    assert "Lumbar Drain: Clamped" in pdf_text(saved)


def test_device_status_and_include_edits_update_lumbar_display_and_saved_record(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = block("v", "Intracranial Pressure Monitor:\n" + LUMBAR)
    app.create_handoff()
    sheet = ss["drafts"]["P4102"]
    row = sheet["neuro_devices"]["rows"][0]
    status_key = "device_" + row["id"] + "_status"
    include_key = "device_" + row["id"] + "_include"

    ss[status_key] = "Open to drain"
    app.device_row_change("P4102", "neuro_devices", row["id"], "status", status_key)
    assert lumbar_drain_text(sheet) == "Lumbar Drain: Open to drain"
    ss[status_key] = "Clamped after review"
    app.device_row_change("P4104", "neuro_devices", row["id"], "status", status_key)
    assert lumbar_drain_text(sheet) == "Lumbar Drain: Open to drain"
    # Save reads the just-blurred value even if its field callback has not run.
    app.save_room(None)
    assert lumbar_drain_text(ss["vault"]["rooms"]["P4102"]) == "Lumbar Drain: Clamped after review"

    ss[include_key] = False
    app.device_row_change("P4102", "neuro_devices", row["id"], "include", include_key)
    app.save_room(None)
    saved = ss["vault"]["rooms"]["P4102"]
    assert not lumbar_drain_text(saved)
    assert automatic_vitals(saved)["Neurologic"] == "CAPD: None"
    assert "Lumbar" not in handoff_text(saved)
    assert saved["neuro_devices"]["rows"][0]["status"] == "Clamped after review"

    ss[include_key] = True
    app.device_row_change("P4102", "neuro_devices", row["id"], "include", include_key)
    app.save_room(None)
    assert lumbar_drain_text(ss["vault"]["rooms"]["P4102"]) == "Lumbar Drain: Clamped after review"


@pytest.mark.parametrize("body", ["Intracranial Pressure Monitor:",
                                 "Intracranial Pressure Monitor:\n[REMOVED] " + LUMBAR,
                                 "Intracranial Pressure Monitor:\nNo Lumbar Drain"])
def test_empty_removed_or_absent_v_clears_previous_lumbar_status(body):
    old = imported(lumbar_source())

    result = import_sections(old, block("v", body), settings())

    assert not result.errors
    assert result.sheet["neuro_devices"] is None
    assert not lumbar_drain_text(result.sheet)
    neuro = automatic_vitals(result.sheet)["Neurologic"]
    assert "Lumbar" not in neuro and "------" not in neuro
    assert "WAT-1" in neuro and "ICP Mean" in neuro
    assert lumbar_drain_text(old) == "Lumbar Drain: Clamped"


def test_failed_v_hides_retained_lumbar_in_all_exports_and_after_reload():
    old = imported(lumbar_source())
    malformed = "vvvvvvvv\nIntracranial Pressure Monitor:\nLumbar Drain-Drain Status: Open"

    result = import_sections(old, malformed, settings())

    assert result.errors and "v" in result.skipped
    assert result.sheet["neuro_devices"] == old["neuro_devices"]
    assert not lumbar_drain_text(result.sheet)
    vault = save_sheet_in(new_vault(), result.sheet)
    key = generate_key()
    saved = open_vault(seal_vault(vault, key), key)["rooms"]["P4102"]
    assert "------" not in automatic_vitals(saved)["Neurologic"]
    for text in (handoff_text(saved), without_style_tags(handoff_html(saved)), pdf_text(saved)):
        assert "Lumbar" not in text
        assert "WAT-1" in text and "ICP Mean" in text


def test_whole_paste_replacement_without_v_cannot_restore_old_lumbar_from_widgets(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = block("v", "Intracranial Pressure Monitor:\n" + LUMBAR)
    app.create_handoff()
    old = ss["drafts"]["P4102"]
    row = old["neuro_devices"]["rows"][0]
    key = "device_" + row["id"] + "_status"
    ss[key] = "OLD_LUMBAR_WIDGET"
    ss["paste"] = block("a", "Diagnoses:\n1. Synthetic replacement example")

    app.create_handoff()

    assert ss["drafts"]["P4102"]["id"] != old["id"]
    assert key not in ss
    app.device_row_change("P4102", "neuro_devices", row["id"], "status", key)
    app.save_room(None)
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved["neuro_devices"] is None
    assert "OLD_LUMBAR_WIDGET" not in json.dumps(saved)
    assert "Lumbar" not in handoff_text(saved)
    assert "------" not in automatic_vitals(saved)["Neurologic"]


def test_evd_icp_and_other_drains_are_not_relabelled_lumbar():
    source = block("v", "Intracranial Pressure Monitor:\n" + EVD + "\n" + ICP
                   + "\nDrain Right surgical site-Drain Status: Suction")
    sheet = imported(source)

    assert not lumbar_drain_text(sheet)
    assert evd_text(sheet) == "EVD: Open to drain"
    assert "Intraparenchymal ICP monitor" in devices_text(sheet)
    assert "Drain Right surgical site | Suction" in devices_text(sheet)
    assert "Lumbar" not in handoff_text(sheet)
    assert "------" not in automatic_vitals(sheet)["Neurologic"]


@pytest.mark.parametrize("body", ["Lumbar puncture culture collected",
                                 "CSF culture from lumbar puncture-Status: Pending"])
def test_lumbar_puncture_or_culture_mentions_do_not_create_a_lumbar_drain(body):
    sheet = imported(block("v", "Intracranial Pressure Monitor:\n" + body))

    assert not lumbar_drain_text(sheet)
    assert "Lumbar Drain:" not in handoff_text(sheet)
    assert automatic_vitals(sheet)["Neurologic"] == "CAPD: None"


def test_lumbar_only_handoff_remains_available_to_print_all():
    sheet = imported(block("v", "Intracranial Pressure Monitor:\n" + LUMBAR))
    assert not devices_text(sheet) and not evd_text(sheet)

    ready = available_handoffs(new_vault(), {"P4102": sheet})

    assert list(ready) == ["P4102"]
    pdf = PdfReader(BytesIO(handoffs_pdf(list(ready.values()))))
    assert len(pdf.pages) == 1
    assert "Lumbar Drain: Clamped" in pdf.pages[0].extract_text()
