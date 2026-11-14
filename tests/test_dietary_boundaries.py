"""Synthetic boundary checks for the alternating AB dietary section."""
import pytest

from parser import SECTION_NAMES, parse_smartphrase


DIAGNOSES = "aaaaaaaa\nDiagnoses:\n1. Synthetic example\naaaaaaaa\n"
DIETARY = """Dietary Orders:
Dietary Orders (From admission, onward)
Start\tOrdered
01/04/26 0800
Pediatric diet Regular Diet effective now
Question: Diet type: Answer: Regular
Diet Orders
Pediatric diet Regular: General starting at 01/04 0800"""


def block(marker, body, close=None):
    return marker + "\n" + body + "\n" + (close or marker) + "\n"


@pytest.mark.parametrize("marker", ["abababab", "ababababa", "ab" * 16,
                                    "ab" * 16 + "a", "AB" * 14 + "A"])
def test_alternating_ab_markers_have_their_own_section(marker):
    parsed = parse_smartphrase(DIAGNOSES + block(marker, DIETARY))
    assert set(parsed.blocks) == {"a", "ab"}
    assert not parsed.invalid and not parsed.issues and not parsed.diagnosis_error
    assert parsed.blocks["ab"] == DIETARY
    assert SECTION_NAMES["ab"] == "Dietary Orders"


@pytest.mark.parametrize("opening,closing", [("abababab", "ab" * 20 + "a"),
                                            ("ab" * 15 + "a", "ABABABAB"),
                                            ("Ab" * 10, "aB" * 12 + "a")])
def test_ab_marker_lengths_case_and_final_a_can_differ(opening, closing):
    parsed = parse_smartphrase(DIAGNOSES + block(opening, DIETARY, closing))
    assert not parsed.invalid and parsed.blocks["ab"] == DIETARY


def test_x_and_ab_are_distinct_sections_and_both_diet_headings_are_allowed():
    source = DIAGNOSES + block("xxxxxxxx", "Diet:\nDiet Orders\nPediatric diet Regular")
    source += block("ababababa", DIETARY)
    parsed = parse_smartphrase(source)
    assert set(parsed.blocks) == {"a", "x", "ab"}
    assert not parsed.invalid and not parsed.issues


@pytest.mark.parametrize("heading", ["Dietary Orders:", "Dietary Orders (From admission, onward)",
                                     "Dietary orders (from admission,onward):", "DIETARY  ORDERS：",
                                     "Diet Orders", "Diet:"])
def test_supported_ab_headings(heading):
    parsed = parse_smartphrase(DIAGNOSES + block("ababababa", heading + "\nNone"))
    assert not parsed.invalid and not parsed.issues


def test_existing_x_accepts_the_new_detailed_dietary_headings():
    parsed = parse_smartphrase(DIAGNOSES + block("xxxxxxxx", DIETARY))
    assert set(parsed.blocks) == {"a", "x"}
    assert not parsed.invalid and not parsed.issues


@pytest.mark.parametrize("body", ["", "Dietary Orders:\nDiet Orders\nNone"])
def test_explicit_empty_ab_is_a_valid_snapshot(body):
    parsed = parse_smartphrase(DIAGNOSES + block("abababab", body))
    assert "ab" in parsed.blocks and "ab" not in parsed.invalid


def test_table_cells_and_instruction_text_are_preserved():
    body = """Dietary Orders:
Question\tAnswer\tComment
Diet:\tPediatric Tube Feeding\t
Formula:\tSynthetic Formula\t
Route:\tGastrostomy tube\t
Infusion time (hours)\t18 hours\t
Comments: a phrase with abababab inside is ordinary text.
Diet Orders
Infant tube feeding Pediatric Tube Feeding; Synthetic Formula; Continuous Feeds; Gastrostomy tube; 18 hours; 32; 576; No Additives"""
    parsed = parse_smartphrase(DIAGNOSES + block("ababababa", body))
    assert not parsed.invalid and parsed.blocks["ab"] == body


def test_ecg_before_dietary_orders_stays_separate():
    ecg = "ECG 12 lead 01/04/2026\nQTc Calculation(Bazett): 438 ms"
    parsed = parse_smartphrase(DIAGNOSES + block("zzzzzzzz", ecg) + block("ababababa", DIETARY))
    assert not parsed.invalid and not parsed.issues
    assert parsed.blocks["z"] == ecg and parsed.blocks["ab"] == DIETARY


