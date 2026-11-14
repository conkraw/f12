"""AC bowel-status regressions. Synthetic snippets, no real patient fixtures."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import fitz
import pytest
from bowel_movements import parse_bowel_movement, bowel_movement_text, validate_bowel_movement
from importing import import_sections
from parser import parse_smartphrase
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, save_sheet_in, upgrade_vault
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from security import generate_key, seal_vault, open_vault
from batching import available_handoffs
from categories import save_category, apply_category_rules
from empty_groups import refresh_empty_group_layout
from fen_gi import fen_gi_body
from test_rooms_infusions import med
from test_callbacks import app, open_room
from test_ui_smoke import equip


def wrap(key, body):
    return key * 16 + '\n' + body + '\n' + key * 16


def imported(body, sheet=None, other=''):
    result = import_sections(sheet or new_sheet('P4102'), wrap('ac', body) + '\n' + other, new_vault()['settings'])
    assert result.sheet is not None, result.errors
    return result


@pytest.mark.parametrize('amount', ['Small', 'Medium', 'Moderate', 'Large', 'Smear', 'Scant', 'Trace', 'small', 'LARGE', 'Large (documented)', '1', '1 x', '25 mL', '10 g'])
def test_positive_stool_amount(amount):
    parsed = parse_bowel_movement('Stool Amount: ' + amount)
    assert not parsed.error and parsed.data == {'documented': True}


@pytest.mark.parametrize('label', ['Diaper Weight Mixed Urine/Stool (g)', 'Diaper Weight with Stool (g)', 'diaper weight mixed urine / stool (g)'])
@pytest.mark.parametrize('value', ['25 g', '51 g', '123 g', '69 g', '337 g', '72 g', '67 g', '1', '.5 g', '1,025.5 g'])
def test_positive_stool_containing_diapers(label, value):
    parsed = parse_bowel_movement(label + ': ' + value)
    assert not parsed.error and parsed.data == {'documented': True}


@pytest.mark.parametrize('body', ['', '  \n\t\n', 'No data recorded', 'Stool Amount:', 'Stool Amount: None',
    'Stool Amount: 0', 'Stool Amount: --', 'Stool Amount: N/A', 'Stool Amount: Not documented',
    'Diaper Weight Mixed Urine/Stool (g): 0 g', 'Diaper Weight with Stool (g): 0.0 g',
    'Diaper Weight Mixed Urine/Stool (g):', 'Diaper Weight with Stool (g): Unknown'])
def test_empty_and_zero_are_no(body):
    result = imported(body)
    assert not result.errors and result.sheet['bowel_movement'] == {'documented': False}
    assert bowel_movement_text(result.sheet) == 'Last BM (24 hours): No'


def test_multiple_positive_signals_collapse_to_one_yes_with_no_details():
    body = 'Diaper Weight Mixed Urine/Stool (g): 123 g\nDiaper Weight with Stool (g): 69 g\nStool Amount: Small'
    result = imported(body)
    assert not result.errors
    text = handoff_text(result.sheet)
    assert text.count('Last BM (24 hours): Yes') == 1
    for private_detail in ['123 g', '69 g', 'Stool Amount', 'Small', 'Mixed Urine/Stool']:
        assert private_detail not in text and private_detail not in json.dumps(result.sheet)
    assert text.index('Bowel Regimen') < text.index('Last BM (24 hours): Yes') < text.index('Diuretics')


@pytest.mark.parametrize('body', ['Stool Amount: -1', 'Diaper Weight Mixed Urine/Stool (g): -5 g',
    'Stool Amount: Large? unknown', 'Diaper Weight Mixed Urine/Stool (g): not readable',
    'Urine: 50', 'Other: 51', 'Diaper Weight with Urine (g): 20 g', 'Stool Amount: <script>Large</script>'])
def test_unreadable_data_is_warning_not_false_no_or_stale_yes(body):
    prior = imported('Stool Amount: Large').sheet
    result = imported(body, prior)
    assert result.errors and 'ac' in result.sheet['import_warnings']
    assert result.sheet['bowel_movement'] is None
    assert bowel_movement_text(result.sheet) == ''
    result.sheet['import_warnings'].clear()
    assert 'Last BM' not in handoff_text(result.sheet)


def test_one_positive_signal_is_enough_even_if_a_separate_field_is_empty_or_unknown():
    result = imported('Stool Amount: Unknown\nDiaper Weight with Stool (g): 20 g')
    assert not result.errors and bowel_movement_text(result.sheet).endswith('Yes')


def test_whitespace_colon_and_windows_line_endings():
    result = imported('Stool Amount\uff1a\tLarge\r\nDiaper Weight with Stool (g):\u00a069 g')
    assert not result.errors and bowel_movement_text(result.sheet).endswith('Yes')


@pytest.mark.parametrize('marker', ['ac' * 4, 'AC' * 16, 'ac' * 15 + 'a'])
def test_paired_ac_divider_variants(marker):
    result = import_sections(new_sheet('P4102'), marker + '\nStool Amount: Large\n' + marker, new_vault()['settings'])
    assert not result.errors and bowel_movement_text(result.sheet).endswith('Yes')


def test_absent_ac_does_not_infer_from_generic_other_or_feeds_or_medication():
    outside = (wrap('h', 'INTAKE/OUTPUT:\nI/O this shift:\nOut: 70 [Other:70]\nWeight: 5 kg') + '\n'
               + wrap('ab', 'Dietary Orders:\nDiet Orders\nBreast Milk (print labels) starting at 01/05 0800'))
    result = imported('', other=outside)
    assert not result.errors and bowel_movement_text(result.sheet).endswith('No')
    # A matching positive field outside AC must never be borrowed.
    text = wrap('ac', '') + '\nStool Amount: Large'
    result = import_sections(new_sheet('P4102'), text, new_vault()['settings'])
    assert not result.errors and bowel_movement_text(result.sheet).endswith('No')


def test_bowel_medication_alone_cannot_establish_yes():
    result = imported('')
    result.sheet['medications'] = [med('polyethylene glycol powder', '8.5 g', 'Oral', 'Daily')]
    assert 'Last BM (24 hours): No' in handoff_text(result.sheet)


def test_reimport_blank_resets_yes_without_duplicate_lines():
    old = imported('Stool Amount: Large').sheet
    first = imported('Stool Amount: Small', old)
    result = imported('', first.sheet)
    assert not result.errors
    assert handoff_text(result.sheet).count('Last BM (24 hours): No') == 1
    assert 'Last BM (24 hours): Yes' not in handoff_text(result.sheet)
    assert old['bowel_movement'] == {'documented': True}


@pytest.mark.parametrize('key,body', [('h', 'INTAKE/OUTPUT:'), ('s', '')])
def test_new_io_snapshot_without_ac_clears_stale_bm(key, body):
    old = imported('Stool Amount: Large').sheet
    result = import_sections(old, wrap(key, body), new_vault()['settings'])
    assert not result.errors and result.sheet.get('bowel_movement') is None
    assert 'Last BM' not in handoff_text(result.sheet)


def test_limited_unrelated_update_keeps_existing_bm_snapshot():
    old = imported('Stool Amount: Small').sheet
    result = import_sections(old, wrap('a', 'Diagnoses:\n1. Synthetic diagnosis'), new_vault()['settings'])
    assert not result.errors and result.sheet['bowel_movement'] == old['bowel_movement']


@pytest.mark.parametrize('text', [wrap('ac', '') + '\n' + wrap('ac', 'Stool Amount: Large'),
    wrap('a', 'Diagnoses:\n1. Synthetic one') + '\n' + wrap('a', 'Diagnoses:\n1. Synthetic two')])
def test_repeated_patient_sections_rejected(text):
    old = imported('Stool Amount: Large').sheet
    result = import_sections(old, text, new_vault()['settings'])
    assert result.errors and result.sheet is None


@pytest.mark.parametrize('text', ['ac' * 16 + '\nStool Amount: Large',
    ('ac' * 16) + '\nStool Amount: Large\n' + ('ac' * 15) + 'ad'])
def test_broken_ac_boundaries_clear_old_status(text):
    old = imported('Stool Amount: Large').sheet
    result = import_sections(old, text, new_vault()['settings'])
    assert result.errors and result.sheet['bowel_movement'] is None


def test_ac_does_not_break_z_or_ab_and_cannot_hide_other_headers():
    text = (wrap('z', 'No results found for this or any previous visit from the past 365 days.') + '\n'
            + wrap('ac', 'Stool Amount: Large'))
    parsed = parse_smartphrase(text)
    assert not parsed.invalid and set(parsed.blocks) == {'z', 'ac'}
    bad = parse_smartphrase(wrap('ac', 'VITALS:\nTemp: 37'))
    assert 'ac' in bad.invalid


@pytest.mark.parametrize('value', [True, False, 'Yes', {}, {'documented': 1}, {'documented': 'No'}, {'documented': True, 'raw': 'private'}])
def test_strict_snapshot_validation(value):
    with pytest.raises(ValueError):
        validate_bowel_movement(value)


def test_old_archives_and_encrypted_round_trip():
    old = new_vault()
    old_sheet = new_sheet('P4102')
    assert 'bowel_movement' not in old_sheet
    assert upgrade_vault(old) == old
    for value in ['Stool Amount: Large', '']:
        sheet = imported(value).sheet
        key = generate_key()
        vault = save_sheet_in(new_vault(), sheet)
        restored = open_vault(seal_vault(vault, key), key)['rooms']['P4102']
        assert restored['bowel_movement'] == sheet['bowel_movement']
        assert bowel_movement_text(restored) == bowel_movement_text(sheet)


def test_bowel_only_handoff_in_print_all():
    sheet = imported('').sheet
    assert 'P4102' in available_handoffs(new_vault(), {'P4102': sheet})


@pytest.mark.parametrize('signal,status', [('Stool Amount: Large', 'Yes'), ('', 'No')])
def test_bm_in_plain_html_and_pdf_is_not_bold_and_under_bowel(signal, status):
    sheet = imported(signal).sheet
    label = 'Last BM (24 hours): ' + status
    html = handoff_html(sheet)
    assert label in html and '<b>Last BM' not in html and '<strong>Last BM' not in html
    assert html.index('Bowel Regimen') < html.index(label)
    for payload in [handoff_pdf(sheet), handoffs_pdf([sheet])]:
        doc = fitz.open(stream=payload, filetype='pdf')
        text = '\n'.join(page.get_text() for page in doc)
        assert label in text
        spans = [span for page in doc for block in page.get_text('dict')['blocks']
                 if 'lines' in block for line in block['lines'] for span in line['spans']
                 if 'Last BM' in span['text']]
        assert spans and all(not (span['flags'] & 16) for span in spans)


def test_visible_bowel_medications_stay_above_observation():
    sheet = imported('Stool Amount: Small').sheet
    sheet['medications'] = [med('polyethylene glycol synthetic powder', '8.5 g', 'Oral', 'Daily')]
    text = fields_with_medications(sheet)['FEN / GI']
    assert text.index('Bowel Regimen') < text.index('polyethylene glycol') < text.index('Last BM')
    assert text.count('polyethylene glycol') == 1 and text.count('Last BM') == 1


def test_custom_bowel_category_position_preserved():
    settings = new_vault()['settings']
    settings = save_category(settings, 'GI Support', 'FEN / GI', ident='custom:gi')
    settings = save_category(settings, 'Bowel Care', 'FEN / GI', parent='custom:gi', ident='gi:bowel')
    sheet = imported('Stool Amount: Large').sheet
    refresh_empty_group_layout(sheet, settings)
    text = fields_with_medications(sheet)['FEN / GI']
    assert text.index('GI Support') < text.index('Bowel Care') < text.index('Last BM')
    assert text.count('Last BM') == 1


def test_ui_import_resets_widgets_and_includes_bm(app, monkeypatch):
    open_room(app)
    app.st.session_state['paste'] = wrap('ac', 'Stool Amount: Large')
    app.create_handoff()
    sheet = app.st.session_state['drafts']['P4102']
    assert sheet['bowel_movement'] == {'documented': True}
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data, bytes) and data.startswith(b'%PDF') for _, data in downloads)
