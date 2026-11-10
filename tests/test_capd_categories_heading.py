"""Version 6.43: synthetic inputs, isolated callbacks, and in-memory PDF checks."""
from copy import deepcopy
from io import BytesIO
import re
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from capd import parse_capd, score_text, validate_capd_rows, capd_display_row
from observations import parse_neuro, empty_neuro, neuro_rows
from models import new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault, fields_with_medications, automatic_vitals
from importing import import_sections
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, display_fields, field_markup
from categories import (default_categories, save_category, set_category_rule, apply_category_rules, placement,
                        medication_blocks, add_missing_builtin_categories)
from fen_gi import effective_section, group_for as gi_group, set_gi_rule, apply_gi_rules
from medication_groups import group_for, apply_group_rules, set_group_rule
from security import seal_vault, open_vault
from test_rooms_infusions import med
from test_callbacks import app, open_room
from test_workflow_print import Store


def block(letter, text):
    return letter*20 + '\n' + text + '\n' + letter*20


def imported(text, sheet=None):
    out=import_sections(sheet or new_sheet('P4102'),text,new_vault()['settings'])
    assert not out.errors, out.errors
    return out.sheet


@pytest.mark.parametrize('source,expected',[
    ('CAPD: Cornell Assessment of Pediatric Delirium Score: 24','24'),
    ('CAPD: 0','0'),('CAPD: 32','32'),
    ('CAPD:\nCornell Assessment of Pediatric Delirium Score:\n24','24'),
    ('Cornell Assessment of Pediatric Delirium Score: 9','9'),
    ('capd: cornell assessment of pediatric delirium score: 24','24'),
    ('CAPD total score: 8','8'),('CAPD (0-32): 12','12'),
    ('CAPD:\n12/32','12'),('CAPD\t10','10'),
    ('CAPD: 24\nCAPD: 24','24'),('CAPD:\n0','0'),
    ('CAPD:\r\nCornell Assessment of Pediatric Delirium Score: 24\r\n','24'),
])
def test_explicit_recorded_total_formats(source,expected):
    parsed=parse_capd(source)
    assert not parsed.error and parsed.rows[0]['value']==expected
    sheet=imported(block('y',source))
    assert sheet['neuro_vitals']['y'][0]['value']==expected
    assert 'CAPD: '+expected in automatic_vitals(sheet)['Neurologic']
    validate_sheet(sheet)


@pytest.mark.parametrize('source',['','CAPD:','CAPD:\nNone','CAPD: No data recorded',
    'CAPD: Cornell Assessment of Pediatric Delirium Score:', 'CAPD: Unable to assess',
    'Cornell Assessment of Pediatric Delirium Score:\nNot assessed','CAPD (0-32):'])
def test_empty_or_unassessed_is_none_not_zero(source):
    s=imported(block('y',source))
    assert s['neuro_vitals']['y']==[]
    assert automatic_vitals(s)['Neurologic']=='CAPD: None'


@pytest.mark.parametrize('source',['CAPD: -1','CAPD: 33','CAPD: 2.5','CAPD: 9 to 12',
    'CAPD: 24\nCAPD: 20','CAPD: score not readable','CAPD: 4/24',
    'Pain: 4','CAPD: 24 at 11/08/26 1200','CAPD: <script>24</script>'])
def test_unreadable_or_conflicting_y_does_not_represent_stale_score(source):
    old=imported(block('y','CAPD: 8'));before=deepcopy(old)
    out=import_sections(old,block('y',source)+'\n'+block('k','Target Arousal Level:\nTarget Arousal Level (SBS): SBS 0'),new_vault()['settings'])
    assert out.errors and out.sheet and 'y' in out.skipped
    assert old==before and out.sheet['neuro_vitals']['y']==old['neuro_vitals']['y']
    text=handoff_text(out.sheet)
    assert out.sheet['neuro_vitals']['k'][0]['value']=='SBS 0'
    assert 'SBS 0' not in text and 'CAPD: None' in text and 'CAPD: 8' not in text
    assert 'IMPORT REVIEW' not in text
    assert out.diagnostics[0]['section']=='y'
    assert '24 at' not in str(out.diagnostics) and '<script>' not in str(out.diagnostics)


