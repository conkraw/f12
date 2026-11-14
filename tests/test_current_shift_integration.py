"""Synthetic integration tests. No live patient source or repository access."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import fitz
import pytest
from current_shift import current_shift_text
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, validate_sheet, save_sheet_in, upgrade_vault
from fluid_balance import parse_balance, balance_text, balance_heading
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from batching import available_handoffs
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_current_shift import source

BALANCE = '''Intake/Output Summary (Last 24 hours) at 01/05/2026 0617
Last data filed at 01/05/2026 0545
Gross per 24 hour
Intake\t1200.5 ml
Output\t950 ml
Net\t250.5 ml'''


def block(key, body):
    return key * 12 + '\n' + body + '\n' + key * 12


def imported(body=None, old=None, extra=''):
    result = import_sections(deepcopy(old) if old is not None else new_sheet('P4102'),
                             block('h', source() if body is None else body) + '\n' + extra,
                             new_vault()['settings'])
    assert result.sheet is not None, result.errors
    return result


def test_existing_24_hour_object_values_times_and_output_unchanged():
    old = new_sheet('P4102')
    old['intake_output'] = parse_balance(BALANCE).data
    before = deepcopy(old['intake_output'])
    old_text = fields_with_medications(old)['FEN / GI']
    result = imported(old=old, extra=block('s', BALANCE))
    assert not result.errors
    sheet = result.sheet
    assert sheet['intake_output'] == before == old['intake_output']
    assert fields_with_medications(sheet)['FEN / GI'].replace('\n-----\n' + current_shift_text(sheet), '', 1) == old_text
    assert balance_heading(sheet['intake_output']) == 'Intake/Output (6a-6a)'
    assert sheet['intake_output']['last_filed'] == '01/05/2026 0545'


def test_explicit_h_24h_totals_fill_missing_s_but_do_not_replace_populated_s():
    result = imported()
    assert not result.errors and result.sheet['intake_output']['intake'] == '1250 ml' 
    result = imported(extra=block('s', BALANCE))
    assert not result.errors and result.sheet['intake_output'] == parse_balance(BALANCE).data
    assert result.sheet['current_shift']['as_of'] == '2026-01-05T06:30:00'


def test_other_sheet_fields_unchanged_and_nutrition_follows_shift():
    old = new_sheet('P4102')
    old['fields']['FEN / GI'] = 'Synthetic separate notes'
    old['fields']['Respiratory'] = 'Synthetic support'
    old['dosing_weight'] = '5 kg'
    before = deepcopy(old)
    sheet = imported(old=old).sheet
    assert {k: v for k, v in sheet.items() if k not in ('current_shift', 'intake_output', 'empty_group_layout')} == {k: v for k, v in before.items() if k not in ('intake_output', 'empty_group_layout')}
    text = fields_with_medications(sheet)['FEN / GI']
    assert text.index('Current Shift') < text.index('Synthetic separate notes')
    assert 'UOP: 2.00' in text


def test_saved_old_archive_works_without_new_field():
    vault = new_vault()
    sheet = new_sheet('P4102')
    assert 'current_shift' not in sheet
    validate_sheet(sheet)
    vault = save_sheet_in(vault, sheet)
    assert upgrade_vault(vault) == vault


def test_encrypted_save_and_recall_keeps_source_endpoint():
    sheet = imported().sheet
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    loaded = open_vault(seal_vault(vault, key), key)
    restored = loaded['rooms']['P4102']
    assert restored['current_shift'] == sheet['current_shift']
    assert current_shift_text(restored) == current_shift_text(sheet)


def test_new_print_time_does_not_change_rates_or_shift_label():
    sheet = imported().sheet
    for cutoff in [datetime(2026, 1, 5, 20, tzinfo=timezone.utc), datetime(2026, 1, 6, 14, tzinfo=timezone.utc)]:
        assert current_shift_text(sheet) in handoff_text(sheet, cutoff)
    assert sheet['current_shift']['as_of'] == '2026-01-05T06:30:00'


def test_shift_only_handoff_in_print_all_and_all_export_formats():
    sheet = imported().sheet
    assert 'P4102' in available_handoffs(new_vault(), {'P4102': sheet})
    assert current_shift_text(sheet) in handoff_text(sheet)
    html = handoff_html(sheet)
    assert 'Current Shift (11pm - 6:30am)' in html and '2.00 mL/kg/hr' in html
    for pdf in (handoff_pdf(sheet), handoffs_pdf([sheet])):
        doc = fitz.open(stream=pdf, filetype='pdf')
        text = '\n'.join(page.get_text() for page in doc)
        assert 'Current Shift' in text and '2.00 mL/kg/hr' in text and 'Chest Tube:' in text


def test_failed_new_h_clears_prior_shift_without_affecting_24h():
    old = imported(extra=block('s', BALANCE)).sheet
    before = deepcopy(old['intake_output'])
    result = imported(source(out='Urine:NOT_A_VOLUME'), old=old, extra=block('s', BALANCE))
    assert result.errors and result.sheet['current_shift'] is None
    assert 'h' in result.sheet['import_warnings']
    assert result.sheet['intake_output'] == before
    result.sheet['import_warnings'].clear()
    assert 'Current Shift' not in handoff_text(result.sheet)


def test_malformed_h_boundary_clears_old_shift():
    old = imported().sheet
    result = import_sections(old, 'hhhhhhhh\n' + source(), new_vault()['settings'])
    assert result.sheet is not None and result.errors
    assert result.sheet['current_shift'] is None


def test_missing_h_retains_snapshot_but_explicit_blank_h_clears_it():
    old = imported().sheet
    other = import_sections(old, block('a', 'Diagnoses:\n1. Synthetic'), new_vault()['settings'])
    assert other.sheet['current_shift'] == old['current_shift']
    cleared = imported('INTAKE/OUTPUT:', old=old)
    assert not cleared.errors and cleared.sheet['current_shift'] is None


def test_incomplete_source_never_uses_saved_24h_clock_or_dosing_weight():
    old = imported(extra=block('s', BALANCE)).sheet
    old['dosing_weight'] = '20 kg'
    no_clock = '\n'.join(line for line in source().splitlines() if not line.startswith('Intake/Output Summary'))
    for body in (no_clock, source(weight='')):
        result = imported(body, old=old)
        assert not result.errors and result.notices
        assert current_shift_text(result.sheet) == ''
        result.sheet['import_warnings'].clear()
        assert current_shift_text(result.sheet) == ''


def test_current_shift_ui_is_read_only_and_displayed_once(app, monkeypatch):
    open_room(app)
    sheet = imported().sheet
    app.st.session_state['drafts']['P4102'] = sheet
    equip(app, monkeypatch)
    headings, texts = [], []
    app.st.subheader = lambda label, **kwargs: headings.append(label)
    app.st.text = lambda label, **kwargs: texts.append(label)
    before = deepcopy(sheet)
    app.current_shift_editor(sheet)
    assert headings == ['Current Shift (11pm - 6:30am)']
    assert sum('UOP: 2.00' in text for text in texts) == 1
    assert sheet == before


def test_full_handoff_ui_with_shift(app, monkeypatch):
    open_room(app)
    app.st.session_state['drafts']['P4102'] = imported().sheet
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(value, bytes) and value.startswith(b'%PDF') for _, value in downloads)


def test_acknowledging_failed_shift_does_not_restore_old_rates(app):
    open_room(app)
    sheet = imported(source(out='Urine:BAD'), old=imported().sheet).sheet
    app.st.session_state['drafts']['P4102'] = sheet
    app.acknowledge_import_warning('P4102', 'h')
    assert sheet['current_shift'] is None and current_shift_text(sheet) == ''


def test_reimport_replaces_shift_snapshot_and_removes_warnings():
    bad = imported(source(out='Urine:BAD'), old=imported().sheet).sheet
    fresh = imported(source(stamp='01/05/2026 1630', out='Urine:60'), old=bad)
    assert not fresh.errors and 'h' not in fresh.sheet['import_warnings']
    assert current_shift_text(fresh.sheet) == 'Current Shift (3pm - 4:30pm)\nUOP: 2.00 mL/kg/hr'
