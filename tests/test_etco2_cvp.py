from style_assert_helpers import without_style_tags
"""ETCO2/CVP E-block import regressions. Inputs and handoffs are synthetic."""
from copy import deepcopy
from pathlib import Path
import pytest
import fitz
from vitals import parse_vitals, route, text_by_system
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, validate_sheet
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from security import generate_key, seal_vault, open_vault
from medications import remap, upsert_rule
from recovery_helpers import assert_retained
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
ET = 'ETCO2 (mmHg)  Avg: 42.2 mmHg  Min: 28 mmHg  Max: 61 mmHg'
CVP = 'CVP (mean)  Avg: 7.4 mmHg  Min: 3 mmHg  Max: 12 mmHg'


def block(value):
    return 'eeeeeeee\nVITALS:\n' + value + '\neeeeeeee'


def sample_sheet():
    result = import_sections(new_sheet('P4102'), (ROOT / 'examples/synthetic_etco2_cvp.txt').read_text(), new_vault()['settings'])
    assert not result.errors, result.errors
    sheet = result.sheet
    sheet['fields']['Respiratory'] = 'RESP_NOTES'
    sheet['fields']['Cardiovascular'] = 'CV_NOTES'
    return sheet


@pytest.mark.parametrize('source,label,value,section', [
    (ET, 'ETCO2', '28 to 61 mmHg', 'Respiratory'),
    (CVP, 'CVP (mean)', '3 to 12 mmHg', 'Cardiovascular'),
    ('EtCO2: Avg: 40 mmHg Min: 20 mmHg Max: 60 mmHg', 'ETCO2', '20 to 60 mmHg', 'Respiratory'),
    ('ETCO₂ (mmHg)\tAvg: 42\tMin: 28\tMax: 61', 'ETCO2', '28 to 61 mmHg', 'Respiratory'),
    ('ET CO2 (mmHg) Average: 40 Minimum: 28 Maximum: 60', 'ETCO2', '28 to 60 mmHg', 'Respiratory'),
    ('End-tidal CO2 (mmHg): Avg: 40 Min: 28 Max: 60', 'ETCO2', '28 to 60 mmHg', 'Respiratory'),
    ('End tidal carbon dioxide (kPa) Avg: 5 Min: 3.50 Max: 6.20', 'ETCO2', '3.50 to 6.20 kPa', 'Respiratory'),
    ('CVP (mean) (mmHg) Avg: 7.4 Min: 3 Max: 12', 'CVP (mean)', '3 to 12 mmHg', 'Cardiovascular'),
    ('CVP (mmHg) (mean) Max: 12 Avg: 7.4 Min: 3', 'CVP (mean)', '3 to 12 mmHg', 'Cardiovascular'),
    ('Central Venous Pressure (mean): Min: -2 mmHg Max: 8 mmHg', 'CVP (mean)', '-2 to 8 mmHg', 'Cardiovascular'),
    ('CVP Min: -3 mmHg Max: 0 mmHg', 'CVP', '-3 to 0 mmHg', 'Cardiovascular'),
    ('CVP (cm H2O) Avg: 7.4 Min: 3 Max: 12', 'CVP', '3 to 12 cmH2O', 'Cardiovascular'),
    ('ETCO2 (mmHg) Avg: 40 Min: 0 Max: 200', 'ETCO2', '0 to 200 mmHg', 'Respiratory'),
    ('ETCO2 (mmHg) Avg: N/A Min: 28 Max: 61', 'ETCO2', '28 to 61 mmHg', 'Respiratory'),
    ('CVP (mmHg) Min: 3.50 Max: 12.00', 'CVP', '3.50 to 12.00 mmHg', 'Cardiovascular'),
    ('CVP Min: 3 Max: 12', 'CVP', '3 to 12', 'Cardiovascular'),
    ('ETCO2 (mmHg) Min: 35 Max: 35', 'ETCO2', '35 to 35 mmHg', 'Respiratory'),
    ('CVP (mean) Avg: 4 mmHg Min: .5 mmHg Max: +8 mmHg', 'CVP (mean)', '.5 to +8 mmHg', 'Cardiovascular'),
    ('CVP (mean) Avg: 7.4 mm Hg Min: 3 mm Hg Max: 12 mm Hg', 'CVP (mean)', '3 to 12 mmHg', 'Cardiovascular'),
    ('cvp\u00a0(mean)\u202favg: 7.4 mmHg min: 3 mmHg max: 12 mmHg', 'CVP (mean)', '3 to 12 mmHg', 'Cardiovascular'),
    ('CVP (mmHg) Min: 3 Min: 3.0 Max: 12', 'CVP', '3 to 12 mmHg', 'Cardiovascular'),
])
def test_supported_ranges(source, label, value, section):
    result = parse_vitals('VITALS:\n' + source)
    assert not result.error and not result.issues
    assert result.rows == [{'label': label, 'value': value, 'section': section, 'include': True}]


