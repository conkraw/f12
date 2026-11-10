"""6.20: synthetic display regressions. UI/storage use existing local stubs."""
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
import re

import fitz
import pytest
from pypdf import PdfReader

from test_callbacks import app, open_room
from test_rooms_infusions import med
from test_ui_smoke import equip
from test_rooms_infusions import Store
from models import (new_sheet, new_vault, fields_with_medications, validate_vault,
                    save_sheet_in, upgrade_vault, SCHEMA_VERSION)
from infusions import (INFUSION_HEADINGS, is_infusion, supports_infusion_display,
                       respiratory_body, hematology_body, infusion_entry,
                       system_body_blocks, render_body_blocks, infusion_key,
                       set_infusion_rule, apply_infusion_rules)
from fen_gi import effective_section
from exports import (handoff_html, handoff_text, handoff_pdf, handoffs_pdf,
                     handoffs_html, field_markup, print_layout_info)
from labs import parse_labs
from vitals import parse_vitals
from ventilation import parse_ventilation
from medications import upsert_rule, remap
from security import generate_key, open_vault, seal_vault

STAMP = datetime(2027, 1, 4, 20, 0, tzinfo=timezone.utc)


def example():
    s = new_sheet('P4102')
    s['fields']['Diagnoses'] = 'Synthetic infusion-formatting example'
    s['fields']['Respiratory'] = 'Respiratory note'
    s['fields']['Hematology'] = 'Hematology note'
    s['vitals'] = parse_vitals('VITALS:\nResp: [12-24] 18\nSpO2 Avg: 98 % Min: 94 % Max: 100 %\nHeart Rate: 100').rows
    s['ventilation'] = parse_ventilation('Vent Mode: Pressure Control\nResp Rate (Set): 14\nPEEP (cm H2O): 5 cm H2O\nFiO2 (%): 30 %').data
    s['labs'] = parse_labs('LABS:\nComponent\tValue\tDate\nTHEOPH\t12.4\t01/04/2027').data
    s['medications'] = [
        med('aminophylline RESP_IV', dose='0.5 mg/kg/hr (Dosing Weight)', rate='2 mL/hr', section='Respiratory'),
        med('albuterol RESP_CONT', dose='5 mg/hr', route='Nebulization', frequency='Continuous', rate='1 mL/hr', section='Respiratory'),
        med('albuterol RESP_PRN', dose='2.5 mg', route='Nebulization', frequency='q4h PRN', rate='', section='Respiratory'),
        med('heparin HEP_DRIP', dose='10 Units/kg/hr (Dosing Weight)', section='Other Medications'),
        med('cangrelor CANG_DRIP', dose='0.1 mcg/kg/min (Dosing Weight)', section='Other Medications'),
        med('enoxaparin ENOX_INJ', dose='10 mg', route='Subcutaneous', frequency='q12h', rate='', section='Other Medications'),
        med('synthetic HEME_OTHER_DRIP', dose='1 unit/hr', section='Hematology'),
        med('synthetic HEME_TABLET', dose='2 mg', route='Oral', frequency='Daily', rate='', section='Hematology'),
    ]
    return s


@pytest.mark.parametrize('route', ['Nebulization','nebulisation','Nebulized','Nebulised','Inhalation','INHALED','nebulized inhalation','nebulised inhalation'])
def test_continuous_respiratory_route_is_highlighted(route):
    r = med('synthetic respiratory medicine', route=route, section='Respiratory')
    before = deepcopy(r)
    assert is_infusion(r) and supports_infusion_display(r)
    assert 'Respiratory Infusions' in respiratory_body('', [r])
    assert r == before


@pytest.mark.parametrize('freq', ['q4h','q2h PRN','Once','PRN','as needed','Continuous PRN','Continuous as needed','Daily',''])
def test_nebulized_intermittent_or_prn_is_not_inferred_from_product_name_or_pump_rate(freq):
    r = med('synthetic infusion syringe', route='Nebulization', frequency=freq, section='Respiratory')
    assert not is_infusion(r)
    assert 'Respiratory Infusions' not in respiratory_body('', [r])
    assert r['name'] in respiratory_body('', [r])