def test_order_sbs_capd_wat_before_medications_in_all_exports():
    source='\n'.join([block('k','Target Arousal Level:\nTarget Arousal Level (SBS): SBS 0'),
                     block('l','WAT Score:\nWAT-1 total score (0-12): 3'),
                     block('y','CAPD: Cornell Assessment of Pediatric Delirium Score: 24')])
    s=imported(source)
    from sbs_test_helpers import observed
    observed(s, '0')
    s['medications']=[med('midazolam test infusion')]
    before=deepcopy(s)
    outputs=[handoff_text(s), handoff_html(s), '\n'.join(p.extract_text() for p in PdfReader(BytesIO(handoff_pdf(s))).pages)]
    for text in outputs:
        assert text.index('SBS: 0') < text.index('CAPD: 24') < text.index('WAT-1') < text.index('midazolam test infusion')
        assert text.count('CAPD: 24')==1
    assert s==before


def test_default_capd_always_on_old_and_blank_records():
    s=new_sheet('P4102')
    assert 'y' not in s['neuro_vitals']
    for text in (handoff_text(s), handoff_html(s)):
        assert text.count('CAPD: None')==1
    rows=neuro_rows(empty_neuro())
    assert rows==[{'label':'CAPD','value':'None','section':'Neurologic','include':True}]


def test_omitted_y_preserves_but_empty_y_clears_score():
    s=imported(block('y','CAPD: 24'))
    s=imported(block('k','Target Arousal Level:\nSBS 0'),s)
    assert 'CAPD: 24' in handoff_text(s)
    s=imported(block('y','CAPD:'),s)
    assert 'CAPD: None' in handoff_text(s) and 'CAPD: 24' not in handoff_text(s)


def test_zero_distinct_from_none_and_excluded_score():
    s=imported(block('y','CAPD: 0'))
    assert 'CAPD: 0' in handoff_text(s)
    s['neuro_vitals']['y'][0]['include']=False
    assert 'CAPD: None' in handoff_text(s)


def test_y_error_clears_only_after_successful_y_reimport():
    s=imported(block('y','CAPD: 9'))
    s=import_sections(s,block('y','CAPD: invalid'),new_vault()['settings']).sheet
    assert 'y' in s['import_warnings']
    s=imported(block('k','Target Arousal Level:\nSBS 0'),s)
    assert 'y' in s['import_warnings']
    s=imported(block('y','CAPD: 6'),s)
    assert 'y' not in s['import_warnings'] and 'CAPD: 6' in handoff_text(s)


@pytest.mark.parametrize('name,route,target,section',[
    ('diphenhydramine injection','Intravenous','group:allergy_immunology','Respiratory'),
    ('diphenhydrAMINE solution','Per NJ Tube','group:allergy_immunology','Respiratory'),
    ('Benadryl capsule','Oral','group:allergy_immunology','Respiratory'),
    ('erythromycin ethylsuccinate suspension','Per G Tube','gi:prokinetic','FEN / GI'),
    ('erythromycin tablet','Oral','gi:prokinetic','FEN / GI'),
    ('prucalopride tablet','Oral','gi:prokinetic','FEN / GI'),
])
@pytest.mark.parametrize('prefix',['','[START ON 11/9/2026] ','[Held by provider] '])
def test_new_category_defaults_single_destination(name,route,target,section,prefix):
    r=med(prefix+name,dose='2 mg',route=route,frequency='q12h',rate='',section='Other Medications')
    old=deepcopy(r)
    assert placement(r)['id']==target and effective_section(r)==section
    s=new_sheet('P4102');s['medications']=[r]
    out=fields_with_medications(s)
    assert name in out[section]
    for other in ('Neurologic','Respiratory','FEN / GI','Cardiovascular','Infectious Disease','Other Medications'):
        if other != section: assert name not in out[other]
    assert r==old


@pytest.mark.parametrize('name,route',[('erythromycin ophthalmic ointment','Both Eyes'),('erythromycin gel','Topical'),('erythromycin cream','Apply externally'),('erythromycinate','Oral'),('prucalopridex','Oral')])
def test_eye_skin_and_partial_names_not_gi_prokinetic(name,route):
    assert gi_group(med(name,route=route))!='prokinetic'