@pytest.mark.parametrize('source', [
    'No data recorded', ' NO DATA RECORDED. ', 'No data recorded:',
    'ETCO2 (mmHg): No data recorded', 'CVP (mean) No data recorded',
    'ETCO₂ (mmHg): Not documented', 'CVP: N/A', 'CVP (mean): --',
    'ETCO2 (mmHg)', 'CVP (mean):', 'Central venous pressure: None',
])
def test_missing_data_does_not_become_zero_or_cancel_vitals(source):
    result = parse_vitals('VITALS:\nResp: 18\n' + source + '\nHeart Rate: 100')
    assert not result.error and not result.issues
    assert len(result.rows) == 2
    assert [r['label'] for r in result.rows] == ['Resp', 'Heart Rate']


@pytest.mark.parametrize('source', [
    'ETCO2 (mmHg) Avg: 30 Min: 20',
    'ETCO2 (mmHg) Avg: 30 Max: 40',
    'ETCO2 (mmHg) Avg: 30',
    'CVP Avg: 5 mmHg Min: -- Max: 10 mmHg',
    'CVP Min: 10 mmHg Max: 5 mmHg',
    'CVP Min: 3 mmHg Max: 8 cmH2O',
    'CVP Min: 3 Max: 8 mmHg',
    'CVP (kPa) Min: 3 mmHg Max: 8 mmHg',
    'CVP (mmHg) (kPa) Min: 3 Max: 8',
    'ETCO2 Min: 20% Max: 40%',
    'CVP (mmHg) Min: 3 Min: 4 Max: 12',
    'CVP (mmHg) Min: 3 Max: 12 Max: 14',
    'ETCO2 (mmHg) Min: 20 mmHg extra Max: 40 mmHg',
    'ETCO2 (mmHg) Min: 20 | 21 Max: 40',
    'CVP (mmHg) Min: NaN Max: 10',
])
def test_ambiguous_pressure_summary_keeps_existing_section_and_warns(source):
    original = sample_sheet()
    snapshot = deepcopy(original)
    result = import_sections(original, block(source), new_vault()['settings'])
    assert_retained(result, snapshot, 'e')
    assert original == snapshot


@pytest.mark.parametrize('source,label,value', [
    ('ETCO2: 40 mmHg', 'ETCO2', '40 mmHg'),
    ('ETCO2 (mmHg): [20-60] 40', 'ETCO2 (mmHg)', '[20-60] 40'),
    ('ETCO₂: 0 mmHg', 'ETCO₂', '0 mmHg'),
    ('End tidal CO2: 4.8 kPa', 'End tidal CO2', '4.8 kPa'),
    ('CVP: -2 mmHg', 'CVP', '-2 mmHg'),
    ('CVP (mean): [3-12] 8 mmHg', 'CVP (mean)', '[3-12] 8 mmHg'),
    ('Central venous pressure: 9', 'Central venous pressure', '9'),
])
def test_ordinary_values_and_units_stay_verbatim(source, label, value):
    result = parse_vitals(source)
    assert not result.error
    assert result.rows[0]['label'] == label and result.rows[0]['value'] == value
    assert result.rows[0]['section'] != 'Other'


def test_old_vitals_are_unchanged_when_monitors_not_supplied():
    text = 'Temp: [36-38] 37\nHeart Rate: [80-120] 100\nResp: [12-25] 18\nBP: (90-110)/(50-80) 100/60\nFiO2 (%): [21-30] 30 %\nSpO2 Avg: 97% Min: 93% Max: 100%'
    result = parse_vitals(text)
    assert not result.error and len(result.rows) == 6
    assert result.rows[0]['value'] == '[36-38] 37'
    assert result.rows[-1]['value'] == '93% to 100%'
    assert not any(r['label'].startswith(('CVP', 'ETCO')) for r in result.rows)


@pytest.mark.parametrize('label', ['PCO2', 'CO2', 'PCO2 VEN', 'ETCO2Monitor', 'ETCO2estimated'])
def test_blood_gas_not_used_as_etco2(label):
    assert route(label) == 'Other'


def test_ranges_always_above_support_infusions_and_notes():
    sheet = sample_sheet()
    text = fields_with_medications(sheet)
    assert text['Respiratory'].index('ETCO2:') < text['Respiratory'].index('HFNC') < text['Respiratory'].index('RESP_NOTES')
    assert text['Cardiovascular'].index('CVP (mean):') < text['Cardiovascular'].index('CV_NOTES')
    assert 'CVP' not in text['Respiratory'] and 'ETCO2' not in text['Cardiovascular']
    assert 'Avg:' not in text['Respiratory'] and 'Avg:' not in text['Cardiovascular']


