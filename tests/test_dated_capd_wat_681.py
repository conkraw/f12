"""Recorded CAPD/WAT source dates and privacy, using synthetic inputs only."""
from copy import deepcopy
import json

import pytest

from capd import canonical_capd_value, capd_display_row, parse_capd, validate_capd_rows
from observations import (empty_neuro, neuro_rows, normalize_score_rows, parse_neuro,
                          validate_neuro, wat_display_rows)
from score_dates import (date_label, latest_score, sanitize_score_line,
                         score_with_date, split_score_stamp)


STAFF = "SYNTHETIC_CLINICIAN_SENTINEL"


def score_row(label, value, include=True):
    return {"label": label, "value": value, "section": "Neurologic", "include": include}


def parse_score(source, content):
    return parse_capd(content) if source == "y" else parse_neuro(content, "l")


@pytest.mark.parametrize("source,label,score", [
    ("y", "CAPD: Cornell Assessment of Pediatric Delirium Score", "15"),
    ("l", "WAT-1 total score (0-12)", "3"),
])
def test_epic_attribution_and_time_never_enter_saved_score(source, label, score):
    result = parse_score(source, label + ": " + score + " (11/14/26 0607 : " + STAFF + ", RN)")
    assert not result.error and not result.issues
    assert result.rows == [score_row("CAPD" if source == "y" else "WAT-1", score + " (11/14/26)")]
    assert STAFF not in json.dumps(result.__dict__)
    assert "0607" not in json.dumps(result.__dict__)