def test_explicit_erythromycin_id_category_overrides_default():
    settings=set_category_rule(new_vault()['settings'],'erythromycin','system:Infectious Disease')
    r=apply_category_rules([med('erythromycin IVPB',dose='2 mg',frequency='q8h')],settings)[0]
    assert effective_section(r)=='Infectious Disease' and placement(r)['name']==''


def test_new_category_supports_subcategory_move_and_rename():
    s=save_category(new_vault()['settings'],'Motility','FEN / GI',ident='custom:motility')
    s=save_category(s,'Prokinetics','FEN / GI',ident='gi:prokinetic',parent='custom:motility')
    r=apply_category_rules([med('prucalopride tablet',route='Oral',frequency='Daily')],s)[0]
    assert placement(r)['parent_name']=='Motility' and placement(r)['name']=='Prokinetics'


@pytest.mark.parametrize('field',['hidden','include'])
def test_new_categories_respect_hidden_flags(field):
    r=med('diphenhydramine tablet',route='Oral',frequency='Daily');r[field]=(field=='hidden')
    s=new_sheet('P4102');s['medications']=[r]
    assert 'diphenhydramine' not in handoff_text(s)


def test_saved_gi_override_recognizes_prokinetic_without_duplicates():
    r=med('synthetic motility medicine',frequency='Daily')
    r=apply_gi_rules([r],set_gi_rule([],r,'prokinetic'))[0]
    assert placement(r)['id']=='gi:prokinetic'
    assert effective_section(r)=='FEN / GI'


def test_27_archive_adds_only_missing_defaults_and_preserves_customization():
    v=new_vault();v['schema']=27
    settings=save_category(v['settings'],'Custom Beta','Respiratory',ident='group:beta_agonist')
    settings['medication_categories']=[r for r in settings['medication_categories'] if r['id'] not in ('group:allergy_immunology','gi:prokinetic')]
    v['settings']=settings;v['rooms']['P4102']=new_sheet('P4102')
    before=deepcopy(v);u=upgrade_vault(v)
    assert v==before and u['schema']==32 and u['rooms']==before['rooms']
    original={x['id']:x for x in before['settings']['medication_categories']}
    updated={x['id']:x for x in u['settings']['medication_categories']}
    assert all(updated[k]==row for k,row in original.items())
    assert set(updated)-set(original)=={'group:allergy_immunology','gi:prokinetic'}
    validate_vault(u)


def test_existing_custom_category_same_name_not_overwritten_on_upgrade():
    settings=save_category(new_vault()['settings'],'Old custom GI','FEN / GI',ident='custom:existing')
    settings['medication_categories']=[r for r in settings['medication_categories'] if r['id']!='gi:prokinetic']
    for item in settings['medication_categories']:
        if item['id']=='custom:existing': item['name']='Prokinetic Agents'
    new=add_missing_builtin_categories(settings)
    assert next(x for x in new['medication_categories'] if x['id']=='custom:existing')['name']=='Prokinetic Agents'
    assert next(x for x in new['medication_categories'] if x['id']=='gi:prokinetic')['name']=='Prokinetic Agents (default)'


VENT='''Invasive Ventilation:
Mode: Vent Mode: Volume Targeted Pressure Control - PS
Respiratory Rate: Resp Rate (Set): 10
Observed PIP: PIP Observed (cm H2O) Avg: 15.4 cm H2O Min: 15 cm H2O Max: 15.9 cm H2O
Set TV: Vt (Set, mL): 450 mL (safety vt)
Set PEEP: PEEP (cm H2O): 5 cm H2O
Pmin: Pmin: 10 cmH2O
Pmax: Pmax: 20 cmH2O
Timin: Ti Min: 0.9
Timax: Ti Max: 1.2'''


def test_vent_heading_bold_once_below_respiratory_vitals_in_pdf_and_html():
    s=imported(block('c',VENT)+'\n'+block('d','Non-invasive Ventilation:\nO2 Delivery Method: Trach tube\nFiO2 (%): 21 %')+'\n'+block('e','VITALS:\nResp: [10-24] 14'))
    assert s['ventilation']['values']
    text=handoff_text(s)
    assert text.index('Resp:') < text.index('Vent Settings') < text.index('Device: Home Vent')
    assert handoff_html(s).count('<b>Vent Settings</b>')==1
    import fitz
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    hits=[sp for page in doc for b in page.get_text('dict')['blocks'] if 'lines' in b
          for line in b['lines'] for sp in line['spans'] if 'Vent Settings' in sp['text']]
    assert len(hits)==1 and 'Bold' in hits[0]['font']
    doc.close()


