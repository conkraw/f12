"""Synthetic detailed dietary orders, source boundaries and unknown values."""
from copy import deepcopy
import json

import pytest

from diet import (ENTERAL_KEYS, PARENTERAL_KEYS, parse_diet, validate_diet,
                  diet_failed, diet_for_output)


def tube(formula="Synthetic Vanilla", route="Gastrostomy tube", hours="18", rate="45",
         volume="810", additive_flag="No Additives", tail="24", annotation=""):
    return (annotation + "Infant tube feeding Pediatric Tube Feeding; " + formula +
            "; Continuous Feeds; " + route + "; " + hours + " hours; " + rate +
            "; " + volume + "; " + additive_flag + "; " + tail)


def detailed_order(header=None, *, formula="Synthetic Vanilla", route="Gastrostomy tube",
                   hours="18", rate="45", volume="810", comments="", density="24",
                   additive_flag="No Additives", additive="", summary=True):
    header = header or tube(formula, route, hours, rate, volume, additive_flag, additive or density)
    lines = ["Dietary Orders:", "Dietary Orders (From admission, onward)",
             "Start\t\tOrdered", "01/02/26 0800", header + "  Diet effective now"]
    if comments:
        lines.append("Comments: " + comments)
    lines += ["Question\tAnswer\tComment", "Diet:\tPediatric Tube Feeding\t",
              "Formula:\t" + formula + "\t", "Type:\tContinuous Feeds\t",
              "Route:\t" + route + "\t", "Infusion time (hours)\t" + hours + " hours\t",
              "Tube feeding continuous rate (mL/hr):\t" + rate + "\t",
              "Total Volume (mL/day):\t" + volume + "\t", "Additives?\t" + additive_flag + "\t"]
    if additive:
        lines.append("Select Additive\t" + additive + "\t")
    elif density:
        lines.append("Caloric density (kcal per ounce):\t" + density + "\t")
    lines += ["01/02/26 0759", "Diet Orders"]
    if summary:
        lines.append(header + ": Tube Feeding starting at 01/02 0800")
    return "\n".join(lines)


def parsed(text, **kwargs):
    result = parse_diet(text, **kwargs)
    assert not result.error, result.error
    validate_diet(result.data)
    return result


def test_complete_order_deduplicates_detailed_qa_and_compact_summary():
    result = parsed(detailed_order())
    assert not result.issues and not result.diagnostics
    assert set(result.data) == {"rows", "enteral", "parenteral"}
    assert not result.data["rows"] and not result.data["parenteral"]
    assert len(result.data["enteral"]) == 1
    row = result.data["enteral"][0]
    assert set(row) == ENTERAL_KEYS
    assert (row["method"], row["formula"], row["rate"], row["hours"], row["daily_volume"]) == (
        "GT", "Synthetic Vanilla", "45 mL/hr", "18", "810")
    assert row["caloric_density"] == "24 kcal/oz"
    assert row["status"] == "active" and row["include"]


@pytest.mark.parametrize("route,method", [
    ("Gastrostomy tube", "GT"), ("Nasogastric tube", "NG"),
    ("Nasojejunal tube", "NJ"), ("Nasoenteric (post-pyloric) tube", "Post-pyloric"),
    ("Orogastric tube", "OG"), ("Gastrojejunostomy tube", "GJ"),
])
def test_only_explicit_route_is_abbreviated(route, method):
    row = parsed(detailed_order(route=route)).data["enteral"][0]
    assert row["method"] == method and row["route"] == route


def test_formula_fortifier_and_full_instructions_are_retained():
    comments = ("Fortify with Synthetic Infant powder to 25kcal/oz.\n"
                "May use milk swab for oral stimulation.\n"
                "Use the stated mixture and pause four hours during the day.")
    result = parsed(detailed_order(formula="Breast Milk", additive_flag="Additives",
                                  additive="BM w Synthetic powder= 25 kcal/oz",
                                  density="", comments=comments))
    row = result.data["enteral"][0]
    assert row["formula"] == "Breast Milk"
    assert row["caloric_density"] == "25 kcal/oz"
    assert row["additives"] == "BM w Synthetic powder= 25 kcal/oz"
    assert row["comments"] == " ".join(comments.splitlines())
    assert not result.data["rows"]


def test_mixture_and_titration_do_not_replace_ordered_formula_or_rate():
    comments = ("Synthetic Vanilla PLANT BASED\nStart at 5mL/hr and increase by 5mL/hr. "
                "The mixture includes 300mL formula + 510mL water.")
    row = parsed(detailed_order(additive_flag="Additives", additive="Other - note in comments",
                               density="", comments=comments)).data["enteral"][0]
    assert row["formula"] == "Synthetic Vanilla" and row["rate"] == "45 mL/hr"
    assert "5mL/hr" in row["comments"] and "300mL" in row["comments"]


