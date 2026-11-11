"""Synthetic regressions for alternative orders joined by Epic's Or connector.

All names and dose tokens are fabricated. No attachment content is retained.
"""
from copy import deepcopy
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

from categories import medication_blocks
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_sections
from infusion_rates import administration_display, requested_titration
from medications import (destination_for, format_medication, hidden_for,
                         match_name, parse_medications, rule_for_inline_mapping,
                         set_visibility_rule, upsert_rule, visibility_name)
from models import new_sheet, new_vault, save_sheet_in
from recovery_helpers import assert_retained
from security import generate_key, open_vault, seal_vault


ALPHA = "Synthetic alpha product"
BETA = "Synthetic beta product"


def order(name=ALPHA, dose="DOSE_ALPHA", route="Oral", frequency="q6h",
          *, bullet="•\t", complete=True):
    cells = [name, dose, route, frequency]
    if complete:
        cells += ["PRIVATE_PROVIDER_MARKER", "", "PRIVATE_ADMIN_MARKER"]
    return bullet + "\t".join(cells)


def alternatives(connector="\tOr", *, second_name=BETA, second_dose="DOSE_BETA",
                 second_route="Intravenous", second_frequency="q4h PRN", second_bullet="•\t"):
    return "\n".join([
        "Medications:", order(), connector,
        order(second_name, second_dose, second_route, second_frequency, bullet=second_bullet),
    ])


def wrap(letter, body):
    return letter * 12 + "\n" + body + "\n" + letter * 12


@pytest.mark.parametrize("connector", [
    "Or", "\tOr", "\t\tOr\t", "  or  ", " OR ", "Or:",
    "• Or", "•\tOr", "▪\tOR:", "\u00a0Or\u00a0",
])
def test_standalone_alternative_connector_preserves_independent_orders(connector):
    result = parse_medications(alternatives(connector))
    assert not result.error, result.issues
    assert len(result.rows) == 2
    first, second = result.rows
    assert first["id"] != second["id"]
    assert first["name"] == ALPHA
    assert second["name"] == "Or: " + BETA
    assert [row["dose"] for row in result.rows] == ["DOSE_ALPHA", "DOSE_BETA"]
    assert [row["route"] for row in result.rows] == ["Oral", "Intravenous"]
    assert [row["frequency"] for row in result.rows] == ["q6h", "q4h PRN"]
    assert all(row["last_rate"] == row["rate_time"] == "" for row in result.rows)
    assert format_medication(second).startswith(BETA)
    assert "Or: " not in format_medication(second)
    assert "PRIVATE_" not in json.dumps(result.rows)


@pytest.mark.parametrize("bullet", ["", "• ", "●\t", "- "])
def test_order_after_or_accepts_existing_explicit_table_row_variants(bullet):
    result = parse_medications(alternatives(second_bullet=bullet))
    assert not result.error
    assert len(result.rows) == 2
    assert result.rows[1]["name"] == "Or: " + BETA


@pytest.mark.parametrize("complete, suffix", [
    (True, "\tOr"), (True, "\tOR:\t \t"),
    (False, "\tOr"), (False, "\tOr\t\t"),
])
def test_alternative_connector_in_final_tab_cell_does_not_shift_columns(complete, suffix):
    source = "Medications:\n" + order(complete=complete) + suffix + "\n" + order(
        BETA, "", "Topical", "PRN", complete=complete)
    result = parse_medications(source)
    assert not result.error, result.issues
    assert len(result.rows) == 2
    assert result.rows[0]["dose"] == "DOSE_ALPHA"
    second = result.rows[1]
    assert second["name"] == "Or: " + BETA
    assert second["dose"] == ""
    assert second["route"] == "Topical"
    assert second["frequency"] == "PRN"
    assert second["last_rate"] == second["rate_time"] == ""
    assert "PRIVATE_" not in json.dumps(result.rows)


def test_all_empty_optional_cells_remain_empty():
    second = "•\t" + "\t".join([BETA, "", "Topical", "PRN", "", "", ""])
    result = parse_medications("Medications:\n" + order() + "\n\tOr\n" + second)
    assert not result.error and len(result.rows) == 2
    row = result.rows[1]
    assert (row["dose"], row["route"], row["frequency"], row["last_rate"], row["rate_time"]) == (
        "", "Topical", "PRN", "", "")