@pytest.mark.parametrize('section', ['Neurologic','Cardiovascular','Hematology','Other Medications'])
@pytest.mark.parametrize('route', ['Nebulization','Inhalation'])
def test_respiratory_route_extension_does_not_change_other_systems(section, route):
    r = med('synthetic generic', route=route, section=section)
    assert not is_infusion(r)


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
@pytest.mark.parametrize('route', ['Intravenous','IV','Intra-arterial','Subcutaneous'])
def test_existing_continuous_parenteral_recognition_in_new_sections(section, route):
    r = med('synthetic generic', section=section, route=route)
    assert is_infusion(r) and supports_infusion_display(r)
    assert system_body_blocks(section, '', [r])[0] == ('heading', INFUSION_HEADINGS[section])


def test_aminophylline_has_requested_automatic_methylxanthine_default():
    r = med('aminophylline synthetic', section='Other Medications')
    assert is_infusion(r) and supports_infusion_display(r)
    assert 'Methylxanthine' in respiratory_body('', [r])
    mapped = remap([r], upsert_rule([], 'aminophylline', 'Respiratory'))
    assert 'Methylxanthine' in respiratory_body('', mapped)
    assert r['section'] == 'Other Medications'


def test_respiratory_order_vitals_support_theophylline_infusions_notes_other():
    s = example(); before = deepcopy(s)
    text = fields_with_medications(s)['Respiratory']
    tokens = ['Resp:', 'Mode:', 'Beta-Agonist', 'RESP_CONT', 'RESP_PRN', 'Methylxanthine', 'RESP_IV', 'Theophylline level:', 'Respiratory note']
    assert [text.index(t) for t in tokens] == sorted(text.index(t) for t in tokens)
    assert text.count('Theophylline level:') == 1
    assert s == before


def test_dvt_infusions_and_scheduled_injections_share_one_category():
    s = example(); before = deepcopy(s)
    blocks = system_body_blocks('Hematology', s['fields']['Hematology'], s['medications'])
    assert blocks[0] == ('heading','DVT Prophylaxis')
    assert sum(kind == 'heading' and item == 'DVT Prophylaxis' for kind, item in blocks) == 1
    assert next(i for i, (kind, item) in enumerate(blocks) if kind == 'heading' and item == 'Heme Infusions') > next(i for i, (kind, item) in enumerate(blocks) if kind == 'medication' and item['name'] == 'enoxaparin ENOX_INJ')
    drips = [r['name'] for kind, r in blocks if kind == 'infusion']
    assert drips == ['heparin HEP_DRIP', 'cangrelor CANG_DRIP', 'synthetic HEME_OTHER_DRIP']
    injections = [r['name'] for kind,r in blocks if kind == 'medication']
    assert 'enoxaparin ENOX_INJ' in injections
    text = fields_with_medications(s)['Hematology']
    assert text.index('DVT Prophylaxis') < text.index('HEP_DRIP')
    assert text.index('ENOX_INJ') < text.index('Antiplatelet Therapy') < text.index('CANG_DRIP')
    for marker in ['HEP_DRIP','CANG_DRIP','ENOX_INJ','HEME_OTHER_DRIP','HEME_TABLET']:
        assert text.count(marker) == 1
    assert s == before


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
@pytest.mark.parametrize('field', ['hidden','include'])
def test_hidden_or_excluded_infusions_not_printed(section, field):
    s = new_sheet('P4102'); r = med('SECRET_SENTINEL', section=section)
    r[field] = field == 'hidden'; s['medications'] = [r]
    for text in [handoff_html(s), handoff_text(s)]:
        assert 'SECRET_SENTINEL' not in text
        assert INFUSION_HEADINGS[section] not in text