def test_no_empty_vent_heading_for_blank_or_hfnc_only():
    assert 'Vent Settings' not in handoff_text(new_sheet('P4102'))
    s=imported(block('c','Invasive Ventilation:\nFiO2 (%): 30 %')+'\n'+block('d','Non-invasive Ventilation:\nO2 Delivery Method: High flow nasal cannula\nFiO2 (%): 30 %\nO2 Flow Rate (L/min): 10 L/min'))
    assert 'HFNC' in handoff_text(s) and 'Vent Settings' not in handoff_text(s)


def test_niv_settings_have_bold_vent_heading():
    s=imported(block('c','Invasive Ventilation:\nVent Mode: Bilevel Non Invasive Ventilation\nFiO2 (%): 30 %')+'\n'+block('d','Non-invasive Ventilation:\nO2 Delivery Method: CPAP/Bi-PAP mask\nTotal Inspiratory Pressure (cm H2O): 10 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 5 cmH20\nFiO2 (%): 30 %'))
    assert '<b>Vent Settings</b>' in handoff_html(s)


def test_save_roundtrip_preserves_capd_and_existing_other_fields():
    v=new_vault();s=imported(block('y','CAPD: 24'));s['updated_at']='2026-11-08T23:00:00+00:00'
    v['rooms']['P4102']=s
    key=Fernet.generate_key().decode()
    restored=open_vault(seal_vault(v,key),key)
    assert restored==v and 'CAPD: 24' in handoff_text(restored['rooms']['P4102'])


def test_print_all_has_one_capd_per_room():
    first=imported(block('y','CAPD: 24'));second=new_sheet('P4104')
    pdf=PdfReader(BytesIO(handoffs_pdf([first,second])))
    text='\n'.join(p.extract_text() for p in pdf.pages)
    assert text.count('CAPD: 24')==1 and text.count('CAPD: None')==1


def test_capd_import_edit_autosave_callbacks(app):
    open_room(app);ss=app.st.session_state
    ss['paste']=block('y','CAPD: 24')
    app.create_handoff()
    s=ss['drafts']['P4102'];assert s['neuro_vitals']['y'][0]['value']=='24'
    key='neuro_'+s['id']+'_y_0';ss[key]='0'
    app.neuro_row_change('P4102','y',0,'value',key)
    assert ss['drafts']['P4102']['neuro_vitals']['y'][0]['value']=='0'
    store=Store();ss['room_choice']='P4104';app.room_changed(store)
    assert store.calls[0][0]['rooms']['P4102']['neuro_vitals']['y'][0]['value']=='0'
    assert 'CAPD: None' in handoff_text(ss['drafts']['P4104'])


def test_placeholder_does_not_make_unused_rooms_printable():
    from batching import available_handoffs
    v=new_vault()
    assert available_handoffs(v,{'P4102':new_sheet('P4102')})=={}
    s=imported(block('y','CAPD:'))
    assert available_handoffs(v,{'P4102':s})=={}
    s=imported(block('y','CAPD: 0'))
    assert set(available_handoffs(v,{'P4102':s}))=={'P4102'}


def test_y_missing_closing_divider_keeps_other_successful_sections():
    old=imported(block('y','CAPD: 24'))
    text=block('k','Target Arousal Level:\nSBS -1')+'\n'+'y'*20+'\nCAPD: 9'
    out=import_sections(old,text,new_vault()['settings'])
    assert out.sheet and out.errors and 'y' in out.sheet['import_warnings']
    assert out.sheet['neuro_vitals']['k'][0]['value']=='SBS -1'
    assert 'SBS -1' not in handoff_text(out.sheet) and 'CAPD: None' in handoff_text(out.sheet)


def test_repeated_y_pairs_reject_cross_patient_paste():
    old=new_sheet('P4102');before=deepcopy(old)
    out=import_sections(old,block('y','CAPD: 24')+'\n'+block('y','CAPD: 0'),new_vault()['settings'])
    assert out.sheet is None and out.errors and old==before
