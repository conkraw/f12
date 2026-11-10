"""6.44 synthetic regression cases. No live app or storage calls."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from observations import parse_neuro, neuro_rows, empty_neuro, validate_neuro
from icp_cpp import parse_icp_cpp, display_icp_cpp_rows
from empty_groups import refresh_empty_group_layout, validate_empty_group_layout
from categories import save_category, set_category_rule, apply_category_rules, default_categories, target_snapshot
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, automatic_vitals, upgrade_vault, SCHEMA_VERSION
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from importing import import_sections
from batching import available_handoffs
from security import open_vault, seal_vault
from test_rooms_infusions import med
from test_callbacks import app, open_room


def block(body, letter='m'):
    return letter*18+'\n'+body+'\n'+letter*18


def imported(body, sheet=None):
    result=import_sections(sheet or new_sheet('P4102'),block(body),new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


FORMATS = [
    ('ICP Range: 1-22\nLast ICP: 10','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range: 1 mmHg to 22 mmHg\nLast ICP: ICP Mean (mmHg): 10 mmHg','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range: ICP Mean (mmHg) Avg: 7 Min: 1 mmHg Max: 22 mmHg\nLast ICP: ICP Mean (mmHg): 10 mmHg','ICP: 1-22 [10 mm Hg]'),
    ('CPP Range: CPP Avg: 56 Min: 40 Max: 80\nLast CPP: CPP: 65 mm Hg','CPP: 40-80 [65 mm Hg]'),
    ('ICP Range:\nICP Mean (mmHg) Avg: 12 Min: 1 Max: 22\nLast ICP:\nICP Mean (mmHg): 10 mmHg','ICP: 1-22 [10 mm Hg]'),
    ('CPP Range:\n40-80\nLast CPP:\n65','CPP: 40-80 [65 mm Hg]'),
    ('ICP Range: [1-22] 10 mmHg','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range: [1-22] mmHg\nLast ICP: 10','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range: -2-22\nLast ICP: 0','ICP: -2-22 [0 mm Hg]'),
    ('ICP Range: −2–22\nLast ICP: −1','ICP: -2-22 [-1 mm Hg]'),
    ('ICP Range: -4 to -1\nLast ICP: -2','ICP: -4--1 [-2 mm Hg]'),
    ('ICP Range: 1.5-22.7\nLast ICP: 10.2','ICP: 1.5-22.7 [10.2 mm Hg]'),
    ('ICP Range: 0-0\nLast ICP: 0','ICP: 0-0 [0 mm Hg]'),
    ('ICP Range: 1-22','ICP: 1-22 mm Hg'),
    ('Last CPP: 65 mmHg','CPP: 65 mm Hg'),
    ('ICP Range: No data recorded\nLast ICP: 10','ICP: 10 mm Hg'),
    ('ICP Range: 1-22\nLast ICP:','ICP: 1-22 mm Hg'),
    ('ICP Range: ICP Mean (mm Hg) Max: 22 Min: 1 Avg: 6\nLast ICP: 10','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range:\t1-22\nLast ICP:\t10 mmHg','ICP: 1-22 [10 mm Hg]'),
    ('icp range: 1-22\nlast icp: 10','ICP: 1-22 [10 mm Hg]'),
    ('ICP Range: 1-22\nLast ICP: (!) 10 mmHg','ICP: 1-22 [(!) 10 mm Hg]'),
    ('ICP Range: 1-22\nLast ICP: 30','ICP: 1-22 [30 mm Hg]'),
]

@pytest.mark.parametrize('body,expected',FORMATS)
def test_new_range_and_last_formats(body,expected):
    s=imported(body)
    assert expected in automatic_vitals(s)['Neurologic']
    assert 'Avg:' not in automatic_vitals(s)['Neurologic']
    validate_sheet(s)

@pytest.mark.parametrize('body',[
    'ICP Range: 1-22\nLast ICP: 10\nLast ICP: 11',
    'ICP Range: 22-1\nLast ICP: 10',
    'CPP Range: CPP Avg: 50 Min: 40',
    'ICP Range: ICP Mean (mmHg) Avg: 10',
    'ICP Range: Min: 1 Max: 22 Min: 2',
    'ICP Range: 1-22 kPa',
    'Last CPP: 20 cmH2O',
    'Last ICP: not a value',
    'ICP Range: 1-22\nLast ICP: CPP: 10 mmHg',
    'ICP Range: 1-22\nLast ICP: 1/10/2026',
    'ICP Range: 1-22\nTemperature: 10',
    'ICP Range: 1-22\nLast ICP: nan',
    'CPP Range: 40-80\nLast CPP: 4e2',
    'ICP Range: 1-22\nLast ICP: 10 mg',
])
def test_bad_new_fields_reject_without_printing_retained_last(body):
    original=imported('ICP Range: 1-22\nLast ICP: 10\nCPP Range: 40-80\nLast CPP: 65')
    before=deepcopy(original)
    result=import_sections(original,block(body)+'\n'+block('Diagnoses:\n1. SYNTHETIC updated','a'),new_vault()['settings'])
    assert result.errors and result.sheet['import_warnings'].get('m')
    assert result.sheet['neuro_vitals']['m']==original['neuro_vitals']['m']
    assert 'ICP:' not in automatic_vitals(result.sheet)['Neurologic']
    assert result.sheet['fields']['Diagnoses']=='SYNTHETIC updated' and original==before

@pytest.mark.parametrize('body',[
    'ICP Range:\nLast ICP:\nCPP Range:\nLast CPP:',
    'ICP Range: No data recorded\nLast ICP: --\nCPP Range: None\nLast CPP: N/A',
    'ICP Trends:\nNo data recorded\nICP Range:\nNo data recorded\nLast CPP:',
])
def test_missing_values_do_not_invent_pressures(body):
    s=imported(body)
    assert not s['neuro_vitals']['m']
    assert 'ICP:' not in automatic_vitals(s)['Neurologic']
    assert 'CAPD: None' in automatic_vitals(s)['Neurologic']


def test_equal_repeated_endpoints_and_last_do_not_duplicate():
    s=imported('ICP Range: 1-22\nICP Range: 1.0-22.0\nLast ICP: 10\nLast ICP: 10.0')
    assert len(s['neuro_vitals']['m'])==2
    assert automatic_vitals(s)['Neurologic'].count('ICP:')==1


def test_no_average_substitution_for_missing_last():
    s=imported('ICP Range: ICP Mean (mmHg) Avg: 9 Min: 1 Max: 22\nLast ICP:')
    assert 'ICP: 1-22 mm Hg' in automatic_vitals(s)['Neurologic']
    assert '[' not in automatic_vitals(s)['Neurologic']


def test_import_omission_preserves_empty_clears_and_recovery_clears_warning():
    s=imported('ICP Range: 1-22\nLast ICP: 10')
    r=import_sections(s,block('Target Arousal Level (SBS): SBS 0','k'),new_vault()['settings'])
    assert r.sheet['neuro_vitals']['m']==s['neuro_vitals']['m']
    cleared=imported('ICP Trends:',s)
    assert not cleared['neuro_vitals']['m']
    bad=import_sections(s,block('ICP Range: 22-1'),new_vault()['settings']).sheet
    corrected=imported('ICP Range: 2-9\nLast ICP: 4',bad)
    assert 'm' not in corrected['import_warnings']
    assert 'ICP: 2-9 [4 mm Hg]' in automatic_vitals(corrected)['Neurologic']


def test_older_single_reading_stored_values_unchanged():
    source='ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg'
    rows=parse_neuro(source,'m').rows
    assert rows==[dict(label='ICP Mean (mmHg)',value='5 mmHg',section='Neurologic',include=True),
                  dict(label='CPP',value='72 mmHg',section='Neurologic',include=True)]
    assert display_icp_cpp_rows(rows)==rows


def test_excluded_range_or_last_not_resurrected():
    s=imported('ICP Range: 1-22\nLast ICP: 10')
    s['neuro_vitals']['m'][0]['include']=False
    assert 'ICP: 10 mm Hg' in automatic_vitals(s)['Neurologic']
    s['neuro_vitals']['m'][1]['include']=False
    assert 'ICP:' not in automatic_vitals(s)['Neurologic']


GROUPS=[('group:dvt','Hematology','DVT Prophylaxis','enoxaparin'),
        ('gi:bowel','FEN / GI','Bowel Regimen','sennosides'),
        ('gi:prophylaxis','FEN / GI','GI Prophylaxis','pantoprazole'),
        ('gi:diuretic','FEN / GI','Diuretics','furosemide'),
        ('group:fever','Neurologic','Fever Control','acetaminophen')]

@pytest.mark.parametrize('ident,section,label,name',GROUPS)
def test_empty_groups_show_once_in_correct_system(ident,section,label,name):
    s=new_sheet('P4102');before=deepcopy(s)
    fields=fields_with_medications(s)
    assert fields[section].count(label+': None')==1
    assert all(label+': None' not in v for k,v in fields.items() if k!=section)
    assert s==before

@pytest.mark.parametrize('ident,section,label,name',GROUPS)
def test_populated_group_has_drug_not_none(ident,section,label,name):
    s=new_sheet('P4102');s['medications']=[med(name,'5 mg','Oral','q6h PRN',rate='')]
    text=fields_with_medications(s)[section]
    assert name in text and label+': None' not in text

@pytest.mark.parametrize('ident,section,label,name',GROUPS)
@pytest.mark.parametrize('field',['hidden','include'])
def test_hidden_or_excluded_drug_never_creates_false_none(ident,section,label,name,field):
    s=new_sheet('P4102');r=med(name,'5 mg','Oral','Daily',rate='');r[field]=field=='hidden';s['medications']=[r]
    text=fields_with_medications(s)[section]
    assert name not in text and label+': None' not in text


def test_failed_medication_import_suppresses_none_not_other_content():
    from import_review import diagnostic
    s=new_sheet('P4102');s['fields']['Neurologic']='SYNTHETIC note'
    s['import_warnings']['b']=[diagnostic('b','section_parse_failed',action='not_updated')]
    text=handoff_text(s)
    for _,_,label,_ in GROUPS:assert label+': None' not in text
    assert 'SYNTHETIC note' in text


def test_heparin_flush_does_not_fill_dvt_group():
    s=new_sheet('P4102');s['medications']=[med('heparin flush','10 Units','Intracatheter','q24h',rate='')]
    assert 'DVT Prophylaxis: None' in fields_with_medications(s)['Hematology']


def test_custom_renamed_moved_nested_empty_category_follows_layout():
    settings=new_vault()['settings']
    settings=save_category(settings,'Support','Respiratory',ident='custom:parent',order=3)
    settings=save_category(settings,'Temperature meds','Respiratory','custom:parent','group:fever',order=4)
    s=new_sheet('P4102');refresh_empty_group_layout(s,settings);before=deepcopy(s)
    fields=fields_with_medications(s)
    assert 'Temperature meds: None' in fields['Respiratory'] and 'Support' in fields['Respiratory']
    assert 'Fever Control: None' not in fields['Neurologic']
    assert s==before
    validate_sheet(s)


def test_medication_in_child_counts_as_present_in_required_parent():
    settings=save_category(new_vault()['settings'],'Test subcategory','Hematology',parent='group:dvt',ident='custom:child')
    settings=set_category_rule(settings,'test drug','custom:child')
    s=new_sheet('P4102');s['medications']=apply_category_rules([med('test drug','1 mg','Oral','Daily',rate='')],settings)
    assert 'DVT Prophylaxis: None' not in fields_with_medications(s)['Hematology']
    assert 'test drug' in fields_with_medications(s)['Hematology']


def test_medication_remapping_does_not_duplicate_order():
    settings=set_category_rule(new_vault()['settings'],'acetaminophen','gi:bowel')
    s=new_sheet('P4102');s['medications']=apply_category_rules([med('acetaminophen','1 mg','Oral','q6h',rate='')],settings)
    text=handoff_text(s)
    assert text.count('acetaminophen')==1
    assert 'Fever Control: None' in text and 'Bowel Regimen: None' not in text


def test_default_layout_not_stored_and_custom_layout_roundtrips():
    s=new_sheet('P4102');before=deepcopy(s);settings=new_vault()['settings']
    refresh_empty_group_layout(s,settings);assert s==before
    settings=save_category(settings,'GI Protection','FEN / GI',ident='gi:prophylaxis')
    refresh_empty_group_layout(s,settings);assert len(s['empty_group_layout'])==1
    v=new_vault();v['settings']=settings;v['rooms'][s['room']]=s;key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(v,key),key)==v
    refresh_empty_group_layout(s,new_vault()['settings']);assert s==before


def test_empty_room_not_added_to_print_all_by_placeholders():
    v=new_vault();s=new_sheet('P4102');refresh_empty_group_layout(s,v['settings'])
    assert available_handoffs(v,{'P4102':s})=={}


def test_print_all_refreshes_empty_layout_from_shared_settings():
    v=new_vault();v['settings']=save_category(v['settings'],'GI Protection','FEN / GI',ident='gi:prophylaxis')
    s=new_sheet('P4102');s['fields']['Diagnoses']='SYNTHETIC example';v['rooms']['P4102']=s
    ready=available_handoffs(v,{})
    assert 'GI Protection: None' in handoff_text(ready['P4102'])
    assert 'empty_group_layout' not in v['rooms']['P4102']

@pytest.mark.parametrize('mutator',[lambda x:x.append(deepcopy(x[0])), lambda x:x[0].update(id='custom:bad'),
    lambda x:x[0].update(section='bad'), lambda x:x[0].update(name=''),lambda x:x[0].update(name='a\nb')])
def test_bad_saved_placeholder_layout_rejected(mutator):
    layout=[target_snapshot('group:fever',default_categories())];mutator(layout)
    with pytest.raises(ValueError):validate_empty_group_layout(layout)

@pytest.mark.parametrize('kind',['text','html','pdf'])
def test_all_exports_compact_pressures_and_empty_categories(kind):
    s=imported('ICP Range: 1-22\nLast ICP: 10\nCPP Range: 45-85\nLast CPP: 68')
    if kind=='text':text=handoff_text(s)
    elif kind=='html':text=handoff_html(s).replace('</b>','')
    else:text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(handoff_pdf(s))).pages)
    assert 'ICP: 1-22 [10 mm Hg]' in text and 'CPP: 45-85 [68 mm Hg]' in text
    # A narrow column can wrap a phrase without changing its content.
    compact=' '.join(text.split())
    for _,_,label,_ in GROUPS:assert compact.count(label+': None')==1


def test_two_rooms_never_share_pressures_or_meds():
    a=imported('ICP Range: 1-22\nLast ICP: 10')
    b=imported('CPP Range: 55-90\nLast CPP: 71',new_sheet('P4104'))
    b['medications']=[med('sennosides','2 mL','Oral','Daily',rate='')]
    pages=PdfReader(BytesIO(handoffs_pdf([a,b]))).pages
    assert len(pages)==2
    assert 'ICP: 1-22' in pages[0].extract_text() and 'CPP: 55-90' not in pages[0].extract_text()
    assert 'CPP: 55-90' in pages[1].extract_text() and 'ICP: 1-22' not in pages[1].extract_text()
    assert 'Bowel Regimen: None' in pages[0].extract_text() and 'Bowel Regimen: None' not in pages[1].extract_text()


def test_previous_schema_opens_without_changing_stored_fields():
    old=new_vault();old['schema']=28
    s=imported('ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg');s['updated_at']='2026-11-08T13:00:00+00:00'
    old['rooms']['P4102']=s;before=deepcopy(old)
    key=Fernet.generate_key();cipher=Fernet(key).encrypt(json.dumps(old).encode())
    updated=open_vault(cipher,key.decode())
    assert updated==dict(old,schema=SCHEMA_VERSION) and old==before


def test_callback_import_edit_and_room_switch_save_range(app):
    open_room(app);ss=app.st.session_state
    ss['paste']=block('ICP Range: 1-22\nLast ICP: 10')
    app.create_handoff();s=ss['drafts']['P4102'];assert not ss.get('paste')
    key='synthetic_neuro_change';ss[key]='12 mm Hg'
    app.neuro_row_change('P4102','m',1,'value',key)
    assert 'ICP: 1-22 [12 mm Hg]' in automatic_vitals(ss['drafts']['P4102'])['Neurologic']
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['neuro_vitals']['m'][1]['value']=='12 mm Hg'
    open_room(app,'P4104');assert not ss['drafts']['P4104']['neuro_vitals']['m']


def test_invalid_manual_pressure_edit_does_not_commit(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block('ICP Range: 1-22\nLast ICP: 10')
    app.create_handoff();old=deepcopy(ss['drafts']['P4102']['neuro_vitals'])
    ss['test_key']='99-1 mm Hg';app.neuro_row_change('P4102','m',0,'value','test_key')
    assert ss['drafts']['P4102']['neuro_vitals']==old


def test_category_change_reapplies_placeholder_to_open_room(app):
    open_room(app);ss=app.st.session_state
    ss['vault']['settings']=save_category(ss['vault']['settings'],'GI Protection','FEN / GI',ident='gi:prophylaxis')
    app.reapply_open_mappings()
    assert 'GI Protection: None' in handoff_text(ss['drafts']['P4102'])