@pytest.mark.parametrize('name', ['heparin weight drip','cangrelor weight drip'])
def test_hidden_dvt_infusions_not_restored_by_grouping(name):
    s = new_sheet('P4102'); r = med(name, dose='10 Units/kg/hr', section='Other Medications')
    r['hidden'] = True; s['medications']=[r]
    assert 'Heme Infusions' not in handoff_html(s)
    assert name not in handoff_text(s)


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_held_start_labels_source_dose_and_distinct_pump_rate_unchanged(section):
    s = new_sheet('P4102')
    r = med('[Held by provider] [START ON 01/04/2027] synthetic <tag>', dose='0.1-2 mcg/kg/min (Dosing Weight)', rate='0 mL/hr', section=section)
    s['medications']=[r]; before = deepcopy(s)
    h=handoff_html(s)
    assert '<b>[Held by provider] [START ON 01/04/2027] synthetic &lt;tag&gt;</b>' in h
    assert '<b><u>Last Admin rate: UNK</u></b>' in h
    assert 'Recorded rate: 0 mL/hr' in h
    assert '(Dosing Weight)' not in h and s == before


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_custom_wording_does_not_get_conflicting_generated_dose(section):
    s=new_sheet('P4102');r=med('synthetic drug',section=section)
    r['custom_text']='Checked <script>example</script> 1 mg/hr (Dosing Weight)'
    s['medications']=[r];before=deepcopy(s);h=handoff_html(s)
    assert '&lt;script&gt;example&lt;/script&gt;' in h and '<script>example</script>' not in h
    assert 'Dose: 1.2' not in h and 'Recorded rate:' not in h
    assert s == before


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_blank_dose_uses_recorded_rate_without_inferred_dose(section):
    s=new_sheet('P4102');r=med('synthetic infusion',dose='',rate='2.1 mL/hr',section=section);s['medications']=[r]
    h=handoff_html(s)
    assert '<b><u>Recorded rate: 2.1 mL/hr</u></b>' in h
    assert 'Dose:' not in h and r['dose']==''


@pytest.mark.parametrize('vitals', [False,True])
@pytest.mark.parametrize('support', [False,True])
@pytest.mark.parametrize('level', [False,True])
@pytest.mark.parametrize('body', [False,True])
def test_rich_respiratory_prefix_matches_plain_for_all_presence_combinations(vitals,support,level,body):
    s=example()
    if not vitals:s['vitals']=[]
    if not support:s['ventilation']=None
    if not level:s['labs']=new_sheet('P4102')['labs']
    if not body:s['fields']['Respiratory']='';s['medications']=[]
    f=fields_with_medications(s)
    h=field_markup(s,f,'Respiratory')
    assert unescape(re.sub(r'<[^>]+>','',h)) == f['Respiratory']


def test_plain_html_pdf_have_all_entries_once_and_rich_emphasis():
    s=example();before=deepcopy(s)
    t=handoff_text(s,STAMP);h=handoff_html(s,STAMP);data=handoff_pdf(s,STAMP)
    p='\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
    for text in (t,h,p):
        for heading in ['Beta-Agonist','Methylxanthine','Heme Infusions','DVT Prophylaxis']:
            assert heading in text
        for marker in ['RESP_IV','RESP_CONT','RESP_PRN','HEP_DRIP','CANG_DRIP','ENOX_INJ','HEME_OTHER_DRIP','HEME_TABLET']:
            assert re.sub(r'\s+', '', text).count(marker)==1
        assert '(Dosing Weight)' not in text
    for name in ['aminophylline RESP_IV','albuterol RESP_CONT','heparin HEP_DRIP','cangrelor CANG_DRIP']:
        assert '<b>'+name+'</b>' in h
    assert '<b><u>Dose: 10 Units/kg/hr</u></b>' in h
    doc=fitz.open(stream=data,filetype='pdf')
    spans=[sp for page in doc for block in page.get_text('dict')['blocks'] if 'lines' in block for li in block['lines'] for sp in li['spans']]
    for marker in ['RESP_IV','RESP_CONT','HEP_DRIP','CANG_DRIP']:
        assert any(marker in sp['text'] and 'Bold' in sp['font'] for sp in spans)
    assert s==before


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_long_infusion_column_paginates_without_dropping_entries(section):
    s=new_sheet('P4102')
    s['medications']=[med(f'LONG_{i}_SENTINEL', section=section) for i in range(28)]
    p=PdfReader(BytesIO(handoff_pdf(s,STAMP)));text=re.sub(r'\s+','',''.join(page.extract_text() for page in p.pages))
    assert len(p.pages)>1
    for i in range(28):assert text.count(f'LONG_{i}_SENTINEL')==1


