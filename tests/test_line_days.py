"""Synthetic line days with Eastern calendar boundaries and saved-date integrity."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

from pypdf import PdfReader
import pytest

from devices import parse_devices, device_line, devices_text, devices_markup, line_day_number
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf, handoffs_html
from importing import import_sections
from lab_windows import display_clock
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room


EASTERN = ZoneInfo('America/New_York')
NOW = datetime(2026, 11, 10, 12, tzinfo=EASTERN)


def sheet_with_devices(text):
    result = import_sections(new_sheet('P4102'), 'uuuuuuuu\n' + text + '\nUUUUUUUU', new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize('inserted,instant,expected', [
    ('11/10/2026', NOW, 1),
    ('11/09/26', NOW, 2),
    ('11/08/2026', NOW, 3),
    ('12/31/25', datetime(2026, 1, 1, tzinfo=EASTERN), 2),
    ('02/28/24', datetime(2024, 3, 1, tzinfo=EASTERN), 3),
    ('02/28/25', datetime(2025, 3, 1, tzinfo=EASTERN), 2),
    ('03/07/26', datetime(2026, 3, 9, tzinfo=EASTERN), 3),
    ('10/31/26', datetime(2026, 11, 2, tzinfo=EASTERN), 3),
    ('11/10/26', datetime(2026, 11, 11, 4, 59, tzinfo=timezone.utc), 1),
    ('11/10/26', datetime(2026, 11, 11, 5, 0, tzinfo=timezone.utc), 2),
    ('07/10/26', datetime(2026, 7, 11, 3, 59, tzinfo=timezone.utc), 1),
    ('07/10/26', datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc), 2),
])
def test_calendar_days(inserted, instant, expected):
    assert line_day_number(inserted, instant) == expected


@pytest.mark.parametrize('value', ['', 'unknown', '11/11/2026', '02/30/26', '11/08', None])
def test_missing_invalid_or_future_has_no_invented_day(value):
    assert line_day_number(value, NOW) is None


@pytest.mark.parametrize('prefix,kind', [
    ('Peripheral IV', 'PIV'), ('PIV', 'PIV'), ('PICC', 'PICC'),
    ('CVC', 'CVC'), ('CVL', 'CVC'), ('Central Venous Line', 'CVC'),
    ('Arterial Line', 'Arterial line'), ('Hemodialysis Catheter', 'CVC'),
])
def test_vascular_types_keep_date_and_calculate_day(prefix, kind):
    data = parse_devices(prefix + ' 11/08/26 Right Arm')
    assert not data.error
    row = data.data['rows'][0]
    before = deepcopy(row)
    assert row['kind'] == kind
    assert '(11/08/26, Day 3)' in device_line(row, NOW)
    assert row == before


def test_multiple_lines_each_use_their_own_date_without_storing_days():
    sheet = sheet_with_devices('PIV 11/10/2026 Right Hand\nPICC 11/08/26 Left Arm\nCVL 11/09/26 Right Femoral')
    before = deepcopy(sheet)
    first = devices_text(sheet, NOW)
    assert '11/10/2026, Day 1' in first
    assert '11/08/26, Day 3' in first
    assert '11/09/26, Day 2' in first
    assert first == devices_text(sheet, NOW)
    assert first.count('Day ') == 3
    assert sheet == before


def test_line_counts_refresh_after_encrypted_reload():
    sheet = sheet_with_devices('PICC 11/08/26 Left Arm')
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    saved = deepcopy(restored)
    with display_clock(NOW):
        assert 'Day 3' in devices_text(restored['rooms']['P4102'])
    with display_clock(datetime(2026, 11, 11, 12, tzinfo=EASTERN)):
        assert 'Day 4' in devices_text(restored['rooms']['P4102'])
    assert restored == saved
    assert restored['rooms']['P4102']['devices']['rows'][0]['date'] == '11/08/26'


def test_legacy_cvl_stored_as_other_gets_day_without_rewriting_archive():
    sheet = sheet_with_devices('CVL 11/08/26 Right Femoral-Status: In place')
    sheet['devices']['rows'][0]['kind'] = 'Other'
    before = deepcopy(sheet)
    text = devices_text(sheet, NOW)
    assert 'Vascular access: CVL Right Femoral (11/08/26, Day 3)' in text
    assert 'Other devices:' not in text
    assert 'data-line-insertion="2026-11-08"' in devices_markup(sheet, as_of=NOW, live_days=True)
    assert sheet == before


def test_removed_nonvascular_unknown_dates_do_not_gain_days():
    sheet = sheet_with_devices(
        '[REMOVED] PIV 11/08/26 Left Arm\nPICC Right Arm\n'
        'PIV 11/11/26 Right Hand\nETT 11/08/26 4 mm\n'
        '[REMOVED] ETT 11/07/26 3.5 mm\nUrethral Catheter 11/08/26 8 Fr')
    text = devices_text(sheet, NOW)
    assert 'Day ' not in text
    assert '11/11/26' in text and 'ETT history (removed)' in text
    assert 'PIV Left Arm' not in text


def test_all_export_paths_use_export_day_and_preserve_source():
    sheet = sheet_with_devices('CVL 11/08/26 Right Femoral')
    before = deepcopy(sheet)
    for text in (handoff_text(sheet, NOW), handoff_html(sheet, NOW), handoffs_html([sheet], NOW)):
        assert '11/08/26, Day 3' in text
    for blob in (handoff_pdf(sheet, NOW), handoffs_pdf([sheet], NOW)):
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(blob)).pages)
        assert '11/08/26, Day 3' in text
        assert text.count('Day 3') == 1
    assert sheet == before


def test_live_html_has_only_escaped_dates_and_no_duplicate_day_labels():
    sheet = sheet_with_devices('PICC 11/08/26 Left Arm')
    sheet['devices']['rows'][0]['label'] = 'PICC <script>unsafe</script> & Left Arm'
    markup = devices_markup(sheet, as_of=NOW, live_days=True)
    assert 'data-line-insertion="2026-11-08"' in markup
    assert 'data-line-date="11/08/26"' in markup
    assert '<script>unsafe' not in markup and '&lt;script&gt;' in markup
    assert markup.count('Day 3') == 1
    plain_markup = devices_markup(sheet, as_of=NOW)
    assert 'data-line-insertion' not in plain_markup
    assert '11/08/26, Day 3' in plain_markup


def test_date_edit_recalculates_without_new_paste(app):
    open_room(app)
    sheet = sheet_with_devices('PIV 11/08/26 Left Hand')
    app.set_editor('P4102', sheet)
    row = app.st.session_state['drafts']['P4102']['devices']['rows'][0]
    key = 'device_' + row['id'] + '_date'
    app.st.session_state[key] = '11/09/26'
    app.device_row_change('P4102', 'devices', row['id'], 'date', key)
    assert row['date'] == '11/09/26'
    assert 'Day 2' in device_line(row, NOW)
    validate_sheet(app.st.session_state['drafts']['P4102'])