@pytest.mark.parametrize("annotations", [
    "", "[Held by provider] ", "[START ON 01/01/2099] ",
    "[Held by provider] [START ON 01/01/2099] ",
    "[START ON 01/01/2099] [Held by provider] ",
])
def test_or_prefix_does_not_block_routing_or_generic_visibility(annotations):
    rules = upsert_rule([], "Synthetic beta", "Neurologic")
    visibility = set_visibility_rule([], "Synthetic beta", True, "prefix")
    result = parse_medications(alternatives(second_name=annotations + BETA), rules, visibility)
    assert not result.error
    second = result.rows[1]
    assert second["name"] == "Or: " + annotations + BETA
    assert second["section"] == "Neurologic" and second["hidden"]
    assert not result.rows[0]["hidden"]
    assert match_name(second["name"]) == BETA.lower()
    assert rule_for_inline_mapping(second["name"], rules) == ("synthetic beta product", "prefix")


def test_exact_visibility_and_mapping_keep_scheduled_dates_distinct():
    dated = "[START ON 01/01/2099] " + BETA
    name = "Or: [Held by provider] " + dated
    rules = upsert_rule([], dated, "Neurologic", "exact")
    visibility = set_visibility_rule([], name, True)
    assert destination_for(name, rules) == "Neurologic"
    assert hidden_for(name, visibility)
    assert hidden_for(dated, visibility)
    assert visibility_name(name) == dated.lower()
    other_date = name.replace("01/01/2099", "01/02/2099")
    assert destination_for(other_date, rules) == "Other Medications"
    assert not hidden_for(other_date, visibility)
    assert not hidden_for(BETA, visibility)


def test_connectors_apply_only_to_the_next_separate_order():
    source = alternatives() + "\nAnd\n" + order("Synthetic gamma product", "DOSE_GAMMA")
    source += "\n" + order("Synthetic delta product", "DOSE_DELTA")
    result = parse_medications(source)
    assert not result.error
    assert [row["name"] for row in result.rows] == [
        ALPHA, "Or: " + BETA, "And: Synthetic gamma product", "Synthetic delta product"]


def test_literal_or_inside_medication_name_remains_literal():
    name = "Synthetic oral or topical product"
    result = parse_medications("Medications:\n" + order(name))
    assert not result.error
    assert result.rows[0]["name"] == name
    assert match_name(name) == name.lower()


@pytest.mark.parametrize("source", [
    "Medications:\nOr\n" + order(),
    "Medications:\n" + order() + "\nOr",
    "Medications:\n" + order() + "\tOr",
    "Medications:\n" + order() + "\nOr\nOr\n" + order(BETA),
    "Medications:\n" + order() + "\nOr\nAnd\n" + order(BETA),
    "Medications:\n" + order() + "\nAnd\nOr\n" + order(BETA),
    "Medications:\n" + order() + "\nOr\nMissing tabular columns",
    "Medications:\n" + order() + "\nOr\n" + order(BETA, route=""),
    "Medications:\n" + order() + "\nOr\n" + order(BETA, frequency=""),
    "Medications:\n" + order() + "\tUNRECOGNIZED_EXTRA_CELL",
    "Medications:\n" + order() + "\tOr\tUNRECOGNIZED_EXTRA_CELL",
])
def test_invalid_sequences_and_columns_keep_the_previous_medication_list(source):
    parsed = parse_medications(source)
    assert parsed.error
    sheet = new_sheet("P4102")
    sheet["medications"] = parse_medications("Medications:\n" + order("Synthetic saved product")).rows
    before = deepcopy(sheet)
    out = import_sections(sheet, wrap("b", source), new_vault()["settings"])
    assert_retained(out, before, "b")
    assert sheet == before
    assert "PRIVATE_" not in json.dumps(out.errors) + json.dumps(out.diagnostics)


def test_failed_alternative_block_is_atomic_and_corrected_reimport_recovers():
    sheet = new_sheet("P4102")
    sheet["medications"] = parse_medications("Medications:\n" + order("Synthetic saved product")).rows
    before = deepcopy(sheet)
    bad = wrap("a", "Diagnoses:\nSynthetic section update") + "\n"
    bad += wrap("b", alternatives() + "\n• unstructured row")
    failed = import_sections(sheet, bad, new_vault()["settings"])
    assert_retained(failed, before, "b")
    assert failed.sheet["fields"]["Diagnoses"] == "Synthetic section update"
    corrected = import_sections(failed.sheet, wrap("b", alternatives()), new_vault()["settings"])
    assert not corrected.errors
    assert "b" not in corrected.sheet["import_warnings"]
    assert len(corrected.sheet["medications"]) == 2
    assert corrected.sheet["medications"][1]["name"] == "Or: " + BETA
    assert sheet == before


