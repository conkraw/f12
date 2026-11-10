from pathlib import Path
import pytest
from parser import MAX_PASTE, SECTION_NAMES, parse_smartphrase


def block(key='a', content='1. Example diagnosis (CMS/HCC)', opening=32, closing=32, heading=None):
    return f'{key * opening}\n{heading or SECTION_NAMES[key]}:\n{content}\n{key * closing}\n'


@pytest.mark.parametrize('opening,closing', [(8,8), (8,37), (37,32), (64,100)])
def test_divider_lengths(opening, closing):
    out = parse_smartphrase(block(opening=opening, closing=closing))
    assert out.diagnoses == ['Example diagnosis (CMS/HCC)']
    assert not out.diagnosis_error


def test_full_synthetic_ten_sections():
    text = (Path(__file__).parents[1] / 'examples/synthetic_smartphrase.txt').read_text()
    out = parse_smartphrase(text)
    assert set(out.blocks) == set('abcdefghij')
    assert len(out.diagnoses) == 2
    assert not out.issues


def test_preserves_wording_codes_case_and_duplicates():
    out = parse_smartphrase(block(content='1. Example NAME (CMS/HCC)\n2. Example NAME (CMS/HCC)'))
    assert out.diagnoses == ['Example NAME (CMS/HCC)', 'Example NAME (CMS/HCC)']


def test_wrapped_numbered_diagnoses():
    out = parse_smartphrase(block(content='1. Example diagnosis with\n   wrapped continuation\n2. Second diagnosis'))
    assert out.diagnoses == ['Example diagnosis with wrapped continuation', 'Second diagnosis']


def test_bullets():
    assert parse_smartphrase(block(content='• Example one\n• Example two')).diagnoses == ['Example one','Example two']


def test_plain_lines_preserved():
    assert parse_smartphrase(block(content='Example one\nExample two')).diagnoses == ['Example one','Example two']


@pytest.mark.parametrize('text', ['', '  ', 'Diagnoses:\n1. No delimiters', 'aaaaaaaa\nDiagnoses:\n1. No end', 'aaaaaaa\nDiagnoses:\n1. Too short\naaaaaaa'])
def test_incomplete_rejected(text):
    assert parse_smartphrase(text).diagnosis_error


def test_duplicate_blocks_rejected():
    out = parse_smartphrase(block() + block(content='1. Another patient'))
    assert out.diagnosis_error and 'a' in out.invalid


def test_missing_close_not_swallowed_into_medications():
    out = parse_smartphrase('aaaaaaaa\nDiagnoses:\n1. Example\n' + block('b', 'Drug placeholder'))
    assert out.diagnosis_error
    assert out.blocks['b'].startswith('Medications:')


def test_wrong_heading_inside_a_rejected():
    out = parse_smartphrase(block(content='1. Example\nMedications:\nDo not import'))
    assert out.diagnosis_error


def test_mislabeled_block_rejected():
    assert parse_smartphrase(block(heading='Medications')).diagnosis_error


def test_empty_diagnosis_does_not_erase():
    assert parse_smartphrase(block(content='')).diagnosis_error


def test_vitals_typo_does_not_corrupt_diagnosis():
    text = block() + 'eeeeeeee\nVITALS:\nExample vitals\nceeeeeeeeeeeeeee\n' + block('f', 'Example culture')
    out = parse_smartphrase(text)
    assert out.diagnoses == ['Example diagnosis (CMS/HCC)']
    assert 'e' in out.invalid and out.issues
    assert not out.diagnosis_error


def test_typo_inside_diagnoses_blocks_import():
    assert parse_smartphrase('aaaaaaaa\nDiagnoses:\n1. Example\ncaaaaaaaaa\naaaaaaaa').diagnosis_error


def test_case_spacing_and_windows_newlines():
    text = '  AAAAAAAAA\r\n  DIAGNOSES:\r\n1.\tExample\r\nAAAAAAAA\r\n'
    assert parse_smartphrase(text).diagnoses == ['Example']


def test_outside_text_not_imported():
    out = parse_smartphrase('Ignored source text\n' + block())
    assert out.diagnoses == ['Example diagnosis (CMS/HCC)']
    assert out.issues


def test_message_does_not_echo_source():
    out = parse_smartphrase('aaaaaaaa\nWrong heading:\nPRIVATE_SENTINEL\naaaaaaaa')
    assert 'PRIVATE_SENTINEL' not in str(out.issues) + out.diagnosis_error


def test_length_limit():
    assert parse_smartphrase('x' * (MAX_PASTE + 1)).diagnosis_error
