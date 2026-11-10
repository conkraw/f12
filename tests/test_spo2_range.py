from style_assert_helpers import without_style_tags
from recovery_helpers import assert_retained
"""SpO2 summary range regressions using synthetic inputs only."""
from copy import deepcopy
from pathlib import Path
import pytest
import fitz

from vitals import parse_vitals, text_by_system
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, SCHEMA_VERSION
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf
from medications import remap, upsert_rule
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
SUMMARY = 'SpO2  Avg: 99.2 %  Min: 93 %  Max: 100 %'


def block(summary=SUMMARY):
    return 'eeeeeeee\nVITALS:\nResp: [16-24] 20\n' + summary + '\neeeeeeee'


def sample_sheet():
    source = (ROOT / 'examples/synthetic_compact_pn.txt').read_text()
    source = source.replace('VITALS:\n', 'VITALS:\n' + SUMMARY + '\n')
    result = import_sections(new_sheet('P4102'), source, new_vault()['settings'])
    assert not result.errors, result.errors
    result.sheet['medications'] = remap(result.sheet['medications'], upsert_rule([], 'dexamethasone', 'Respiratory'))
    # This test isolates respiratory placement after an explicit override.
    for row in result.sheet['medications']:
        if row['section']=='Respiratory': row['group_mode']='other'
    return result.sheet


def test_exact_requested_summary_is_only_the_range():
    result = parse_vitals('VITALS:\n' + SUMMARY)
    assert not result.error and not result.issues
    assert result.rows == [{'label': 'SpO2', 'value': '93% to 100%',
                            'section': 'Respiratory', 'include': True}]
    assert text_by_system(result.rows) == {'Respiratory': 'SpO2: 93% to 100%'}


@pytest.mark.parametrize('source,expected', [
    ('SpO2: Avg: 99.2% Min: 93% Max: 100%', '93% to 100%'),
    ('SPO2 AVG: 99.2 % MIN: 93 % MAX: 100 %', '93% to 100%'),
    ('spo2\tAvg:\t99.2 %\tMin:\t93 %\tMax:\t100 %', '93% to 100%'),
    ('SpO₂\u00a0Avg: 99.2 %\u00a0Min: 93 %\u202fMax: 100 %', '93% to 100%'),
    ('SpO2 (%) Avg: 99.2 Min: 93 Max: 100', '93% to 100%'),
    ('SpO2 (%): Average: 99.2 Minimum: 93 Maximum: 100', '93% to 100%'),
    ('SpO2 Max: 100% Avg: 99.2% Min: 93%', '93% to 100%'),
    ('SpO2 Min: 93% Max: 100%', '93% to 100%'),
    ('SpO2 Avg: 98.42% Min: 93.50% Max: 99.80%', '93.50% to 99.80%'),
    ('SpO2 Avg: 98% Min: 98% Max: 98%', '98% to 98%'),
    ('SpO2 Avg: N/A Min: 0% Max: 100%', '0% to 100%'),
    (' SpO2 Avg: 99.2 % Min: 93 % Min: 93.0 % Max: 100 % ', '93% to 100%'),
])
def test_supported_summary_typography(source, expected):
    result = parse_vitals('VITALS:\n' + source)
    assert not result.error, result.error
    assert result.rows[0]['value'] == expected
    assert result.rows[0]['label'] == 'SpO2'


@pytest.mark.parametrize('source', [
    'SpO2 Avg: 99.2 % Max: 100 %',
    'SpO2 Avg: 99.2 % Min: 93 %',
    'SpO2 Avg: 99.2 %',
    'SpO2 Avg: 99.2 % Min: N/A Max: 100 %',
    'SpO2 Avg: 99.2 % Min: 93 % Max: ',
    'SpO2 Avg: 99.2 % Min: 93 % Min: 92 % Max: 100 %',
    'SpO2 Avg: 99.2 % Min: 93 % Max: 100 % Max: 99 %',
    'SpO2 Avg: 99.2 % Min: 100 % Max: 93 %',
    'SpO2 Avg: 99.2 % Min: 93 % Max: 101 %',
    'SpO2 Avg: 99.2 % Min: -1 % Max: 100 %',
    'SpO2 Avg: 99.2 % Min: 93 Max: 100',
    'SpO2 Min: 93% unexpected words Max: 100%',
])
def test_malformed_summary_never_invents_or_sorts_endpoints(source):
    original = sample_sheet()
    snapshot = deepcopy(original)
    result = import_sections(original, block(source), new_vault()['settings'])
    assert_retained(result, snapshot, "e")
    assert original == snapshot