@pytest.mark.parametrize("name,summary", [("Regular", "Peds Regular"), ("Clear Liquid", "Peds Clear Liquid")])
def test_oral_question_answer_and_summary_are_one_order(name, summary):
    source = ("Dietary Orders:\n01/02/26 0800\nPediatric diet " + name + " Diet effective now\n"
              "Question: Diet type: Answer: " + name + "\n01/02/26 0759\nDiet Orders\n"
              "Pediatric diet " + name + ": General starting at 01/02 0800")
    result = parsed(source)
    assert len(result.data["rows"]) == 1
    assert result.data["rows"][0]["text"] == summary
    assert not result.data["enteral"] and not result.diagnostics


def test_npo_medication_route_is_not_a_feed_and_milk_labels_are_ignored():
    source = ("Dietary Orders:\nNPO diet NPO except: Other (specify); Explanatory comment: "
              "except for medications (NJ) Diet effective now\nQuestion\tAnswer\tComment\n"
              "NPO except:\tOther (specify)\t\nExplanatory comment:\texcept for medications (NJ)\t\n"
              "Diet Orders\nPediatric 2-in-1 PN (Continuous) at 8 mL/hr starting at 01/02 2100\n"
              "NPO diet NPO except: Other (specify); Explanatory comment: except for medications (NJ): NPO starting at 01/02 0800\n"
              "Breast Milk (print labels) starting at 01/01 0500")
    result = parsed(source)
    assert [r["text"] for r in result.data["rows"]] == ["NPO except meds (NJ)"]
    assert not result.data["enteral"]
    assert len(result.data["parenteral"]) == 1
    assert result.data["parenteral"][0]["rate"] == "8 mL/hr"
    assert not result.diagnostics


def test_explicit_npo_exception_conflict_is_not_overwritten_by_answer():
    source = ("Dietary Orders:\nNPO diet NPO except: No Exceptions Diet effective now\n"
              "Question: NPO except: Answer: Medications")
    result = parsed(source)
    assert {row["text"] for row in result.data["rows"]} == {"NPO", "NPO except meds"}
    assert any(item["code"] == "nutrition_conflict" for item in result.diagnostics)


def test_comment_labels_do_not_override_structured_order_fields():
    source = detailed_order(comments="Formula: Old Formula\nRoute: Nasojejunal tube\nRate: 5mL/hr")
    row = parsed(source).data["enteral"][0]
    assert row["formula"] == "Synthetic Vanilla" and row["method"] == "GT"
    assert row["rate"] == "45 mL/hr" and "Old Formula" in row["comments"]


def test_oral_tube_and_pn_orders_coexist_without_duplicates():
    source = detailed_order() + "\nPediatric diet Regular: General\nTPN at 8 mL/hr\nTPN at 8 mL/hr"
    result = parsed(source)
    assert len(result.data["rows"]) == len(result.data["enteral"]) == len(result.data["parenteral"]) == 1
    assert set(result.data["parenteral"][0]) == PARENTERAL_KEYS
    assert not result.diagnostics


@pytest.mark.parametrize("value", ["", "Dietary Orders:", "Dietary Orders:\nDiet Orders\nNone"])
def test_explicit_empty_detailed_snapshot(value):
    result = parsed(value, detailed=True)
    assert result.data == {"rows": [], "enteral": [], "parenteral": []}
    assert not result.diagnostics


@pytest.mark.parametrize("annotation,status", [("[Held by provider] ", "held"), ("[START ON 01/03/2026] ", "future")])
def test_held_and_future_tube_and_pn_orders_keep_status(annotation, status):
    result = parsed("Dietary Orders:\n" + tube(annotation=annotation) + "\n" + annotation + "TPN at 8 mL/hr")
    assert result.data["enteral"][0]["status"] == result.data["parenteral"][0]["status"] == status
    assert result.data["enteral"][0]["rate"] == "45 mL/hr"


@pytest.mark.parametrize("annotation", ["[REMOVED] ", "[DISCONTINUED] ", "Discontinued: ", "Cancelled: "])
def test_removed_orders_do_not_become_feeds(annotation):
    source = "Dietary Orders:\n" + annotation + tube() + "\n" + annotation + "TPN at 8 mL/hr"
    result = parsed(source)
    assert result.data == {"rows": [], "enteral": [], "parenteral": []}


@pytest.mark.parametrize("field,header_value,answer,expected_field", [
    ("rate", "45", "46", "rate"), ("hours", "18", "20", "hours"),
    ("formula", "Synthetic Vanilla", "Synthetic Chocolate", "formula"),
    ("route", "Gastrostomy tube", "Nasojejunal tube", "route"),
    ("volume", "810", "900", "daily_volume"),
])
def test_header_answer_conflict_is_not_restored_by_duplicate_summary(field, header_value, answer, expected_field):
    arguments = {field: answer}
    result = parsed(detailed_order(header=tube(), **arguments))
    assert len(result.data["enteral"]) == 1
    assert result.data["enteral"][0][expected_field] == ""
    assert any(d["code"] == "nutrition_conflict" and d["field"] == expected_field for d in result.diagnostics)
    assert header_value in result.data["enteral"][0]["source"]
    assert answer in result.data["enteral"][0]["source"]


