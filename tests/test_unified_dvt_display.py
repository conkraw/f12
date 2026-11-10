"""6.21 display-only regressions. All fixtures are synthetic, not dose guidance."""
from copy import deepcopy
from html import unescape
from io import BytesIO
from itertools import permutations
import re

import fitz
import pytest
from pypdf import PdfReader

from test_rooms_infusions import med
from test_resp_heme_infusions import STAMP
from models import new_sheet, new_vault, save_sheet_in, fields_with_medications
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf, handoffs_html, field_markup
from infusions import system_body_blocks, hematology_body
from medication_groups import set_group_rule, apply_group_rules
from security import generate_key, seal_vault, open_vault


def dvt_rows():
    return [
        med('heparin HEP_SENTINEL infusion', dose='10 Units/kg/hr (Dosing Weight)',
            rate='1.2 mL/hr', section='Other Medications'),
        med('cangrelor CANG_SENTINEL infusion', dose='0.1 mcg/kg/min (Dosing Weight)',
            rate='0.12 mL/hr', section='Other Medications'),
        med('enoxaparin ENOX_SENTINEL injection', dose='10 mg', route='Subcutaneous',
            frequency='q12h', rate='', section='Other Medications'),
    ]


def sheet():
    s = new_sheet('P4102')
    s['fields']['Diagnoses'] = 'Synthetic formatting example'
    s['medications'] = dvt_rows()
    return s


@pytest.mark.parametrize('order', list(permutations(range(3))))
def test_one_group_preserves_order_and_emphasizes_only_infusions(order):
    rows = dvt_rows()
    rows = [rows[i] for i in order]
    before = deepcopy(rows)
    blocks = system_body_blocks('Hematology', '', rows)
    assert blocks[0] == ('heading', 'DVT Prophylaxis')
    assert len(blocks) == 6
    assert [r['id'] for kind, r in blocks if kind in {'medication','infusion'}] == [r['id'] for r in rows if not r['name'].startswith('cangrelor')] + [r['id'] for r in rows if r['name'].startswith('cangrelor')]
    for kind, r in blocks:
        if kind not in {'medication','infusion'}:
            continue
        assert kind == ('medication' if r['name'].startswith('enoxaparin') else 'infusion')
    assert rows == before


def test_exactly_one_dvt_heading_no_heme_heading_for_dvt_only():
    s = sheet()
    for text in [handoff_text(s, STAMP), handoff_html(s, STAMP),
                 PdfReader(BytesIO(handoff_pdf(s, STAMP))).pages[0].extract_text()]:
        text = re.sub(r'\s+', ' ', text)
        assert text.count('DVT Prophylaxis') == 1
        assert 'Heme Infusions' not in text
        for marker in ['HEP_SENTINEL', 'CANG_SENTINEL', 'ENOX_SENTINEL']:
            assert text.count(marker) == 1


def test_heparin_name_and_dose_emphasized_under_dvt_in_html_and_pdf():
    s = sheet()
    h = handoff_html(s, STAMP)
    assert h.index('<b>DVT Prophylaxis</b>') < h.index('<b>heparin HEP_SENTINEL infusion</b>')
    assert '<b><u>Dose: 10 Units/kg/hr</u></b>' in h
    assert 'Recorded rate: 1.2 mL/hr' in h
    assert '<b>enoxaparin ENOX_SENTINEL injection' not in h
    with fitz.open(stream=handoff_pdf(s, STAMP), filetype='pdf') as doc:
        spans = [sp for page in doc for block in page.get_text('dict')['blocks']
                 if 'lines' in block for line in block['lines'] for sp in line['spans']]
        assert any('HEP_SENTINEL' in sp['text'] and 'Bold' in sp['font'] for sp in spans)
        assert any('Dose: 10 Units/kg/hr' in sp['text'] and 'Bold' in sp['font'] for sp in spans)
        assert any('ENOX_SENTINEL' in sp['text'] and 'Bold' not in sp['font'] for sp in spans)


@pytest.mark.parametrize('mode,kind', [('auto', 'infusion'), ('infusion', 'infusion'), ('other', 'medication')])
def test_saved_infusion_style_choice_does_not_move_order_out_of_dvt(mode, kind):
    r = dvt_rows()[0]
    r['infusion_mode'] = mode
    b = system_body_blocks('Hematology', '', [r])
    assert b == [('heading', 'DVT Prophylaxis'), (kind, r)]