def test_print_all_starts_new_room_and_preserves_groups():
    a=example();b=example();b['room']='P4104'
    pdf=PdfReader(BytesIO(handoffs_pdf([a,b],STAMP)))
    assert len(pdf.pages)==2
    assert 'P4102' in pdf.pages[0].extract_text() and 'P4104' in pdf.pages[1].extract_text()
    assert handoffs_html([a,b],STAMP).count('<b>Heme Infusions</b>')==2


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_manual_infusion_choice_persists_and_cannot_overwrite_dose(app,section):
    open_room(app);ss=app.st.session_state
    r=med('synthetic choice',frequency='',section=section);ss['drafts']['P4102']['medications']=[r]
    # Preserve the user's system assignment when existing callback reapplies rules.
    ss['vault']['settings']['medication_mappings']=upsert_rule([], 'synthetic choice', section)
    ss['display_choice']='infusion';store=Store()
    app.medication_row_change('P4102',r['id'],'infusion_mode','display_choice',store)
    out=ss['drafts']['P4102']['medications'][0]
    assert out['infusion_mode']=='infusion' and effective_section(out)==section
    assert out['dose']==r['dose'] and out['last_rate']==r['last_rate']
    assert store.saved['rooms']=={} and store.saved['settings']['medication_infusions'][0]['mode']=='infusion'
    assert INFUSION_HEADINGS[section] in fields_with_medications(ss['drafts']['P4102'])[section]


@pytest.mark.parametrize('section', ['Respiratory','Hematology'])
def test_failed_save_keeps_original_display_and_rule(app,section):
    open_room(app);ss=app.st.session_state;r=med('synthetic choice',section=section)
    ss['drafts']['P4102']['medications']=[r];before=deepcopy(r);ss['display_choice']='other'
    app.medication_row_change('P4102',r['id'],'infusion_mode','display_choice',Store(True))
    assert ss['drafts']['P4102']['medications'][0]==before
    assert ss['vault']['settings']['medication_infusions']==[]


def test_manual_other_keeps_dvt_category_without_infusion_heading():
    r=med('heparin weight drip',dose='10 Units/kg/hr',section='Other Medications');r['infusion_mode']='other'
    t=hematology_body('',[r])
    assert 'DVT Prophylaxis' in t and 'Heme Infusions' not in t


def test_infusion_override_does_not_steal_neuro_prn_or_fever_groups():
    for r in [med('fentanyl PRN', frequency='q1h PRN'), med('acetaminophen',frequency='q6h')]:
        r['infusion_mode']='infusion'
        assert not supports_infusion_display(r)
        assert not any(k=='infusion' for k,_ in system_body_blocks('Neurologic','',[r]))


def test_new_controls_render_for_resp_and_heme_including_dvt(app,monkeypatch):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=example()
    equip(app,monkeypatch);labels=[];orig=app.st.selectbox
    def select(label,*args,**kwargs):
        labels.append(label);return orig(label,*args,**kwargs)
    monkeypatch.setattr(app.st,'selectbox',select)
    app.handoff_page(None)
    assert any(x.startswith('Category for order') for x in labels)
    assert any(x.startswith('Infusion emphasis for order') for x in labels)
    for index in (4,5,6):assert f'Category for order {index}' in labels


def test_admin_can_change_choice_without_handoff(app,monkeypatch):
    ss=app.st.session_state;r=med('synthetic resp',section='Respiratory')
    ss['vault']['settings']['medication_infusions']=set_infusion_rule([],r,'other')
    equip(app,monkeypatch);app.admin_page(None)
    ss['edit_mode']='infusion';app.edit_saved_infusion_rule(infusion_key(r),'edit_mode',None)
    assert ss['vault']['settings']['medication_infusions'][0]['mode']=='infusion'
    assert not ss['drafts']


def test_rendering_saved_data_preserves_archive_every_field_and_timestamp():
    v=new_vault();s=example();v=save_sheet_in(v,s)
    v['settings']['medication_infusions']=set_infusion_rule([],s['medications'][1],'other')
    key=generate_key();encrypted=seal_vault(v,key);before=deepcopy(v)
    restored=open_vault(encrypted,key)
    assert restored==before and restored['schema']==33==SCHEMA_VERSION
    for sheet in restored['rooms'].values():
        fields_with_medications(sheet);handoff_html(sheet);handoff_pdf(sheet,STAMP)
    assert restored==before and upgrade_vault(restored)==before


# v6.30: make time-window routing tests independent of the machine's clock.
from datetime import datetime, timezone
from lab_windows import display_clock
@pytest.fixture(autouse=True)
def fixed_routing_clock():
    with display_clock(datetime(2027,1,4,20,0,tzinfo=timezone.utc)):
        yield
