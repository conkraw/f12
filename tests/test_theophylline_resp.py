"""v6.18: synthetic THEOPH result routing without changing source data."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from pypdf import PdfReader

from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, handoffs_html
from importing import import_sections
from lab_layout import laboratory_html
from labs import canonical, parse_labs, result_cards, labs_text, theophylline_text
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, SCHEMA_VERSION
from medications import parse_medications, upsert_rule
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
STAMP = datetime(2027, 1, 5, 12, 0, tzinfo=timezone.utc)


def parsed(text):
    result = parse_labs('LABS:\nLab Results\nComponent\tValue\tDate\n' + text)
    assert not result.error, result.error
    return result.data


def g_block(text):
    return 'gggggggg\nLABS:\nComponent\tValue\tDate\n' + text + '\ngggggggg'


def demo():
    source = (ROOT / 'examples' / 'synthetic_theophylline.txt').read_text()
    settings = new_vault()['settings']
    settings['medication_mappings'] = upsert_rule([], 'albuterol', 'Respiratory')
    result = import_sections(new_sheet('P4102'), source, settings)
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize('code', ['THEOPH', 'theoph', 'Theoph', ' THEOPH ', 'THEOPHYLLINE', 'Theophylline Level'])
def test_recognizes_exact_code_and_explicit_aliases_without_mutation(code):
    data = parsed(f'{code}\t12.4 (L)\t01/04/2027 09:30')
    before = deepcopy(data)
    assert canonical(code) == 'THEOPH'
    assert theophylline_text(data) == 'Theophylline level: 12.4 (L) [01/04/2027 09:30]'
    assert data['rows'][0]['panel'] == 'Respiratory drug levels'
    assert data == before


@pytest.mark.parametrize('code', ['THEOPH_FREE', 'FREE THEOPHYLLINE', 'THEOPH2', 'THEOPH ABC', 'AMINOPHYLLINE'])
def test_does_not_guess_other_test_codes(code):
    data = parsed(f'{code}\t6.4\t01/04/2027')
    assert theophylline_text(data) == ''
    assert code in labs_text(data)


@pytest.mark.parametrize('value', ['12.40', '0', '<2.0 (L)', '24.5 (H)', '12.4 mcg/mL', '12.4 mg/L', '11.9 (A)'])
def test_result_precision_units_and_source_flags_are_kept_verbatim(value):
    data = parsed(f'THEOPH\t{value}\t01/04/2027')
    assert theophylline_text(data) == f'Theophylline level: {value} [01/04/2027]'
    if '/' not in value:
        assert 'mcg/mL' not in theophylline_text(data)


def test_latest_date_not_largest_value():
    data = parsed('THEOPH\t22.3\t01/03/2027\nTHEOPH\t11.2\t01/04/2027\nTHEOPH\t19.1\t01/02/2027')
    assert theophylline_text(data) == 'Theophylline level: 11.2 [01/04/2027]'
    assert len(data['rows']) == 3


def test_latest_collection_time_is_used_when_present():
    data = parsed('THEOPH\t21.1\t01/04/2027 08:30\nTHEOPH\t13.2\t01/04/2027 12:45')
    assert theophylline_text(data).endswith('13.2 [01/04/2027 12:45]')


def test_same_date_without_times_uses_epic_order_not_value():
    data = parsed('THEOPH\t6.2\t01/04/2027\nTHEOPH\t24.0\t01/04/2027')
    assert theophylline_text(data).endswith('6.2 [01/04/2027]')


def test_mixed_timed_and_untimed_same_date_keeps_source_order():
    data = parsed('THEOPH\t6.2\t01/04/2027\nTHEOPH\t24.0\t01/04/2027 19:00')
    assert theophylline_text(data).endswith('6.2 [01/04/2027]')


def test_exclusion_and_restore_use_existing_include_field():
    data = parsed('THEOPH\t12.4\t01/04/2027\nTHEOPH\t8.0\t01/03/2027')
    data['rows'][0]['include'] = False
    assert '8.0' in theophylline_text(data)
    data['rows'][1]['include'] = False
    assert theophylline_text(data) == ''
    data['rows'][0]['include'] = True
    assert '12.4' in theophylline_text(data)
    assert len(data['rows']) == 2


@pytest.mark.parametrize('text', ['', 'NA\t139\t01/04/2027', 'No results found for: "THEOPH"'])
def test_absent_result_creates_no_placeholder(text):
    s = new_sheet('P4102')
    s['labs'] = parsed(text)
    assert not theophylline_text(s['labs'])
    assert 'Theophylline level' not in handoff_html(s)


def test_respiratory_order_and_single_occurrence():
    s = demo()
    s['fields']['Respiratory'] = 'Respiratory note sentinel'
    before = deepcopy(s)
    fields = fields_with_medications(s)
    text = fields['Respiratory']
    for left, right in [('Resp:', 'Mode:'), ('Mode:', 'Theophylline level:'),
                        ('Theophylline level:', 'Beta-Agonist'),
                        ('albuterol', 'Respiratory note sentinel')]:
        assert text.index(left) < text.index(right)
    assert text.count('Theophylline level:') == 1
    assert 'Theophylline' not in fields['Lab Results / Trends']
    assert not any('THEOPH' in card['rows'] for card in result_cards(s['labs']))
    assert 'THEOPH' not in laboratory_html(s['labs'])
    assert s == before


def test_no_device_needed_for_result_to_show():
    s = new_sheet('P4102')
    s['labs'] = parsed('THEOPH\t12.4\t01/04/2027')
    assert fields_with_medications(s)['Respiratory'] == 'Theophylline level: 12.4 [01/04/2027]'


def test_older_saved_other_labs_panel_routes_without_reimport():
    s = new_sheet('P4102')
    s['labs'] = parsed('THEOPH\t12.4\t01/04/2027')
    s['labs']['rows'][0]['panel'] = 'Other labs'
    before = deepcopy(s)
    assert '12.4' in fields_with_medications(s)['Respiratory']
    assert 'THEOPH' not in fields_with_medications(s)['Lab Results / Trends']
    assert s == before


def test_import_updates_only_g_and_omitted_g_keeps_the_level():
    s = demo()
    before = deepcopy(s)
    result = import_sections(s, g_block('THEOPH\t15.2\t01/05/2027'), new_vault()['settings'])
    assert not result.errors
    for key, value in before.items():
        if key != 'labs':
            assert result.sheet[key] == value
    assert '15.2' in fields_with_medications(result.sheet)['Respiratory']
    after = import_sections(result.sheet, 'aaaaaaaa\nDiagnoses:\n1. Synthetic edited diagnosis\naaaaaaaa', new_vault()['settings'])
    assert after.sheet['labs'] == result.sheet['labs']


@pytest.mark.parametrize('text', ['', 'NA\t140\t01/05/2027', 'No results found for: "THEOPH"'])
def test_new_g_snapshot_without_level_clears_older_automatic_level(text):
    result = import_sections(demo(), g_block(text), new_vault()['settings'])
    assert not result.errors
    assert not theophylline_text(result.sheet['labs'])


def test_invalid_lab_date_keeps_prior_snapshot_and_review_warning():
    s = demo()
    result = import_sections(s, g_block('THEOPH\t15.2\tinvalid-date'), new_vault()['settings'])
    assert result.errors
    assert result.sheet['labs'] == s['labs']
    assert 'g' in result.sheet['import_warnings']


@pytest.mark.parametrize('fn', [handoff_html, handoff_text, handoff_pdf])
def test_every_export_keeps_one_level_without_mutating_sheet(fn):
    s = demo()
    before = deepcopy(s)
    output = fn(s, printed_at=STAMP)
    if isinstance(output, bytes):
        output = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(output)).pages)
    assert output.count('Theophylline level:') == 1
    assert '12.4' in output
    assert s == before


def test_pdf_has_the_level_in_resp_above_meds_and_below_support():
    doc = fitz.open(stream=handoff_pdf(demo(), printed_at=STAMP), filetype='pdf')
    assert len(doc) == 1
    p = doc[0]
    level = p.search_for('Theophylline level:')[0]
    resp = p.search_for('RESP')[0]
    meds = p.search_for('albuterol')[0]
    mode = p.search_for('Mode:')[0]
    lab_area = p.search_for('Other Medications')[0]
    from exports import PRINT_MARGIN, WIDTHS
    width = p.rect.width - 2 * PRINT_MARGIN
    left = PRINT_MARGIN + width * sum(WIDTHS[:2])
    right = left + width * WIDTHS[2]
    assert left <= level.x0 < level.x1 <= right
    assert mode.y0 < level.y0 < meds.y0 < lab_area.y0
    assert p.rect.width == 792 and p.rect.height == 612
    doc.close()


def test_print_all_has_room_specific_results():
    first, second = demo(), demo()
    second['room'] = 'P4104'
    second['labs'] = parsed('THEOPH\t16.8\t01/05/2027')
    pdf = PdfReader(BytesIO(handoffs_pdf([first, second], printed_at=STAMP)))
    assert len(pdf.pages) == 2
    assert '12.4' in pdf.pages[0].extract_text()
    assert '16.8' in pdf.pages[1].extract_text()
    assert all(p.extract_text().count('Theophylline level:') == 1 for p in pdf.pages)
    assert handoffs_html([first, second], printed_at=STAMP).count('Theophylline level:') == 2


def test_original_fields_encrypted_without_schema_or_key_change():
    vault = save_sheet_in(new_vault(), demo())
    before = deepcopy(vault)
    key = generate_key()
    reopened = open_vault(seal_vault(vault, key), key)
    assert SCHEMA_VERSION ==32
    assert reopened == before
    assert 'Theophylline level:' in fields_with_medications(reopened['rooms']['P4102'])['Respiratory']


def test_edit_and_exclude_through_existing_callback(app):
    open_room(app)
    ss = app.st.session_state
    ss['drafts']['P4102'] = demo()
    row = ss['drafts']['P4102']['labs']['rows'][0]
    ss['theoph_edit'] = '14.3 (H)'
    app.lab_row_change('P4102', row['id'], 'value', 'theoph_edit')
    assert '14.3 (H)' in theophylline_text(ss['drafts']['P4102']['labs'])
    ss['theoph_include'] = False
    app.lab_row_change('P4102', row['id'], 'include', 'theoph_include')
    assert '9.1' in theophylline_text(ss['drafts']['P4102']['labs'])


def test_editor_and_full_handoff_render_the_level(app, monkeypatch):
    open_room(app)
    app.st.session_state['drafts']['P4102'] = demo()
    equip(app, monkeypatch)
    rendered = []
    app.st.text = lambda text, *a, **k: rendered.append(text)
    app.handoff_page(None)
    assert any(x.startswith('Respiratory: Theophylline level:') for x in rendered)
    assert any(x.startswith('Theophylline level:') for x in rendered)


def test_html_escapes_source_value_not_executable_markup():
    s = new_sheet('P4102')
    s['labs'] = parsed('THEOPH\t<2.0 (L) <script>bad()</script>\t01/04/2027')
    html = handoff_html(s)
    assert 'Theophylline level:' not in html  # v6.30: non-measurements are retained only in the editor
    assert '<script>bad()</script>' not in html


# v6.30: make time-window routing tests independent of the machine's clock.
from datetime import datetime, timezone
from lab_windows import display_clock
@pytest.fixture(autouse=True)
def fixed_routing_clock():
    with display_clock(datetime(2027,1,5,12,0,tzinfo=timezone.utc)):
        yield