def test_alternatives_survive_encrypted_save_and_all_export_formats_once():
    out = import_sections(new_sheet("P4102"), wrap("b", alternatives()), new_vault()["settings"])
    assert not out.errors
    vault = save_sheet_in(new_vault(), out.sheet)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == vault
    sheet = restored["rooms"]["P4102"]
    before = deepcopy(sheet)
    outputs = [handoff_html(sheet), handoff_text(sheet)]
    for data in (handoff_pdf(sheet), handoffs_pdf([sheet])):
        outputs.append("\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages))
    for text in outputs:
        text = re.sub(r"\s+", " ", text)
        assert text.count(ALPHA) == text.count(BETA) == 1
        assert "Or: " + BETA not in text
        assert "DOSE_ALPHA" in text and "DOSE_BETA" in text
        assert "PRIVATE_" not in text
    assert sheet == before


@pytest.mark.parametrize("name", ["norepinephrine", "nicardipine", "nitroprusside"])
@pytest.mark.parametrize("last_admin", ["", "5.5 mL/hr at 01/01/2099 0900"])
def test_alternative_named_titration_requires_documented_admin_rate(name, last_admin):
    # Entirely invented parser inputs. The fixed ordered dose and Continuous
    # frequency intentionally do not trigger range- or frequency-based rules.
    second = "•\t" + "\t".join([
        name + " SYNTHETIC infusion", "7.25 mL/hr", "Intravenous", "Continuous",
        "PRIVATE_PROVIDER_MARKER", "", last_admin,
    ])
    result = parse_medications("Medications:\n" + order() + "\nOr\n" + second)
    assert not result.error and len(result.rows) == 2
    row = result.rows[1]
    assert row["name"] == "Or: " + name + " SYNTHETIC infusion"
    assert row["dose"] == "7.25 mL/hr"
    assert row["frequency"] == "Continuous"
    assert requested_titration(row)
    if last_admin:
        assert row["last_admin_rate"] == "5.5 mL/hr"
        assert row["last_admin_status"] == "rate"
        assert administration_display(row) == ("Last Admin rate", "5.5 mL/hr", "01/01/2099 0900")
        assert "Last Admin rate: 5.5 mL/hr" in format_medication(row)
    else:
        assert row["last_admin_rate"] == ""
        assert row["last_admin_status"] == "unavailable"
        assert administration_display(row) == ("Last Admin rate", "UNK", "")
        assert "Last Admin rate: UNK" in format_medication(row)
    assert "Dose: 7.25 mL/hr" not in format_medication(row)
    assert "PRIVATE_" not in json.dumps(result.rows)


def test_same_neuro_group_keeps_alternative_after_its_preceding_order():
    # Distinct first words deliberately reverse the ordinary Neuro sort order.
    # Using a shared first word would not exercise the alphabetical-sort bug.
    first_name = "SyntheticZeta product"
    alternative_name = "SyntheticAlpha product"
    other_name = "SyntheticDelta product"
    source = "\n".join([
        "Medications:", order(first_name), "Or", order(alternative_name, "DOSE_BETA"),
        order(other_name, "DOSE_DELTA"),
    ])
    settings = new_vault()["settings"]
    for name in (first_name, alternative_name, other_name):
        settings["medication_mappings"] = upsert_rule(settings["medication_mappings"], name, "Neurologic", "exact")
    out = import_sections(new_sheet("P4102"), wrap("b", source), settings)
    assert not out.errors
    sheet = out.sheet
    before = deepcopy(sheet)
    blocks = medication_blocks("Neurologic", "", sheet["medications"])
    names = [item["name"] for _, item in blocks if isinstance(item, dict)]
    assert names.index("Or: " + alternative_name) == names.index(first_name) + 1
    outputs = [handoff_text(sheet), handoff_html(sheet)]
    outputs.append("\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages))
    for text in outputs:
        text = re.sub(r"\s+", " ", text)
        assert text.index(first_name) < text.index(alternative_name)
        assert "Or: " + alternative_name not in text
    assert sheet == before
