"""FEN/GI template selection uses only synthetic current-age evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from importing import import_sections
from models import new_sheet, new_vault
from note_fengi import FENGI_TEMPLATE_FILES, select_fengi_variant


def sheet(age="", demographics="", **measurements):
    return {
        "anthropometrics": {"age": age, **measurements},
        "fields": {"Demographics / Weight": demographics},
    }


@pytest.mark.parametrize("age", [
    "0 days", "10 days", "5 d.o.", "5 weeks", "5 wk.o.", "5 WK. O.",
    "5 wk.o. 2 d.o.", "18 m.o.", "23 months", "23.99 months", "1 year",
    "1 y.o.", "1 yr.o.", "1 year 11 months", "1 y.o. 11 m.o.", "0y 0m",
    "1.5 years", "1.99 y.o.", "18 months 2 days", "6 months 28 days",
])
def test_documented_under_two_ages_select_infant_template(age):
    assert select_fengi_variant(sheet(age)) == {
        "variant": "under_2", "age_text": age, "warning": "",
    }


@pytest.mark.parametrize("age", [
    "2 years", "2 y.o.", "2 yr.o.", "2 years 0 months", "2 y.o. 0 m.o.",
    "24 months", "24 m.o.", "24.0 months", "24.01 months", "2.0 years",
    "25 months", "5 years 2 months", "18 years", "744 days", "107 weeks",
])
def test_exact_second_birthday_and_older_select_age_two_plus(age):
    assert select_fengi_variant(sheet(age)) == {
        "variant": "age_2_plus", "age_text": age, "warning": "",
    }


@pytest.mark.parametrize("age,variant", [
    ("23.999999999999999999999999999999 months", "under_2"),
    ("24.000000000000000000000000000001 months", "age_2_plus"),
    ("1.999999999999999999999999999999 years", "under_2"),
    ("2.000000000000000000000000000001 years", "age_2_plus"),
])
def test_recorded_decimal_is_not_rounded_across_second_birthday(age,variant):
    assert select_fengi_variant(sheet(age))["variant"] == variant


@pytest.mark.parametrize("age", [
    "", "unknown", "--", "not recorded", "2", "two years", "about 2 years",
    "18-24 months", "<2 years", "2 years?", "104 weeks", "730 days",
    "23 months 28 days", "23 months 29 days", "1 year 12 months",
    "1 year 13 months", "5 weeks 8 days", "24 months 31 days",
    "18 months 3 months", "2 years or 18 months", "-1 years", "NaN months",
    "18 months (corrected)", None, 24, {"age": "2 years"},
])
def test_missing_ambiguous_or_malformed_age_keeps_generic_fen_section(age):
    result = select_fengi_variant(sheet(age))
    assert result["variant"] is None
    assert "current patient age" in result["warning"]
    assert "regenerate" in result["warning"]
    assert result["age_text"] == (age.strip() if isinstance(age,str) else "")


@pytest.mark.parametrize("demographics,age_text,variant", [
    ("Age: 18 m.o.", "18 m.o.", "under_2"),
    ("Age:\n\n18 m.o.\nSex:\nFemale", "18 m.o.", "under_2"),
    ("Age: 2 y.o. Sex: Female", "2 y.o.", "age_2_plus"),
    ("Sex: Female Age: 24 months", "24 months", "age_2_plus"),
    ("Age in months: 24", "24", "age_2_plus"),
    ("Age in\tmonths:\n23", "23", "under_2"),
    ("Age: 18 months BMI Age: 24 months HC Age: 190 days", "18 months", "under_2"),
    ("BMI Age: 18 months Age: 24 months", "24 months", "age_2_plus"),
])
def test_missing_structured_age_uses_only_explicit_current_demographic_age(demographics,age_text,variant):
    result = select_fengi_variant(sheet("",demographics))
    assert result == {"variant":variant,"age_text":age_text,"warning":""}


@pytest.mark.parametrize("demographics", [
    "BMI Age: 24 months", "HC Age: 24 months", "Head Circumference Age: 24 months",
    "Age at BMI measurement: 24 months", "Age at HC measurement: 24 months",
    "Age at measurement: 24 months", "Corrected Age: 24 months",
    "Gestational Age: 40 weeks", "Maternal Age: 30 years", "Historical Age: 24 months",
    "Age on admission: 24 months", "DOB: 11/26/2024", "Date of birth: 11/26/2024",
    "CDC (Girls, 2-20 Years) data", "An 18-month-old infant", "Age:\nWeight: 12 kg",
])
def test_measurement_historical_nonpatient_and_inferred_ages_are_not_fallbacks(demographics):
    result = select_fengi_variant(sheet("",demographics,bmi_age="24 months",hc_age="24 months"))
    assert result["variant"] is None
    assert result["age_text"] == ""
    assert result["warning"]


def test_structured_current_age_has_precedence_over_measurement_ages_and_other_prose():
    value = sheet("18 months", "BMI Age: 24 months\nAge at measurement: 5 years\n"
                  "Historical Age: 6 years\nDOB: 11/26/2020",
                  bmi_age="3 years",hc_age="5 years")
    value.update(age_as_of="2020-01-01",admission_date="11/26/2020",age="10 years")
    assert select_fengi_variant(value) == {"variant":"under_2","age_text":"18 months","warning":""}


@pytest.mark.parametrize("age", ["unknown","incorrect", "104 weeks",24,None])
def test_nonblank_unusable_primary_age_does_not_fall_back_to_valid_demographic_age(age):
    result = select_fengi_variant(sheet(age,"Age: 24 months"))
    assert result["variant"] is None
    assert result["warning"]


@pytest.mark.parametrize("heading", [
    "Previous admission demographics", "BMI measurement from prior visit",
    "Head circumference measurement", "Historical demographics", "History",
    "Age at measurement", "BMI", "HC",
])
@pytest.mark.parametrize("age,variant", [("",None),("24 months","age_2_plus")])
def test_age_under_historical_or_measurement_heading_is_never_current(heading,age,variant):
    result = select_fengi_variant(sheet(age,heading+":\nAge: 18 months"))
    assert result["variant"] == variant
    assert result["age_text"] == age
    assert bool(result["warning"]) is (variant is None)


def test_explicit_current_demographic_heading_ends_historical_context():
    text = "Previous admission demographics:\nAge: 18 months\nCurrent demographics:\nAge: 24 months"
    assert select_fengi_variant(sheet("",text)) == {
        "variant":"age_2_plus","age_text":"24 months","warning":"",
    }


def test_current_age_before_history_stays_current():
    text = "Age: 24 months\nPrevious admission demographics:\nAge: 18 months"
    assert select_fengi_variant(sheet("",text)) == {
        "variant":"age_2_plus","age_text":"24 months","warning":"",
    }


@pytest.mark.parametrize("age,demographics", [
    ("18 months","Age: 24 months"), ("2 years","Age: 18 months"),
    ("18 months","Age: 19 months"), ("1 year","Age: 2 years"),
    ("","Age: 18 months\nAge: 24 months"),
    ("","Age: 18 months Age: 24 months"),
    ("24 months","Age: unknown"),
])
def test_conflicting_current_age_sources_require_review(age,demographics):
    result = select_fengi_variant(sheet(age,demographics))
    assert result["variant"] is None
    assert result["warning"]
    assert result["age_text"] == (age or "18 months")


@pytest.mark.parametrize("age,demographics,variant", [
    ("1 year","Age: 18 months","under_2"),
    ("2 y.o.","Age: 24 months","age_2_plus"),
    ("24 months","Age: 2 years 0 months","age_2_plus"),
    ("","Age: 2 years\nAge: 24 months","age_2_plus"),
])
def test_compatible_current_age_sources_preserve_primary_wording(age,demographics,variant):
    result = select_fengi_variant(sheet(age,demographics))
    assert result["variant"] == variant
    assert result["age_text"] == (age or "2 years")
    assert not result["warning"]


def test_imported_canonical_age_already_resolves_a_i_n_source_precedence():
    def block(letter,body):
        return letter*16+"\n"+body+"\n"+letter*16
    source = "\n".join([
        block("a","Diagnoses:\nSynthetic condition\nAge: 18 months"),
        block("i","NUTRITION:\nAge: 23 months\nBMI Age: 18 months"),
        block("n","Date of Admission: 11/26/2026\nAge: 2 y.o."),
    ])
    result = import_sections(new_sheet("P4102"),source,new_vault()["settings"])
    assert not result.errors
    assert result.sheet["anthropometrics"]["age"] == "2 y.o."
    assert select_fengi_variant(result.sheet) == {"variant":"age_2_plus","age_text":"2 y.o.","warning":""}


def test_selection_is_pure_and_result_is_json_friendly():
    value = sheet("18 months","Manual demographic note",bmi_age="25 months",hc_age="190 days")
    value["anthropometrics"].update(height="60 cm",bmi="17 kg/m²")
    value["medications"] = [{"name":"Synthetic medication","dose":"2 mcg/kg/hr"}]
    value["nutrition"] = {"weight":"12 kg"}
    before = deepcopy(value)
    first = select_fengi_variant(value)
    assert select_fengi_variant(value) == first
    assert json.loads(json.dumps(first)) == first
    assert value == before


@pytest.mark.parametrize("value", [{},None,{"anthropometrics":None},{"fields":None}])
def test_missing_sheet_shapes_return_static_warning(value):
    assert select_fengi_variant(value) == select_fengi_variant({})


def test_template_paths_identify_only_the_two_supplied_assets():
    root = Path(__file__).parents[1] / "templates"
    assert FENGI_TEMPLATE_FILES == {
        "under_2":root / "fengi_under_2.docx",
        "age_2_plus":root / "fengi_age_2_plus.docx",
    }