def test_reimport_omission_clear_and_non_e_isolation():
    sheet = sample_sheet()
    result = import_sections(sheet, block(ET + '\n' + CVP), new_vault()['settings'])
    assert not result.errors and len(result.sheet['vitals']) == 2
    for key in sheet:
        if key != 'vitals':
            assert sheet[key] == result.sheet[key]
    again = import_sections(result.sheet, block(ET + '\n' + CVP), new_vault()['settings'])
    assert again.sheet == result.sheet
    omitted = import_sections(result.sheet, 'aaaaaaaa\nDiagnoses:\nSynthetic update\naaaaaaaa', new_vault()['settings'])
    assert omitted.sheet['vitals'] == result.sheet['vitals']
    blank = import_sections(result.sheet, block('No data recorded\nNo data recorded'), new_vault()['settings'])
    assert not blank.errors and blank.sheet['vitals'] == []
    next_room = import_sections(result.sheet, block('Resp: 18'), new_vault()['settings'])
    assert not next_room.errors and len(next_room.sheet['vitals']) == 1
    assert 'ETCO2' not in fields_with_medications(next_room.sheet)['Respiratory']
    assert 'CVP' not in fields_with_medications(next_room.sheet)['Cardiovascular']


def test_missing_monitor_markers_on_either_side_do_not_block_other_monitor():
    for text, label in [('No data recorded\n' + CVP, 'CVP (mean)'), (ET + '\nNo data recorded', 'ETCO2')]:
        result = import_sections(new_sheet('P4102'), block(text), new_vault()['settings'])
        assert not result.errors and not result.diagnostics and not result.skipped
        assert [r['label'] for r in result.sheet['vitals']] == [label]


def test_pdf_html_text_and_batch():
    sheet = sample_sheet()
    html = without_style_tags(handoff_html(sheet))
    text = handoff_text(sheet)
    for content in [html, text]:
        assert 'ETCO2: 28 to 61 mmHg' in content
        assert 'CVP (mean): 3 to 12 mmHg' in content
        assert 'No data recorded' not in content
    with fitz.open(stream=handoff_pdf(sheet), filetype='pdf') as doc:
        assert len(doc) == 1
        page = doc[0]
        for needle in ['ETCO2: 28 to 61 mmHg', 'CVP (mean): 3 to 12 mmHg']:
            assert needle in page.get_text()
        assert page.search_for('ETCO2:')[0].y0 < page.search_for('RESP_NOTES')[0].y0
        assert page.search_for('CVP (mean):')[0].y0 < page.search_for('CV_NOTES')[0].y0
    another = deepcopy(sheet)
    another['room'] = 'P4104'
    with fitz.open(stream=handoffs_pdf([sheet, another]), filetype='pdf') as doc:
        assert len(doc) == 2
        assert all('ETCO2: 28 to 61 mmHg' in p.get_text() for p in doc)


def test_encryption_and_existing_vital_format():
    sheet = sample_sheet()
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault
    validate_sheet(sheet)


def test_editor_exclusion_autosave_and_other_rooms(app):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = block(ET + '\n' + CVP)
    app.create_handoff()
    assert not ss['import_result']['errors']
    ss['et_edit'] = '29 to 60 mmHg'
    app.vital_row_change('P4102', 0, 'value', 'et_edit')
    ss['cv_hide'] = False
    app.vital_row_change('P4102', 1, 'include', 'cv_hide')
    assert 'CVP' not in fields_with_medications(ss['drafts']['P4102'])['Cardiovascular']
    open_room(app, 'P4104')
    assert ss['vault']['rooms']['P4102']['vitals'][0]['value'] == '29 to 60 mmHg'
    assert ss['drafts']['P4104']['vitals'] == []
    open_room(app, 'P4102')
    ss['cv_hide'] = True
    app.vital_row_change('P4102', 1, 'include', 'cv_hide')
    assert 'CVP (mean)' in fields_with_medications(ss['drafts']['P4102'])['Cardiovascular']


def test_page_render_has_existing_editors_and_downloads(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = block(ET + '\n' + CVP)
    app.create_handoff()
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    pdfs = [d for _, d in downloads if isinstance(d, bytes) and d.startswith(b'%PDF')]
    assert pdfs
    assert any('ETCO2: 28 to 61 mmHg' in ''.join(p.get_text() for p in fitz.open(stream=d, filetype='pdf')) for d in pdfs)