@pytest.mark.parametrize("hours", ["0", "25", "-2", "twenty", "unknown"])
def test_bad_or_unknown_hours_never_default_to_24(hours):
    result = parsed("Dietary Orders:\n" + tube(hours=hours))
    assert result.data["enteral"][0]["hours"] == ""
    assert any(d["code"] in ("nutrition_conflict", "nutrition_incomplete") for d in result.diagnostics)


def test_qa_only_order_does_not_borrow_numbers_from_comments():
    source = ("Dietary Orders:\nDiet:\tInfant Tube Feeding\nFormula:\tSynthetic Formula\n"
              "Type:\tContinuous Feeds\nRoute:\tGastrostomy tube\n"
              "Comments: running for 24 hours at 30mL/hr yesterday")
    row = parsed(source).data["enteral"][0]
    assert row["formula"] == "Synthetic Formula" and row["method"] == "GT"
    assert row["hours"] == row["rate"] == ""


def test_numerically_equivalent_qa_values_are_not_conflicts():
    result = parsed(detailed_order(header=tube(volume="1,080", rate="45.0", hours="24.0"),
                                  volume="1080", rate="45", hours="24"))
    assert not result.diagnostics
    row = result.data["enteral"][0]
    assert (row["rate"], row["hours"], row["daily_volume"]) == ("45 mL/hr", "24", "1080")


def test_legacy_snapshot_and_simple_x_result_still_valid():
    result = parsed("Diet:\nAdult diet Regular: General starting at 01/02 0800")
    assert set(result.data) == {"rows"}
    original = deepcopy(result.data)
    validate_diet(result.data)
    assert result.data == original


def test_detailed_semicolon_x_order_is_recognized_without_qa():
    result = parsed("Diet:\n" + tube())
    assert result.data["enteral"][0]["formula"] == "Synthetic Vanilla"


def test_new_snapshot_does_not_store_unrecognized_source_in_diagnostics():
    result = parsed("Dietary Orders:\nPRIVATE_SENTINEL unknown content\n" + tube())
    assert "PRIVATE_SENTINEL" not in json.dumps(result.diagnostics)
    assert any(d["code"] == "diet_unrecognized" for d in result.diagnostics)


def test_fortifier_density_conflict_is_visible_for_review():
    source = detailed_order(additive_flag="Additives", additive="BM w Synthetic powder= 25 kcal/oz", density="")
    source = source.replace("Select Additive\t", "Caloric density (kcal per ounce):\t27\t\nSelect Additive\t", 1)
    result = parsed(source)
    assert result.data["enteral"][0]["caloric_density"] == ""
    assert any(d["field"] == "caloric_density" and d["code"] == "nutrition_conflict" for d in result.diagnostics)


@pytest.mark.parametrize("field,value", [("hours", "25"), ("hours", "-1"), ("rate", "40 mL"),
                                         ("method", "invented"), ("include", "yes"),
                                         ("comments", "a\nb"), ("status", "running"),
                                         ("rate", "9" * 21 + " mL/hr"),
                                         ("daily_volume", "9" * 21)])
def test_extended_validation_rejects_invalid_edits(field, value):
    data = parsed(detailed_order()).data
    data["enteral"][0][field] = value
    with pytest.raises(ValueError):
        validate_diet(data)


@pytest.mark.parametrize("field", ["rate", "volume", "hours"])
def test_unbounded_source_numbers_are_omitted_for_review(field):
    result = parsed("Dietary Orders:\n" + tube(**{field: "9" * 100}))
    key = "daily_volume" if field == "volume" else field
    assert result.data["enteral"][0][key] == ""
    assert any(item["code"] == "nutrition_conflict" for item in result.diagnostics)


def test_optional_current_feed_ids_are_validated():
    data = parsed(detailed_order()).data
    data["recorded_feed_ids"] = ["a" * 32]
    validate_diet(data)
    data["recorded_feed_ids"] = ["a" * 32, "a" * 32]
    with pytest.raises(ValueError):
        validate_diet(data)
    with pytest.raises(ValueError):
        validate_diet({"rows": [], "recorded_feed_ids": []})


@pytest.mark.parametrize("section", ["x", "ab"])
def test_failed_legacy_or_new_section_hides_retained_diet(section):
    data = parsed(detailed_order()).data
    sheet = {"diet": data, "import_warnings": {section: [{"action": "diet_hidden"}]}}
    assert diet_failed(sheet) and diet_for_output(sheet) is None
    assert sheet["diet"] == data
