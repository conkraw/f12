"""Regression tests for section isolation, paired CBC cells, and safe display."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from parser import parse_smartphrase
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, validate_sheet, upgrade_vault
from importing import import_sections
from cbc import parse_cbc, cbc_summary, cbc_cards, validate_cbc
from recurring_orders import parse_orders
from exports import handoff_text, handoff_html, handoff_pdf
from security import generate_key, seal_vault, open_vault
from import_review import diagnostic, review_summary, validate_import_warnings


def wrap(letter, body):
    return letter * 12 + '\n' + body + '\n' + letter * 12


CBC = ('Results from last 7 days\nLab\tUnits\t01/07/26\n0610\t01/06/26\n2305\n'
       'WBC AUTO\tK/uL\t -- \t14.89\nHEMOGLOBIN\tg/dL\t -- \t10.1*\n'
       'HEMOGLOBIN ISTAT\tg/dL\t10.2*\t10.9*\nHEMATOCRIT\t%\t30*\t29.4* | 32*\n'
       'MCV\tfL\t -- \t77.2\nNEUTROS ABS\tK/uL\t -- \t13.07*\nLYMPHS ABS AUTO\tK/uL\t -- \t1.45*')
ORDERS = ('Orders Placed This Encounter\nProcedures\n• Blood culture\n\tPeripheral\n'
          '\tTiming:\tRecurring (Once)\n\tNumber of Occurrences:\t1\n'
          '• XR chest 1 view\n\tTiming:\tRecurring (Daily imaging)\n\tNumber of Occurrences:\t7')


def run(text, sheet=None):
    return import_sections(sheet or new_sheet('P4102'), text, new_vault()['settings'])


@pytest.mark.parametrize('word', ['Peripheral', 'peripheral', 'Brown', 'Mediastinal', 'Aerobic', 'anaerobic',
                                   'Preliminary', 'Enteral', 'Respiratory', 'Incontinence'])
def test_normal_order_words_not_dividers(word):
    parsed = parse_smartphrase(wrap('r', ORDERS.replace('Peripheral', word)))
    assert 'r' not in parsed.invalid
    assert not any('Malformed divider' in item for item in parsed.issues)
    result = run(wrap('r', ORDERS.replace('Peripheral', word)))
    assert not result.errors
    assert len(result.sheet['recurring_orders']['rows']) == 1


@pytest.mark.parametrize('typo', ['crrrrrrrrrrr', 'rrrrrrrcrrrrr', 'rrrrrrrrrrrc', 'eaaaaaaaaaa'])
def test_genuinely_repeated_malformed_divider_still_flags_section(typo):
    source = wrap('a', 'Diagnoses:\n1. Synthetic') + '\n' + wrap('r', ORDERS + '\n' + typo)
    out = run(source)
    assert out.sheet['fields']['Diagnoses'] == 'Synthetic'
    assert 'r' in out.skipped and 'r' in out.sheet['import_warnings']


def test_exact_pipe_structure_retained_but_neither_result_is_chosen():
    parsed = parse_cbc(CBC)
    assert not parsed.error
    problem = next(row for row in parsed.data['rows'] if '|' in row['value'])
    assert problem['value'] == '29.4* | 32*' and not problem['include']
    assert problem['date'] == '01/06/26 2305'
    cards = cbc_cards({'rows': [], 'notes': []}, parsed.data)
    assert cards[0]['rows']['HGB']['value'] == '10.1*'
    assert 'HCT' not in cards[0]['rows']
    assert cards[0]['rows']['WBC']['value'] == '14.89'
    assert parsed.diagnostics[0]['field'] == 'HCT'
    validate_cbc(parsed.data)
    problem['include'] = True
    with pytest.raises(ValueError):
        validate_cbc(parsed.data)
    problem['value'] = '29.4*'  # A deliberate, verified editor correction.
    validate_cbc(parsed.data)


@pytest.mark.parametrize('value', ['29.4* | 32*', '29.4 | 32 | 31', '29.4 (L) | 32 (L)'])
def test_numeric_multi_value_cells_are_never_min_or_max(value):
    out = parse_cbc(CBC.replace('29.4* | 32*', value))
    assert not out.error and out.diagnostics
    assert next(r for r in out.data['rows'] if r['value'] == value)['include'] is False


def test_bad_cell_preserves_other_cells_and_does_not_echo_content_in_diagnostics():
    text = CBC.replace('29.4* | 32*', 'PRIVATE_VALUE_SENTINEL')
    result = run(wrap('q', text) + '\n' + wrap('a', 'Diagnoses:\n1. Synthetic'))
    assert not result.errors and result.sheet is not None
    assert result.sheet['fields']['Diagnoses'] == 'Synthetic'
    assert 'PRIVATE_VALUE_SENTINEL' not in json.dumps(result.diagnostics)
    assert 'PRIVATE_VALUE_SENTINEL' not in json.dumps(result.sheet)
    assert 'q' in result.sheet['import_warnings']


def test_short_row_skipped_instead_of_shifting_columns():
    result = parse_cbc(CBC.replace('WBC AUTO\tK/uL\t -- \t14.89', 'WBC AUTO\tK/uL\t14.89'))
    assert not result.error
    assert not any(row['component'] == 'WBC AUTO' for row in result.data['rows'])
    assert any(row['component'] == 'HEMOGLOBIN' for row in result.data['rows'])


def test_valid_sections_applied_while_failed_r_keeps_prior_data_hidden():
    sheet = new_sheet('P4102')
    sheet['recurring_orders'] = parse_orders(ORDERS).data
    before = deepcopy(sheet)
    result = run(wrap('a', 'Diagnoses:\n1. New synthetic') + '\n' + wrap('r', ORDERS.replace('Occurrences:\t7', 'Occurrences:\tBAD')) + '\n' + wrap('e', 'VITALS:\nHeart Rate: 100'), sheet)
    assert result.errors and result.imported and result.sheet is not None
    assert sheet == before
    assert result.sheet['fields']['Diagnoses'] == 'New synthetic'
    assert result.sheet['recurring_orders'] == before['recurring_orders']
    fields = fields_with_medications(result.sheet)
    assert 'Daily imaging' not in fields['Labs']
    assert 'Orders not imported' in fields['Labs']
    assert 'Heart Rate: 100' in fields['Cardiovascular']
    assert 'r' in result.sheet['import_warnings']


def test_one_failing_medication_section_does_not_apply_partial_order_list():
    sheet = new_sheet('P4102')
    result = run(wrap('a', 'Diagnoses:\n1. Synthetic') + '\n' + wrap('b', 'Medications:\n• cannot separate this order'), sheet)
    assert result.sheet['fields']['Diagnoses'] == 'Synthetic'
    assert result.sheet['medications'] == sheet['medications']
    assert result.skipped == ['b']


def test_exception_is_isolated_and_raw_exception_never_journaled(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('SECRET_PATIENT_AND_TOKEN')
    monkeypatch.setattr('importing.parse_orders', fail)
    result = run(wrap('r', ORDERS) + '\n' + wrap('a', 'Diagnoses:\n1. Synthetic'))
    assert result.sheet['fields']['Diagnoses'] == 'Synthetic'
    assert 'r' in result.skipped
    assert 'SECRET_PATIENT' not in json.dumps(result.diagnostics) + str(result.errors)


def test_success_replaces_only_warning_for_reimported_section():
    sheet = run(wrap('q', CBC) + '\n' + wrap('r', ORDERS.replace('Occurrences:\t7', 'Occurrences:\tBAD'))).sheet
    assert set(sheet['import_warnings']) == {'q', 'r'}
    next_result = run(wrap('r', ORDERS), sheet)
    assert set(next_result.sheet['import_warnings']) == {'q'}
    assert 'Daily imaging' in fields_with_medications(next_result.sheet)['Labs']
    cleared = run(wrap('q', ''), next_result.sheet).sheet
    assert not cleared['import_warnings'] and not cleared['cbc']['rows']


def test_omitted_sections_keep_persistent_review_flags():
    sheet = run(wrap('q', CBC)).sheet
    out = run(wrap('e', 'VITALS:\nTemp: 37 C'), sheet)
    assert out.sheet['import_warnings'] == sheet['import_warnings']
    assert out.sheet['cbc'] == sheet['cbc']


def test_multiple_patient_sections_still_block_document():
    result = run(wrap('a', 'Diagnoses:\n1. First') + '\n' + wrap('a', 'Diagnoses:\n1. Second') + '\n' + wrap('r', ORDERS))
    assert result.sheet is None and result.errors
    assert result.diagnostics[0]['action'] == 'nothing_changed'


def test_flags_and_rejected_cbc_cells_survive_encrypted_save():
    sheet = run(wrap('q', CBC)).sheet
    key = generate_key()
    vault = save_sheet_in(new_vault(), sheet)
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == vault
    assert restored['rooms']['P4102']['import_warnings']


def test_schema15_migration_preserves_every_old_field():
    old = new_vault()
    old['schema'] = 15;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None)
    old['rooms']['P4102'] = new_sheet('P4102')
    old['rooms']['P4102'].pop("feeds", None);old['rooms']['P4102'].pop("devices", None);old['rooms']['P4102'].pop("neuro_devices", None);old['rooms']['P4102'].pop("pacemaker", None);old['rooms']['P4102'].pop("diet", None);old['rooms']['P4102'].pop('import_warnings')
    old['rooms']['P4102']['fields']['FEN / GI'] = 'Keep all notes'
    before = deepcopy(old)
    new = upgrade_vault(old)
    assert old == before and new['schema'] ==32
    assert new['settings'] == dict(old['settings'], medication_groups=[])
    assert new['rooms']['P4102'] == dict(old['rooms']['P4102'], import_warnings={}, feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)


def test_warnings_stay_in_app_not_html_text_pdf_or_continuation_pages():
    sheet = run(wrap('q', CBC) + '\n' + wrap('r', ORDERS.replace('Occurrences:\t7', 'Occurrences:\tBAD'))).sheet
    sheet['fields']['Diagnoses'] = 'Synthetic recovery preview'
    for source in (handoff_text(sheet), handoff_html(sheet)):
        assert 'IMPORT REVIEW' not in source and 'Orders: orders skipped' not in source
        assert sheet['import_warnings']  # Diagnostics remain available in the app.
        assert '29.4* | 32*' not in source
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    assert 'IMPORT REVIEW' not in pdf.pages[0].extract_text()
    assert '29.4' not in ''.join(p.extract_text() for p in pdf.pages)
    sheet['fields']['Other Medications'] = '\n'.join('Extra example medication ' + str(i) for i in range(150))
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    assert len(pdf.pages) > 1
    assert all('IMPORT REVIEW' not in p.extract_text() for p in pdf.pages)


@pytest.mark.parametrize('change', [lambda x:x.update(room='P4102'), lambda x:x.update(code='PRIVATE'),
 lambda x:x.update(field='PRIVATE'), lambda x:x.update(line='MRN'), lambda x:x.update(column=-1)])
def test_diagnostic_schema_cannot_receive_patient_fields(change):
    from import_review import validate_diagnostic
    value = diagnostic('q', 'cbc_multiple_values', field='HCT', action='cell_omitted')
    change(value)
    with pytest.raises((ValueError, TypeError)):
        validate_diagnostic(value)