@pytest.mark.parametrize('source,label,value', [
    ('SpO2: 98 %', 'SpO2', '98 %'),
    ('SpO2 (%): [93 %-100 %] 98 %', 'SpO2 (%)', '[93 %-100 %] 98 %'),
    ('Resp: [12-20] 16', 'Resp', '[12-20] 16'),
    ('Heart Rate Avg: 100 Min: 90 Max: 110', 'Heart Rate Avg', '100 Min: 90 Max: 110'),
    ('BP: (90-120)/(40-70) 100/60', 'BP', '(90-120)/(40-70) 100/60'),
])
def test_other_vital_formats_stay_verbatim(source, label, value):
    result = parse_vitals('VITALS:\n' + source)
    assert not result.error
    assert result.rows[0]['label'] == label
    assert result.rows[0]['value'] == value


def test_resp_range_precedes_support_notes_and_medications():
    sheet = sample_sheet()
    sheet['fields']['Respiratory'] = 'MANUAL_RESP_NOTE'
    text = fields_with_medications(sheet)['Respiratory']
    assert text.index('SpO2: 93% to 100%') < text.index('HFNC') < text.index('MANUAL_RESP_NOTE') < text.casefold().index('dexamethasone')
    for section, content in fields_with_medications(sheet).items():
        if section != 'Respiratory':
            assert 'SpO2: 93% to 100%' not in content
    assert '99.2' not in text and 'Avg:' not in text


def test_epaste_replaces_range_without_erasing_other_sections():
    before = sample_sheet()
    out = import_sections(before, block('SpO2 Avg: 96.2% Min: 91% Max: 99%'), new_vault()['settings'])
    assert not out.errors
    assert len([r for r in out.sheet['vitals'] if r['label'] == 'SpO2']) == 1
    assert '91% to 99%' in fields_with_medications(out.sheet)['Respiratory']
    for key in before:
        if key != 'vitals':
            assert out.sheet[key] == before[key]
    repeated = import_sections(out.sheet, block('SpO2 Avg: 96.2% Min: 91% Max: 99%'), new_vault()['settings'])
    assert repeated.sheet == out.sheet


def test_omitted_e_keeps_range_and_empty_e_clears():
    original = sample_sheet()
    diagnosis = import_sections(original, 'aaaaaaaa\nDiagnoses:\n1. Synthetic update\naaaaaaaa', new_vault()['settings'])
    assert diagnosis.sheet['vitals'] == original['vitals']
    empty = import_sections(original, 'eeeeeeee\nVITALS:\neeeeeeee', new_vault()['settings'])
    assert empty.sheet['vitals'] == []


def test_edit_and_exclude_in_existing_editor(app):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = block()
    app.create_handoff()
    assert not ss['import_result']['errors']
    row = ss['drafts']['P4102']['vitals'][1]
    assert row['value'] == '93% to 100%'
    ss['test_spo2_value'] = '94% to 100%'
    app.vital_row_change('P4102', 1, 'value', 'test_spo2_value')
    assert ss['drafts']['P4102']['vitals'][1]['value'] == '94% to 100%'
    ss['test_spo2_include'] = False
    app.vital_row_change('P4102', 1, 'include', 'test_spo2_include')
    assert 'SpO2' not in fields_with_medications(ss['drafts']['P4102'])['Respiratory']


def test_pdf_html_text_batch_and_encrypted_save():
    sheet = sample_sheet()
    for output in (without_style_tags(without_style_tags(handoff_html(sheet))), handoff_text(sheet)):
        assert 'SpO2: 93% to 100%' in output
        assert '99.2' not in output and 'Avg:' not in output
    with fitz.open(stream=handoff_pdf(sheet), filetype='pdf') as pdf:
        assert len(pdf) == 1
        assert 'SpO2: 93% to 100%' in pdf[0].get_text()
    another = import_sections(new_sheet('P4104'), block(), new_vault()['settings']).sheet
    with fitz.open(stream=handoffs_pdf([sheet, another]), filetype='pdf') as pdf:
        assert len(pdf) == 2
        assert all('SpO2: 93% to 100%' in page.get_text() for page in pdf)
    vault = save_sheet_in(new_vault(), sheet)
    assert vault['schema'] == SCHEMA_VERSION ==34
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault


def test_page_render_uses_existing_vital_editor_and_export(app, monkeypatch):
    open_room(app)
    app.st.session_state['paste'] = block()
    app.create_handoff()
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    pdfs = [d for _, d in downloads if isinstance(d, bytes) and d.startswith(b'%PDF')]
    assert pdfs
    assert any('SpO2: 93% to 100%' in ''.join(p.get_text() for p in fitz.open(stream=d, filetype='pdf')) for d in pdfs)
