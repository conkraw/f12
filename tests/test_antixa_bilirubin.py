"""6.52 regressions. Synthetic inputs only, with fixed Eastern display clocks."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo
import pytest
from pypdf import PdfReader
from labs import parse_labs
from lab_windows import anti_xa_today, anti_xa_today_summary, laboratory_data, display_clock
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, upgrade_vault
from categories import save_category, apply_category_rules
from empty_groups import refresh_empty_group_layout
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from problem_review import suggestions, review_text, set_decision
from importing import import_sections
from security import generate_key, seal_vault, open_vault
from test_rooms_infusions import med

ET = ZoneInfo('America/New_York')
NOW = datetime(2026, 11, 9, 16, 0, tzinfo=ET)

def sheet(rows=''):
    s = new_sheet('P4102')
    parsed = parse_labs('LABS:\nComponent\tValue\tDate\n' + rows)
    assert not parsed.error, parsed.error
    s['labs'] = parsed.data
    s['admission_date'] = '11/01/2026'
    validate_sheet(s)
    return s

def fields(s, now=NOW):
    with display_clock(now):
        return fields_with_medications(s)

def has_bili(s, now=NOW):
    return any(r['key'] == 'BILITOT' for r in suggestions(s, now))

@pytest.mark.parametrize('date,today,bottom', [
    ('11/09/2026', True, False), ('11/09/26', True, False),
    ('11/9/2026 0000', True, False), ('11/09/2026 15:59', True, False),
    ('11/09/2026 16:00', True, False), ('11/09/2026 16:01', False, False),
    ('11/08/2026 23:59', False, True), ('11/08/2026', False, True),
    ('11/01/2026', False, True), ('10/31/2026', False, True),
    ('11/10/2026', False, False),
])
def test_calendar_date_not_rolling_day(date, today, bottom):
    s = sheet('HEPLMW\t0.56\t' + date)
    f = fields(s)
    assert ('Anti-Xa (HEPLMW):' in f['Hematology']) is today
    assert ('Anti-Xa (HEPLMW):' in f['Lab Results / Trends']) is bottom
    assert bool(anti_xa_today(s, NOW)) is today

@pytest.mark.parametrize('code', ['HEPLMW', 'heplmw', 'HePlMw', ' HEPLMW '])
def test_exact_component_case_insensitive_without_unit_inference(code):
    s = sheet(code + '\t0.56 (H)\t11/09/2026')
    text = anti_xa_today_summary(s, NOW)
    assert text == 'Anti-Xa (HEPLMW): 0.56 (H) [11/09/2026]'
    assert 'IU' not in text

@pytest.mark.parametrize('code', ['ANTI-XA', 'ANTI XA', 'LABHEPA', 'HEPLMWX'])
def test_different_assays_not_relabelled_or_moved(code):
    s = sheet(code + '\t0.56\t11/09/2026')
    assert not anti_xa_today(s, NOW)
    assert not anti_xa_today_summary(s, NOW)
    assert len(laboratory_data(s, NOW)['rows']) == 1

@pytest.mark.parametrize('value', ['0', '<0.10', '>1.5 (H)', '0.56 IU/mL', '0.56 U/mL (H)'])
def test_numeric_value_flags_and_supplied_units_unchanged(value):
    s = sheet('HEPLMW\t' + value + '\t11/09/2026')
    before = deepcopy(s)
    assert anti_xa_today_summary(s, NOW) == 'Anti-Xa (HEPLMW): ' + value + ' [11/09/2026]'
    fields(s)
    assert s == before

@pytest.mark.parametrize('value', ['Pending', 'Canceled', 'Hemolyzed', 'IMPROPERLY COLLECTED', 'not collected', '0.56 pending (H)', '0.56 canceled'])
def test_status_messages_not_promoted_as_numeric_levels(value):
    s = sheet('HEPLMW\t' + value + '\t11/09/2026')
    assert not anti_xa_today(s, NOW)
    assert not laboratory_data(s, NOW)['rows']

def test_latest_today_once_no_stale_older_duplicate():
    s = sheet('HEPLMW\t0.41\t11/09/2026 08:00\nHEPLMW\t0.63\t11/09/2026 15:00\nHEPLMW\t0.27\t11/08/2026\nPT\t14.0\t11/09/2026')
    f = fields(s)
    assert '0.63' in f['Hematology'] and '0.41' not in f['Hematology']
    assert 'HEPLMW' not in f['Lab Results / Trends'] and 'PT: 14.0' in f['Lab Results / Trends']
    assert len(s['labs']['rows']) == 4

def test_date_only_today_preserves_source_first_row_order():
    s = sheet('HEPLMW\t0.68\t11/09/2026\nHEPLMW\t0.39\t11/09/2026')
    assert anti_xa_today(s, NOW)['value'] == '0.68'

def test_after_midnight_result_moves_back_without_mutation_or_save():
    s = sheet('HEPLMW\t0.56\t11/09/2026 22:55')
    before = deepcopy(s)
    first = fields(s, datetime(2026, 11, 9, 23, 59, tzinfo=ET))
    next_day = fields(s, datetime(2026, 11, 10, 0, 0, tzinfo=ET))
    assert 'HEPLMW' in first['Hematology'] and 'HEPLMW' not in first['Lab Results / Trends']
    assert 'HEPLMW' not in next_day['Hematology'] and '0.56 [11/09/2026 22:55]' in next_day['Lab Results / Trends']
    assert s == before

@pytest.mark.parametrize('utc_day,utc_hour,local_date', [(10, 1, '11/09/2026'), (10, 5, '11/10/2026')])
def test_utc_host_uses_eastern_calendar(utc_day, utc_hour, local_date):
    now = datetime(2026, 11, utc_day, utc_hour, tzinfo=timezone.utc)
    s = sheet('HEPLMW\t0.56\t' + local_date)
    assert anti_xa_today(s, now)

def test_hidden_result_not_resurrected():
    s = sheet('HEPLMW\t0.56\t11/09/2026')
    s['labs']['rows'][0]['include'] = False
    f = fields(s)
    assert 'HEPLMW' not in f['Hematology'] + f['Lab Results / Trends']

def test_dvt_medications_then_level_no_duplicate():
    s = sheet('HEPLMW\t0.56\t11/09/2026')
    s['medications'] = [med('enoxaparin test injection', dose='12 mg', route='Subcutaneous', frequency='q12h', rate='', section='Hematology')]
    heme = fields(s)['Hematology']
    assert heme.index('DVT Prophylaxis') < heme.index('enoxaparin') < heme.index('Anti-Xa')
    assert 'None' not in heme and heme.count('Anti-Xa') == 1

def test_no_dvt_medication_still_displays_level_without_claiming_treatment():
    s = sheet('HEPLMW\t0.56\t11/09/2026')
    assert 'DVT Prophylaxis: None\nAnti-Xa (HEPLMW): 0.56' in fields(s)['Hematology']

def test_hidden_dvt_order_suppresses_false_none_but_not_lab():
    s = sheet('HEPLMW\t0.56\t11/09/2026')
    row = med('enoxaparin test injection', dose='12 mg', route='Subcutaneous', frequency='q12h', rate='', section='Hematology')
    row['hidden'] = True
    s['medications'] = [row]
    heme = fields(s)['Hematology']
    assert 'Anti-Xa' in heme and 'None' not in heme and 'enoxaparin' not in heme

@pytest.mark.parametrize('has_med', [True, False])
def test_renamed_nested_dvt_category_contains_result(has_med):
    settings = new_vault()['settings']
    settings = save_category(settings, 'Anticoagulation', 'Hematology', ident='custom:anticoag')
    settings = save_category(settings, 'DVT prevention', 'Hematology', ident='group:dvt', parent='custom:anticoag')
    s = sheet('HEPLMW\t0.56\t11/09/2026')
    if has_med:
        s['medications'] = apply_category_rules([med('enoxaparin test', dose='12 mg', route='Subcutaneous', frequency='q12h', rate='', section='Hematology')], settings)
    refresh_empty_group_layout(s, settings)
    heme = fields(s)['Hematology']
    assert heme.index('Anticoagulation') < heme.index('DVT prevention') < heme.index('Anti-Xa')
    assert heme.count('Anti-Xa') == 1 and 'DVT Prophylaxis' not in heme

def test_g_import_failure_suppresses_derived_level_and_problem():
    s = sheet('HEPLMW\t0.56\t11/09/2026\nBILITOT\t2.3 (H)\t11/09/2026')
    result = import_sections(s, 'g'*20 + '\nLABS:\nmalformed data\n' + 'g'*20, new_vault()['settings'])
    assert result.errors and 'g' in result.sheet['import_warnings']
    assert not anti_xa_today(result.sheet, NOW)
    assert not has_bili(result.sheet)

@pytest.mark.parametrize('flag,want', [('(H)', True), ('(HH)', True), ('(HIGH)', True), ('(h)', True), ('', False), ('(L)', False), ('(A)', False), ('*', False), ('(H) (L)', False)])
def test_bilirubin_explicit_high_flag_only(flag, want):
    s = sheet('BILITOT\t2.3 ' + flag + '\t11/09/2026')
    assert has_bili(s) is want

@pytest.mark.parametrize('component', ['BILITOT', 'bilitot', 'TBILI', 'TOTAL BILIRUBIN'])
def test_total_bilirubin_aliases(component):
    assert has_bili(sheet(component + '\t2.3 (H)\t11/09/2026'))

@pytest.mark.parametrize('component', ['BILIDIR', 'DIRECT BILIRUBIN', 'DBILI', 'AST', 'ALT'])
def test_other_high_liver_results_do_not_trigger(component):
    assert not has_bili(sheet(component + '\t2.3 (H)\t11/09/2026'))

def test_latest_normal_clears_old_high():
    s = sheet('BILITOT\t2.3 (H)\t11/08/2026\nBILITOT\t0.6\t11/09/2026')
    assert not has_bili(s)

def test_latest_timestamp_used_within_same_day():
    s = sheet('BILITOT\t2.3 (H)\t11/09/2026 08:00\nBILITOT\t0.6\t11/09/2026 14:00')
    assert not has_bili(s)
    s['labs']['rows'][1]['value'] = '2.4 (H)'
    assert has_bili(s)

def test_bilirubin_date_only_source_order_used():
    s = sheet('BILITOT\t0.6\t11/09/2026\nBILITOT\t2.3 (H)\t11/09/2026')
    assert not has_bili(s)

@pytest.mark.parametrize('date', ['10/31/2026', '11/10/2026', '11/09/2026 16:01'])
def test_bilirubin_admission_and_future_guard(date):
    assert not has_bili(sheet('BILITOT\t2.3 (H)\t' + date))

@pytest.mark.parametrize('value', ['Pending (H)', 'Canceled', '2.3 pending (H)', '-1 (H)'])
def test_nonmeasurement_or_invalid_bilirubin_not_called_high(value):
    assert not has_bili(sheet('BILITOT\t' + value + '\t11/09/2026'))

def test_bilirubin_exclusion_edit_and_dismissal():
    s = sheet('BILITOT\t2.3 (H)\t11/09/2026')
    row = next(r for r in suggestions(s, NOW) if r['key'] == 'BILITOT')
    dismissed = set_decision(s, row['key'], row['fingerprint'], 'dismissed', row['label'])
    assert 'Hyperbilirubinemia' not in review_text(dismissed, NOW)
    dismissed['labs']['rows'][0]['value'] = '2.4 (H)'
    assert 'Hyperbilirubinemia' in review_text(dismissed, NOW)
    s['labs']['rows'][0]['include'] = False
    assert not has_bili(s)

def test_sheet_and_encrypted_archive_roundtrip_with_new_decision():
    s = sheet('HEPLMW\t0.56\t11/09/2026\nBILITOT\t2.3 (H)\t11/09/2026')
    r = next(r for r in suggestions(s, NOW) if r['key'] == 'BILITOT')
    s = set_decision(s, r['key'], r['fingerprint'], 'confirmed', r['label'])
    validate_sheet(s)
    vault = new_vault(); vault['rooms']['P4102'] = s
    before = deepcopy(vault)
    key = generate_key()
    loaded = open_vault(seal_vault(vault, key), key)
    assert loaded == upgrade_vault(before) and vault == before

@pytest.mark.parametrize('format', ['text', 'html', 'pdf', 'batch_pdf'])
def test_all_exports_once_and_retained_values(format):
    s = sheet('HEPLMW\t0.56\t11/09/2026\nBILITOT\t2.3 (H)\t11/09/2026\nINR\t1.0\t11/09/2026')
    before = deepcopy(s)
    if format == 'text':
        output = handoff_text(s, printed_at=NOW)
    elif format == 'html':
        output = handoff_html(s, printed_at=NOW)
    else:
        data = handoff_pdf(s, printed_at=NOW) if format == 'pdf' else handoffs_pdf([s], printed_at=NOW)
        output = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
    assert output.count('Anti-Xa (HEPLMW):') == 1
    assert output.count('Hyperbilirubinemia') == 1
    assert '2.3 (H)' in output and '0.56' in output
    assert s == before
