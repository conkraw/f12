"""Regression for valid H totals lost by an empty S block. Synthetic source only."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import pytest
import fitz
from io_sources import select_balance_source
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in
from fluid_balance import balance_heading, balance_text, parse_balance
from current_shift import current_shift_text, parse_current_shift
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_current_shift import source


def wrap(key, body):
    return key * 16 + '\n' + body + '\n' + key * 16


def run(h=None, s=None, old=None, ac=None):
    text = '\n'.join(wrap(k, v) for k, v in [('h', h), ('s', s), ('ac', ac)] if v is not None)
    return import_sections(old or new_sheet('P4102'), text, new_vault()['settings'])


def expected(h):
    return parse_balance(h.split('IO Current Shift:', 1)[0]).data


@pytest.mark.parametrize('s', [None, '', ' ', 'INTAKE/OUTPUT:', 'Fluid balance:', 'None', 'No results found', 'Intake/Output:\nIntake\nOutput\nNet', 'Intake --\nOutput --\nNet --'])
def test_explicit_h_24_hour_summary_survives_empty_or_omitted_s(s):
    h = source()
    result = run(h, s)
    assert not result.errors and result.sheet['intake_output'] == expected(h)
    assert result.sheet['current_shift'] == parse_current_shift(h).data
    assert fields_with_medications(result.sheet)['FEN / GI'].startswith('Intake/Output (6a-6a):')


def test_h_replaces_previous_totals_from_same_source_not_stale_values():
    old = run(source(), '').sheet
    updated = source(stamp='01/06/2026 0630').replace('1250 ml', '1499.75 ml').replace('Net 150 ml', 'Net 399.75 ml')
    result = run(updated, '', old=old)
    assert not result.errors and result.sheet['intake_output'] == expected(updated)
    assert old['intake_output']['intake'] == '1250 ml'


def test_populated_s_remains_authoritative_and_is_not_added_to_h():
    h = source()
    s = h.split('IO Current Shift:')[0].replace('1250 ml', '900 ml').replace('Net 150 ml', 'Net -200 ml')
    result = run(h, s)
    assert not result.errors and result.sheet['intake_output'] == parse_balance(s).data
    assert result.sheet['current_shift'] == parse_current_shift(h).data


def test_current_shift_and_totals_parse_independently_on_bad_shift():
    old = run(source(), '').sheet
    h = source(out='Urine:BAD')
    result = run(h, '', old=old)
    assert result.errors and 'h' in result.skipped and 's' not in result.skipped
    assert result.sheet['intake_output'] == expected(h)
    assert result.sheet['current_shift'] is None
    assert 'Intake: 1250 ml' in handoff_text(result.sheet)


def test_bad_h_totals_do_not_erase_valid_shift():
    old = run(source(), '').sheet
    result = run(source().replace('Intake 1250 ml', 'Intake unreadable'), '', old=old)
    assert result.errors and 's' in result.skipped and 'h' not in result.skipped
    assert result.sheet['intake_output'] == old['intake_output']
    assert 'UOP: 1.30' in current_shift_text(result.sheet)


def test_invalid_s_is_not_silently_replaced_by_valid_h():
    old = run(source(), '').sheet
    result = run(source(), 'Intake/Output:\nIntake BAD', old=old)
    assert result.errors and 's' in result.skipped
    assert result.sheet['intake_output'] == old['intake_output']


@pytest.mark.parametrize('body', ['INTAKE/OUTPUT:\nIntake 9999 ml\nOutput 1 ml\nNet 9998 ml',
    'INTAKE/OUTPUT:\nI/O last 3 completed shifts:\nIn: 900\nOut: 100 [Urine:100]\nWeight: 20 kg',
    source().replace('(Last 24 hours)', '(Last 12 hours)')])
def test_h_without_explicit_24h_summary_is_not_promoted_to_day_totals(body):
    old = run(source(), '').sheet
    result = run(body, old=old)
    assert result.sheet['intake_output'] == old['intake_output']


def test_last_three_shifts_section_after_24h_summary_is_not_consumed():
    h = source().replace('IO Current Shift:', 'I/O last 3 completed shifts:\nIn: 8888\nOut: 7777 [Urine:7777]\nWeight: 10 kg\nIO Current Shift:')
    result = run(h, '')
    assert not result.errors and result.sheet['intake_output'] == expected(source())


def test_summary_missing_values_are_not_filled_from_current_shift():
    h = source().replace('Intake 1250 ml\n', '').replace('Net 150 ml\n', '')
    result = run(h, '')
    assert not result.errors
    assert result.sheet['intake_output']['intake'] == '' and result.sheet['intake_output']['net'] == ''
    assert 'Intake: --' in balance_text(result.sheet['intake_output'])
    assert 'Net: --' in balance_text(result.sheet['intake_output'])


def test_no_net_recalculation_even_when_source_values_disagree():
    h = source().replace('Net 150 ml', 'Net 99.99 ml')
    result = run(h, '')
    assert not result.errors and result.sheet['intake_output']['net'] == '99.99 ml'


def test_source_clock_last_filed_and_legacy_heading_preserved():
    h = source(stamp='01/05/2026 1712')
    result = run(h, '')
    assert result.sheet['intake_output']['as_of'] == '01/05/2026 1712'
    assert result.sheet['intake_output']['last_filed'] == '01/05/2026 0400'
    assert balance_heading(result.sheet['intake_output']) == 'Intake/Output (5p-5p)'
    assert current_shift_text(result.sheet).startswith('Current Shift (7am - 5:12pm)')


def test_empty_s_alone_still_clears_legacy_snapshot():
    old = run(source(), '').sheet
    result = run(s='', old=old)
    assert not result.errors and result.sheet['intake_output'] is None


def test_valid_h_does_not_bypass_bad_s_boundaries():
    text = wrap('h', source()) + '\n' + 's' * 16 + '\nIntake 999 ml'
    result = import_sections(new_sheet('P4102'), text, new_vault()['settings'])
    assert result.errors and result.sheet['intake_output'] is None and 's' in result.skipped


def test_bad_h_boundary_does_not_let_empty_s_clear_retained_totals():
    old = run(source(), '').sheet
    text = 'h' * 16 + '\n' + source() + '\n' + wrap('s', '')
    result = import_sections(old, text, new_vault()['settings'])
    assert result.errors and result.sheet['intake_output'] == old['intake_output']
    assert {'h', 's'} <= set(result.skipped)


def test_multiple_h_summaries_rejected_without_overwriting_day_total():
    old = run(source(), '').sheet
    h = source().replace('IO Current Shift:', 'Intake/Output Summary (Last 24 hours) at 01/05/2026 0610\nIO Current Shift:')
    result = run(h, '', old=old)
    assert result.errors and {'h', 's'} <= set(result.skipped)
    assert result.sheet['intake_output'] == old['intake_output']


def test_all_formats_include_totals_shift_and_bm_once():
    result = run(source(), '', ac='Diaper Weight Mixed Urine/Stool (g): 51 g')
    assert not result.errors
    sheet = result.sheet
    for text, bm in [(handoff_text(sheet), 'Last BM (24 Hours): Yes'),
                     (handoff_html(sheet), '<b>Last BM (24 Hours):</b> Yes')]:
        assert text.count('Intake/Output (6a-6a)') == 1
        assert text.count('Current Shift (7pm - 6:30am)') == 1
        assert text.count(bm) == 1
        assert text.index('Intake/Output') < text.index('Current Shift') < text.index('Bowel Regimen') < text.index('Last BM')
    for payload in [handoff_pdf(sheet), handoffs_pdf([sheet])]:
        doc = fitz.open(stream=payload, filetype='pdf')
        text = '\n'.join(p.get_text() for p in doc)
        assert 'Intake: 1250 ml' in text and 'Output: 1100 ml' in text and 'Net: 150 ml' in text
        assert 'Current Shift' in text and 'Last BM (24 Hours): Yes' in text


def test_dosing_weight_math_unchanged_and_shift_uses_own_weight():
    old = new_sheet('P4102')
    old['dosing_weight'] = '5 kg'
    sheet = run(source(weight='20 kg'), '', old=old).sheet
    assert 'In: 1250 ml (250 mL/kg)' in fields_with_medications(sheet)['FEN / GI']
    assert 'UOP: 1.30 mL/kg/hr' in current_shift_text(sheet)


def test_encrypted_save_reload_preserves_both_and_never_retimes_on_print():
    sheet = run(source(), '', ac='Stool Amount: Small').sheet
    key = generate_key()
    restored = open_vault(seal_vault(save_sheet_in(new_vault(), sheet), key), key)['rooms']['P4102']
    assert restored['intake_output'] == sheet['intake_output']
    assert restored['current_shift'] == sheet['current_shift']
    assert restored['bowel_movement'] == sheet['bowel_movement']
    printed = handoff_text(restored, datetime(2026, 1, 9, 17, tzinfo=timezone.utc))
    assert 'Current Shift (7pm - 6:30am)' in printed


def test_callback_reimport_does_not_restore_stale_io_widget_values(app, monkeypatch):
    open_room(app)
    app.st.session_state['paste'] = wrap('h', source()) + '\n' + wrap('s', '')
    app.create_handoff()
    first = app.st.session_state['drafts']['P4102']
    equip(app, monkeypatch)
    app.intake_output_editor(first)
    stale_key = 'io_' + first['id'] + '_intake'
    assert app.st.session_state[stale_key] == '1250 ml'
    app.st.session_state['paste'] = wrap('h', source().replace('Intake 1250 ml', 'Intake 1500 ml')) + '\n' + wrap('s', '')
    app.create_handoff()
    refreshed = app.st.session_state['drafts']['P4102']
    assert refreshed['intake_output']['intake'] == '1500 ml'
    app.save_room(None)
    assert app.st.session_state['vault']['rooms']['P4102']['intake_output']['intake'] == '1500 ml'


def test_explicit_s_zero_is_populated_not_empty():
    result = run(source(), 'Intake/Output:\nIntake 0 ml\nOutput 0 ml\nNet 0 ml')
    assert not result.errors and result.sheet['intake_output']['intake'] == '0 ml'
    assert result.sheet['intake_output']['net'] == '0 ml'


def test_partial_s_keeps_missing_fields_without_borrowing_h_values():
    result = run(source(), 'Intake/Output:\nIntake 50 ml')
    assert not result.errors
    assert result.sheet['intake_output']['intake'] == '50 ml'
    assert result.sheet['intake_output']['output'] == result.sheet['intake_output']['net'] == ''