@pytest.mark.parametrize("heading", ["Medications:", "VITALS:", "ECG 12 lead 01/04/2026", "Diagnoses:"])
def test_unrelated_heading_inside_ab_still_invalidates_it(heading):
    parsed = parse_smartphrase(DIAGNOSES + block("ababababa", DIETARY + "\n" + heading))
    assert parsed.invalid == {"ab"}
    assert parsed.diagnoses == ["Synthetic example"] and not parsed.diagnosis_error
    assert any("Another section heading" in item for item in parsed.issues)


def test_ab_with_the_wrong_first_heading_is_rejected():
    parsed = parse_smartphrase(DIAGNOSES + block("ababababa", "Medications:\nSynthetic data"))
    assert parsed.invalid == {"ab"}
    assert any("matching heading" in item for item in parsed.issues)


@pytest.mark.parametrize("typo", ["ababababx", "abaxabababab", "ababababababx", "xbababababab"])
def test_near_ab_marker_is_flagged_not_repaired_or_ingested(typo):
    parsed = parse_smartphrase(DIAGNOSES + block("ababababa", DIETARY + "\n" + typo))
    assert parsed.invalid == {"ab"}
    assert typo not in parsed.blocks["ab"]
    assert any("Malformed divider" in item for item in parsed.issues)
    assert parsed.diagnoses == ["Synthetic example"]


def test_two_malformed_ab_boundaries_do_not_silently_omit_the_section():
    parsed = parse_smartphrase(DIAGNOSES + block("ababababx", DIETARY))
    assert "ab" in parsed.invalid and "ab" not in parsed.blocks


def test_missing_ab_close_does_not_consume_a_later_ecg():
    source = DIAGNOSES + "ababababa\n" + DIETARY + "\n"
    source += block("zzzzzzzz", "ECG 12 lead 01/04/2026\nQTc Calculation(Bazett): 438 ms")
    parsed = parse_smartphrase(source)
    assert parsed.invalid == {"ab"}
    assert "z" in parsed.blocks and "z" not in parsed.invalid


def test_missing_ab_close_at_end_is_invalid():
    parsed = parse_smartphrase(DIAGNOSES + "abababab\n" + DIETARY)
    assert parsed.invalid == {"ab"}
    assert any("missing its closing divider at the end" in item for item in parsed.issues)


def test_x_and_ab_cannot_close_each_other():
    parsed = parse_smartphrase(DIAGNOSES + block("xxxxxxxx", DIETARY, "ababababa"))
    assert {"x", "ab"}.issubset(parsed.invalid)


def test_duplicate_ab_sections_keep_the_document_rejection_signal():
    source = DIAGNOSES + block("ababababa", DIETARY) + block("abababab", DIETARY)
    parsed = parse_smartphrase(source)
    assert parsed.invalid == {"ab"}
    assert any(item.startswith("More than one Dietary Orders block") for item in parsed.issues)


@pytest.mark.parametrize("marker", ["abababa", "babababa", "acacacac", "bcbcbcbc"])
def test_other_alternating_strings_are_not_new_supported_dividers(marker):
    parsed = parse_smartphrase(DIAGNOSES + block(marker, DIETARY))
    assert "ab" not in parsed.blocks
    assert set(parsed.blocks) == {"a"}


def test_case_whitespace_and_windows_newlines():
    source = DIAGNOSES + block("  ABABABABA  ", DIETARY)
    parsed = parse_smartphrase(source.replace("\n", "\r\n"))
    assert not parsed.invalid and parsed.blocks["ab"] == DIETARY


def test_boundary_errors_do_not_echo_dietary_contents():
    parsed = parse_smartphrase(DIAGNOSES + "ababababa\nDietary Orders:\nPRIVATE_DIETARY_SENTINEL")
    assert "ab" in parsed.invalid
    assert "PRIVATE_DIETARY_SENTINEL" not in str(parsed.issues) + parsed.diagnosis_error


@pytest.mark.parametrize("key", list("abcdefghijklmnopqrstuvwxyz"))
def test_original_repeated_letter_sections_are_still_recognized(key):
    body = SECTION_NAMES[key] + ":\n" + ("1. Synthetic example" if key == "a" else "")
    parsed = parse_smartphrase(("" if key == "a" else DIAGNOSES) + block(key * 12, body))
    assert key in parsed.blocks and key not in parsed.invalid