@pytest.mark.parametrize('frequency,route,kind', [('Continuous', 'Intravenous', 'infusion'),
                                                ('Daily', 'Oral', 'medication')])
def test_explicit_user_dvt_assignment_kept_alongside_automatic_entries(frequency, route, kind):
    r = med('synthetic USER_DVT order', route=route, frequency=frequency, section='Neurologic')
    rules = set_group_rule([], r, 'dvt')
    rows = apply_group_rules([r], rules) + dvt_rows()
    b = system_body_blocks('Hematology', '', rows)
    assert b[0] == ('heading', 'DVT Prophylaxis')
    assert b[1] == (kind, rows[0])
    assert len([x for x in b if x[0] == 'heading']) == 2
    assert len(b) == 7


def test_non_dvt_infusion_not_folded_into_dvt_group():
    rows = dvt_rows() + [med('synthetic NON_DVT infusion', section='Hematology')]
    b = system_body_blocks('Hematology', 'Heme notes', rows)
    assert [x for x in b if x[0] == 'heading'] == [('heading', 'DVT Prophylaxis'), ('heading', 'Antiplatelet Therapy'), ('heading', 'Heme Infusions')]
    h = hematology_body('Heme notes', rows)
    assert h.index('ENOX_SENTINEL') < h.index('Heme Infusions') < h.index('NON_DVT') < h.index('Heme notes')


@pytest.mark.parametrize('field,value', [('hidden', True), ('include', False)])
def test_hidden_and_excluded_orders_are_not_brought_back(field, value):
    rows = dvt_rows()
    for r in rows:
        r[field] = value
    assert system_body_blocks('Hematology', '', rows) == []


def test_manual_no_special_group_choice_is_not_overridden():
    r = dvt_rows()[0]
    r['group_mode'] = 'other'
    r['section'] = 'Hematology'
    b = system_body_blocks('Hematology', '', [r])
    assert b[0] == ('heading', 'Heme Infusions')
    assert 'DVT Prophylaxis' not in hematology_body('', [r])


def test_custom_wording_and_source_values_unchanged():
    s = sheet()
    r = s['medications'][0]
    r['custom_text'] = '[Held by provider] Checked heparin <note> (Dosing Weight)'
    before = deepcopy(s)
    h = handoff_html(s, STAMP)
    assert '<b>[Held by provider] Checked heparin &lt;note&gt;</b>' in h
    assert 'Dose: 10 Units/kg/hr' not in h
    assert 'Recorded rate: 1.2 mL/hr' not in h
    assert 'DVT Prophylaxis' in h and s == before


def test_plain_and_rich_hematology_output_match():
    s = sheet()
    s['fields']['Hematology'] = 'Manually entered notes'
    f = fields_with_medications(s)
    h = field_markup(s, f, 'Hematology')
    assert unescape(re.sub(r'<[^>]+>', '', h)) == f['Hematology']


def test_dvt_print_all_and_long_group_preserve_every_order():
    a, b = sheet(), sheet()
    b['room'] = 'P4104'
    packet = PdfReader(BytesIO(handoffs_pdf([a, b], STAMP)))
    assert len(packet.pages) == 2
    assert handoffs_html([a, b], STAMP).count('<b>DVT Prophylaxis</b>') == 2
    assert 'Heme Infusions' not in handoffs_html([a, b], STAMP)
    for page, room in zip(packet.pages, ['P4102', 'P4104']):
        text = re.sub(r'\s+', '', page.extract_text())
        assert room in text
        for marker in ['HEP_SENTINEL', 'CANG_SENTINEL', 'ENOX_SENTINEL']:
            assert text.count(marker) == 1
    a['medications'] = [med('heparin LONG_DVT_' + str(i) + '_END',
                            dose='10 Units/kg/hr', section='Hematology') for i in range(30)]
    pdf = PdfReader(BytesIO(handoff_pdf(a, STAMP)))
    assert len(pdf.pages) > 1
    text = re.sub(r'\s+', '', ''.join(p.extract_text() for p in pdf.pages))
    for i in range(30):
        assert text.count('LONG_DVT_' + str(i) + '_END') == 1


def test_saved_archive_mapping_timestamp_and_values_unchanged_after_rendering():
    v = save_sheet_in(new_vault(), sheet())
    before = deepcopy(v)
    key = generate_key()
    restored = open_vault(seal_vault(v, key), key)
    for s in restored['rooms'].values():
        handoff_html(s, STAMP)
        handoff_pdf(s, STAMP)
        handoff_text(s, STAMP)
    assert restored == before