@pytest.mark.parametrize("source,label,older,newer", [
    ("y", "CAPD", "28", "2"), ("l", "WAT-1", "9", "1"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_latest_chronological_value_wins_in_either_paste_order(source, label, older, newer, reverse):
    rows = [label + ": " + older + " (11/13/26 2300 : " + STAFF + ", RN)",
            label + ": " + newer + " (11/14/26 0030 : " + STAFF + ", RN)"]
    if reverse:
        rows.reverse()
    result = parse_score(source, "\n".join(rows))
    assert not result.error
    assert result.rows[0]["value"] == newer + " (11/14/26)"


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
@pytest.mark.parametrize("stamp", ["11/14/26", "11/14/2026", "11/14/26 06:07", "11/14/26 0607"])
def test_date_forms_report_only_source_date(source, label, stamp):
    result = parse_score(source, label + ": 0 (" + stamp + " : " + STAFF + ", RN)")
    assert not result.error and result.rows[0]["value"] == "0 (11/14/26)"


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
@pytest.mark.parametrize("stamps,values", [
    (("11/14/26 0600", "11/14/26 0900"), ("5", "1")),
    (("11/13/26", "11/14/26 0900"), ("5", "1")),
    (("11/14/26", "11/14/26 0900"), ("1", "1")),
    (("11/14/26 0900", "11/14/26 0900"), ("1", "1")),
])
def test_timestamp_order_and_equivalent_duplicates_are_safe(source, label, stamps, values):
    rows = [label + ": " + value + " (" + stamp + " : " + STAFF + ", RN)"
            for value, stamp in zip(values, stamps)]
    result = parse_score(source, "\n".join(reversed(rows)))
    assert not result.error
    assert result.rows == [score_row(label, "1 (11/14/26)")]


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
@pytest.mark.parametrize("stamps", [
    ("11/14/26 0900", "11/14/26 0900"),
    ("11/14/26", "11/14/26 0900"),
    ("11/14/26", "11/14/26"),
    ("", "11/14/26 0900"),
    ("", ""),
])
def test_unknown_order_never_guesses_a_latest_score(source, label, stamps):
    rows = [label + ": " + value + (" (" + stamp + " : " + STAFF + ", RN)" if stamp else "")
            for value, stamp in zip(("5", "1"), stamps)]
    result = parse_score(source, "\n".join(rows))
    assert result.error and not result.rows
    assert STAFF not in json.dumps(result.__dict__)


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
@pytest.mark.parametrize("stamp", ["02/30/26 0900", "11/14/26 2460", "13/14/26", "11/14/26 25:00"])
def test_invalid_source_date_fails_without_retaining_staff(source, label, stamp):
    result = parse_score(source, label + ": 3 (" + stamp + " : " + STAFF + ", RN)")
    assert result.error and not result.rows
    assert STAFF not in json.dumps(result.__dict__)


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
def test_old_source_date_still_displays_without_an_age_cutoff(source, label):
    result = parse_score(source, label + ": 3 (02/01/20 0900 : " + STAFF + ", RN)")
    assert not result.error
    data = empty_neuro()
    data[source] = result.rows
    assert score_row(label, "3 (02/01/20)") in neuro_rows(data)


@pytest.mark.parametrize("score,expected", [("0", "0"), ("8", "8"), ("9", "9 (H)"), ("32", "32 (H)")])
def test_capd_flag_uses_recorded_total_and_date_stays_last(score, expected):
    rows = parse_capd("CAPD: " + score + " (11/14/26 0900 : " + STAFF + ", RN)").rows
    before = deepcopy(rows)
    assert capd_display_row(rows)["value"] == expected + " (11/14/26)"
    assert rows == before
    validate_capd_rows(rows)


def test_legacy_undated_scores_are_preserved_without_an_invented_date():
    capd = parse_capd("CAPD: 9/32")
    wat = parse_neuro("WAT-1 total score (0-12): [0-3] 1", "l")
    assert capd.rows[0]["value"] == "9"
    assert capd_display_row(capd.rows)["value"] == "9 (H)"
    assert wat.rows[0]["value"] == "[0-3] 1"
    assert wat_display_rows(wat.rows) == wat.rows


def test_legacy_wat_attribution_can_render_safely_without_archive_rejection():
    data = empty_neuro()
    data["l"] = [score_row("WAT-1 total score (0-12)", "3 (11/14/26 0900 : " + STAFF + ", RN)")]
    before = deepcopy(data)
    validate_neuro(data)
    assert score_row("WAT-1", "3 (11/14/26)") in neuro_rows(data)
    assert STAFF not in json.dumps(neuro_rows(data))
    assert data == before


def test_unrecognized_old_wat_prose_is_loadable_but_never_printed_as_a_score():
    data = empty_neuro()
    data["l"] = [score_row("WAT-1: " + STAFF, "Unrecognized value from " + STAFF)]
    validate_neuro(data)
    assert wat_display_rows(data["l"]) == []
    assert STAFF not in json.dumps(neuro_rows(data))
    assert parse_neuro(data["l"][0]["value"], "l").error


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
def test_editor_normalization_preserves_exclusion_and_never_mutates_input(source, label):
    original = [score_row(label, label + ": 3 (11/14/26 0900 : " + STAFF + ", RN)", False)]
    before = deepcopy(original)
    normalized = normalize_score_rows(original, source)
    assert normalized == [score_row(label, "3 (11/14/26)", False)]
    assert original == before
    data = empty_neuro()
    data[source] = normalized
    shown = neuro_rows(data)
    assert "3 (11/14/26)" not in json.dumps(shown)


def test_editor_normalization_preserves_order_and_count_of_existing_wat_rows():
    original = [score_row("WAT-1", "3 (11/13/26 0900 : " + STAFF + ", RN)", False),
                score_row("WAT-1", "1 (11/14/26 0900 : " + STAFF + ", RN)")]
    normalized = normalize_score_rows(original, "l")
    assert normalized == [score_row("WAT-1", "3 (11/13/26)", False),
                          score_row("WAT-1", "1 (11/14/26)")]


def test_shared_stamp_helpers_strip_attribution_and_keep_time_only_for_ordering():
    text = "Target Arousal Level (SBS): SBS -1 (11/14/26 0907 : " + STAFF + ", RN)"
    body, stamp = split_score_stamp(text)
    assert body == "Target Arousal Level (SBS): SBS -1"
    assert stamp == "11/14/2026 09:07"
    assert sanitize_score_line(text) == body + " (11/14/2026 09:07)"
    assert date_label(stamp) == "11/14/26"
    assert score_with_date("-1", stamp) == "-1 (11/14/26)"
    assert date_label("") == ""


def test_latest_helper_preserves_original_rows_and_ignores_excluded_scores():
    rows = [{"value": "2", "recorded_at": "11/14/26 0900", "include": True},
            {"value": "8", "recorded_at": "11/14/26 1000", "include": False}]
    before = deepcopy(rows)
    chosen = latest_score(rows)
    assert chosen == rows[0] and chosen is not rows[0]
    assert rows == before


def test_canonical_capd_editor_value_is_compact_and_validated():
    assert canonical_capd_value("CAPD: Cornell Assessment of Pediatric Delirium Score: 8 (11/14/26 0900 : " + STAFF + ", RN)") == "8 (11/14/26)"
    with pytest.raises(ValueError):
        validate_capd_rows([score_row("CAPD", "8 (11/14/26 0900 : " + STAFF + ", RN)")])


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
def test_later_unassessed_entry_does_not_replace_last_recorded_score(source, label):
    result = parse_score(source, label + ": 3 (11/13/26 0900 : " + STAFF + ", RN)\n" +
                         label + ": Not assessed (11/14/26 0900 : " + STAFF + ", RN)")
    assert not result.error
    assert result.rows[0]["value"] == "3 (11/13/26)"
