from recovery_helpers import assert_retained
"""Synthetic v6 tests. No clinical records or live repository credentials."""
from copy import deepcopy
from pathlib import Path
from io import BytesIO
import json
import pytest
import fitz
from cryptography.fernet import Fernet
from importing import import_sections
from models import (new_sheet, new_vault, validate_sheet, validate_vault, fields_with_medications,
                    save_sheet_in, upgrade_vault)
from labs import (parse_labs, ordered_components, result_cards, labs_text, lactate_text,
                  empty_labs, validate_labs, date_parts, short_date, canonical)
from vitals import parse_vitals, route
from medications import (parse_medications, set_visibility_rule, hidden_for, remap,
                         upsert_rule, visible, validate_visibility)
from batching import available_handoffs
from exports import handoff_pdf, handoff_text, handoff_html, handoffs_pdf
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from migration_helpers import strip_v6_fields

ROOT=Path(__file__).parents[1]
SAMPLE=(ROOT/'examples/synthetic_labs_vitals.txt').read_text()

def wrapped(letter, heading, body):
    return letter*10+'\n'+heading+':\n'+body+'\n'+letter*10

def parsed(body):
    result=parse_labs('LABS:\nLab Results\nComponent\tValue\tDate\n'+body)
    assert not result.error, result.error
    return result.data

def whole():
    result=import_sections(new_sheet('P4102'),SAMPLE,new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


def test_full_import_source_rows_and_retained_blank_override():
    s=whole()
    assert len(s['labs']['rows'])==46
    assert len(s['vitals'])==6
    assert len(s['medications'])==4
    override=next(x for x in s['medications'] if 'Override Pull' in x['name'])
    assert override['dose']==override['route']==override['frequency']==''
    assert not override['hidden'] and override['include'] and override['warnings']


def test_per_component_trees_keep_mixed_prior_dates_visible():
    cards=result_cards(whole()['labs'])
    assert len(cards)==8
    assert [x['kind'] for x in cards[:4]]==['cbc','cbc','bmp','bmp']
    assert cards[1]['rows']['WBC']['date']=='01/02/2026'
    assert cards[1]['rows']['HGB']['date']=='01/03/2026'
    assert cards[3]['rows']['K']['date']=='01/03/2026'
    assert 'GLUCOSE' not in cards[2]['rows']
    assert cards[1]['rows']['HGB']['value']=='8.4 (L)'


def test_same_date_order_is_source_order_without_time():
    data=parsed('K\t3.4 (L)\t01/03/2026\nK\t3.0 (L)\t01/03/2026\nK\t9.9\t01/02/2026')
    assert [r['value'] for r in ordered_components(data)['K']]==['3.4 (L)','3.0 (L)','9.9']
    assert len(result_cards(data))==2
    assert '9.9' not in labs_text(data)
    assert len(data['rows'])==3


def test_dates_sort_descending_not_numeric_value():
    data=parsed('WBC\t9.0\t01/01/2026\nWBC\t2.0\t01/03/2026\nWBC\t3.0\t01/02/2026')
    assert [r['value'] for r in ordered_components(data)['WBC']]==['2.0','3.0','9.0']


def test_times_sort_only_when_available_for_all_on_date():
    data=parsed('K\t3.0\t01/03/2026 0800\nK\t3.4\t01/03/2026 15:00')
    assert ordered_components(data)['K'][0]['value']=='3.4'
    data['rows'][0]['date']='01/03/2026'
    assert ordered_components(data)['K'][0]['value']=='3.0'


@pytest.mark.parametrize('date',['11/5/26','11/05/2026','11/05/2026 13:45','11/05/2026 1345','11/05/2026 1:45 PM'])
def test_supported_dates(date):
    dt,timed=date_parts(date)
    assert dt.year==2026 and dt.month==11
    assert short_date(date).startswith('11/05/26')


@pytest.mark.parametrize('date',['11/32/2026','unknown','01/01/26 99:99','2026-11-05'])
def test_unknown_date_blocks_instead_of_inventing(date):
    assert parse_labs('LABS:\nNA\t139\t'+date).error


def test_flags_and_units_never_calculated_or_removed():
    data=parsed('PHV\t7.19 (LL)\t01/03/2026\nBILITOT\t<0.2\t01/03/2026\nLACTIC ACID\t2.1 mmol/L (H)\t01/03/2026')
    assert '7.19 (LL)' in labs_text(data) and '<0.2' in labs_text(data)
    assert '2.1 mmol/L (H)' in lactate_text(data)


def test_other_labs_and_only_latest_gas_specimen():
    data=parsed('AST\t20\t01/03/2026\nAST\t30\t01/02/2026\nPHA\t7.4\t01/03/2026\nPHV\t7.3\t01/02/2026')
    cards=result_cards(data)
    assert len(cards)==2 and len(cards[0]['rows'])==1
    assert cards[1]['title'].startswith('Gas ART | latest')
    assert not any(c['title'].startswith('Gas VEN') for c in cards)
    assert 'HCO3A' not in cards[1]['rows']
    assert '30 [' not in labs_text(data)


@pytest.mark.parametrize('component',['LACTIC ACID','Lactate','LACTATEVEN','LACTATEART','LACTICACID','LACT'])
def test_lactate_routes_cardiac_only(component):
    s=new_sheet('P4102');s['labs']=parsed(component+'\t1.4\t01/03/2026')
    fields=fields_with_medications(s)
    assert 'Lactate 1.4' in fields['Cardiovascular'] and '; '+component+']' not in fields['Cardiovascular']
    assert component+': 1.4' not in fields['Lab Results / Trends']


def test_missing_lactate_does_not_get_created():
    assert lactate_text(parsed('K\t3.2\t01/03/2026'))==''


def test_no_result_notes_are_not_fake_numeric_labs():
    out=parse_labs('LABS:\nCoagulation Profile:\nNo results found for: "INR", "PT"')
    assert not out.error and out.data['rows']==[] and out.data['notes']


def test_unknown_component_preserved_in_other_panel():
    data=parsed('CUSTOM_ASSAY\t5.5\t01/03/2026')
    assert 'CUSTOM_ASSAY: 5.5' in labs_text(data)


def test_tabless_labs_numeric_boundary():
    data=parsed('WBC  8.20  01/02/2026\nLACTIC ACID  1.4 mmol/L  01/03/2026')
    assert len(data['rows'])==2
    assert data['rows'][1]['component']=='LACTIC ACID'


def test_bad_g_prevents_partial_import_and_preserves_original():
    s=whole();before=deepcopy(s)
    result=import_sections(s,wrapped('e','VITALS','Heart Rate: 100')+'\n'+wrapped('g','LABS','bad unknown source'),new_vault()['settings'])
    assert_retained(result, before, "g")
    assert s==before


def test_blank_g_clears_old_auto_labs_only():
    s=whole();s['fields']['Lab Results / Trends']='Manual note'
    r=import_sections(s,wrapped('g','LABS',''),new_vault()['settings'])
    assert not r.errors and r.sheet['labs']==empty_labs()
    assert r.sheet['fields']['Lab Results / Trends']=='Manual note'
    assert r.sheet['vitals']==s['vitals']


def test_vitals_only_does_not_rewrite_labs_or_support():
    s=whole();r=import_sections(s,wrapped('e','VITALS','Resp: [18-25] 21'),new_vault()['settings'])
    assert r.sheet['labs']==s['labs'] and r.sheet['ventilation']==s['ventilation']
    assert len(r.sheet['vitals'])==1


def test_reimport_replaces_snapshot_without_duplicate_results():
    s=whole();r=import_sections(s,SAMPLE,new_vault()['settings'])
    assert len(r.sheet['labs']['rows'])==len(s['labs']['rows'])
    assert len(r.sheet['vitals'])==6


@pytest.mark.parametrize('label,expected',[
 ('Resp','Respiratory'),('Respiratory Rate','Respiratory'),('Respirations','Respiratory'),
 ('RR','Respiratory'),('SpO2 (%)','Respiratory'),('FiO2 (%)','Respiratory'),
 ('Heart Rate','Cardiovascular'),('BP','Cardiovascular'),('Arterial BP','Cardiovascular'),
 ('MAP','Cardiovascular'),('CVP (mmHg)','Cardiovascular'),('Central Venous Pressure','Cardiovascular'),
 ('Temp','Infectious Disease'),('Temperature','Infectious Disease'),('Tmax','Infectious Disease')])
def test_vital_destinations(label,expected):
    assert route(label)==expected


def test_unknown_vital_not_discarded():
    result=parse_vitals('VITALS:\nCustom value: 42')
    assert not result.error and result.rows[0]['section']=='Other' and result.issues


def test_vital_ranges_verbatim_no_unit_invention():
    value='(90-110)/(40-60) 100/50'
    result=parse_vitals('VITALS:\nBP: '+value)
    assert result.rows[0]['value']==value


def test_vitals_always_before_support_lactate_notes_and_meds():
    s=whole()
    s['fields']['Respiratory']='RESP MANUAL'
    s['fields']['Cardiovascular']='CARDIAC MANUAL'
    s['fields']['Infectious Disease']='ID MANUAL'
    s['medications']=remap(s['medications'],upsert_rule([],'albuterol','Respiratory'))
    f=fields_with_medications(s)
    assert f['Respiratory'].index('Resp:')<f['Respiratory'].index('Mode:')<f['Respiratory'].index('Beta-Agonist')<f['Respiratory'].index('albuterol')<f['Respiratory'].index('RESP MANUAL')
    assert f['Cardiovascular'].index('Heart Rate:')<f['Cardiovascular'].index('Lactate ')<f['Cardiovascular'].index('CARDIAC MANUAL')
    assert f['Infectious Disease'].startswith('Temp:')


def test_klm_blocks_recognized_without_automatic_import():
    s=whole()
    assert all('SBS -1' not in v for v in s['fields'].values())
    r=import_sections(new_sheet('P4102'),SAMPLE,new_vault()['settings'])
    assert not any('outside' in i for i in r.notices)


def test_hide_exact_ads_not_active_albuterol():
    s=whole();ads=next(r for r in s['medications'] if 'Override Pull' in r['name'])
    rules=set_visibility_rule([],ads['name'],True)
    assert hidden_for(ads['name'],rules)
    assert not hidden_for('albuterol continuous nebulizer solution',rules)
    rows=remap(s['medications'],[],rules)
    assert len(rows)==4 and sum(r['hidden'] for r in rows)==1
    s['medications']=rows
    for output in (handoff_text(s),handoff_html(s)):
        assert 'Override Pull' not in output and 'albuterol continuous nebulizer solution' in output
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert 'Override Pull' not in ''.join(p.get_text() for p in doc)
    restored=remap(rows,[],set_visibility_rule(rules,ads['name'],False))
    assert not any(r['hidden'] for r in restored)
    assert restored[1]['name']==ads['name'] and restored[1]['dose']==ads['dose']


def test_hidden_rule_applies_on_future_paste_and_retains_row():
    s=whole();name=s['medications'][0]['name']
    settings=new_vault()['settings'];settings['medication_visibility']=set_visibility_rule([],name,True)
    r=import_sections(new_sheet('P4104'),SAMPLE,settings)
    assert len(r.sheet['medications'])==4 and r.sheet['medications'][0]['hidden']


def test_system_remapping_does_not_unhide():
    s=whole();s['medications'][0]['hidden']=True
    rows=remap(s['medications'],upsert_rule([],'acetaminophen','Neurologic'))
    assert rows[0]['hidden'] and rows[0]['section']=='Neurologic'


def test_visibility_rule_specificity_and_restored_exception():
    rules=set_visibility_rule([],'acetaminophen',True,'prefix')
    rules=set_visibility_rule(rules,'acetaminophen injection 100 mg',False)
    assert hidden_for('acetaminophen tablet 325 mg',rules)
    assert not hidden_for('acetaminophen injection 100 mg',rules)


def test_hide_and_restore_in_ui_persist_rules_only(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    row=ss['drafts']['P4102']['medications'][0]
    app.hide_medication('P4102',row['id'],True,None)
    assert ss['drafts']['P4102']['medications'][0]['hidden']
    assert not ss['vault']['rooms']
    assert ss['vault']['settings']['medication_visibility'][0]['hidden']
    app.change_visibility_rule(row['name'],False,'exact',None)
    assert not ss['drafts']['P4102']['medications'][0]['hidden']


def test_failed_hide_write_is_not_applied(app):
    from github_store import StorageError
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    row=ss['drafts']['P4102']['medications'][0]
    class Store:
        def save(self,*a): raise StorageError('Write rejected')
    app.hide_medication('P4102',row['id'],True,Store())
    assert not ss['drafts']['P4102']['medications'][0]['hidden']
    assert not ss['vault']['settings']['medication_visibility']
    assert ss['notice'][0]=='error'


def test_hidden_rule_admin_without_handoff(app,monkeypatch):
    from test_ui_smoke import equip
    ss=app.st.session_state
    ss['vault']['settings']['medication_visibility']=set_visibility_rule([],'example medication',True)
    equip(app,monkeypatch);app.admin_page(None)
    app.change_visibility_rule('example medication',False,'exact',None)
    assert not ss['vault']['settings']['medication_visibility'][0]['hidden']


def test_lab_date_edit_invalid_rolls_back(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    row=ss['drafts']['P4102']['labs']['rows'][0]
    old=row['date'];ss['edit_date']='nonsense'
    app.lab_row_change('P4102',row['id'],'date','edit_date')
    assert ss['drafts']['P4102']['labs']['rows'][0]['date']==old and ss['edit_date']==old


def test_lab_value_edit_is_persistent_in_draft(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    row=ss['drafts']['P4102']['labs']['rows'][0]
    ss['edit_value']='13.0 (H)';app.lab_row_change('P4102',row['id'],'value','edit_value')
    assert ss['drafts']['P4102']['labs']['rows'][0]['value']=='13.0 (H)'
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['labs']['rows'][0]['value']=='13.0 (H)'


def test_vital_callback_preserves_ranges(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    ss['edit_vital']='[36.8-37.8] 37.2'
    app.vital_row_change('P4102',0,'value','edit_vital')
    assert ss['drafts']['P4102']['vitals'][0]['value']=='[36.8-37.8] 37.2'


def test_source_edit_widgets_scoped_to_rows_and_rooms(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app);ss=app.st.session_state
    app.load_labs_sample();app.create_handoff()
    ads=ss['drafts']['P4102']['medications'][1]
    app.hide_medication('P4102',ads['id'],True,None)
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_v6_encrypted_roundtrip_and_v5_migration():
    s=whole();v=save_sheet_in(new_vault(),s)
    v['settings']['medication_visibility']=set_visibility_rule([],s['medications'][0]['name'],True)
    key=generate_key();token=seal_vault(v,key)
    # Short strings such as WBC can occur by chance in base64 ciphertext.
    # Check structured plaintext markers instead, plus the exact decrypted vault.
    assert b'"component": "WBC"' not in token and b'12.80' not in token and open_vault(token,key)==v
    old=strip_v6_fields(deepcopy(v));old['schema']=5;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old["settings"].pop("medication_gi_groups", None);old['settings'].pop('medication_infusions', None)
    baseline=deepcopy(old)
    oldtoken=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    upgraded=open_vault(oldtoken,key)
    assert upgraded['schema']==32 and old==baseline
    after=upgraded['rooms']['P4102'];before=old['rooms']['P4102']
    for k in ('fields','noninvasive','ventilation','id','updated_at'):
        assert after[k]==before[k]
    assert after['labs']==empty_labs() and after['vitals']==[]
    assert all(r['hidden'] is False for r in after['medications'])


def test_print_all_labs_and_vitals_only_handoffs():
    first=new_sheet('P4102');first['labs']=parsed('NA\t139\t01/03/2026')
    second=new_sheet('P4104');second['vitals']=parse_vitals('VITALS:\nResp: 22').rows
    ready=available_handoffs(new_vault(),{'P4102':first,'P4104':second})
    assert list(ready)==['P4102','P4104']
    doc=fitz.open(stream=handoffs_pdf(list(ready.values())),filetype='pdf')
    assert all(page.rect.width>page.rect.height for page in doc)
    assert any('P4104' in page.get_text() and 'Resp: 22' in page.get_text() for page in doc)


def test_lab_exports_are_dated_and_do_not_leak_hidden_order():
    s=whole();s['medications'][1]['hidden']=True
    pdf=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    text='\n'.join(p.get_text() for p in pdf)
    assert all(p.rect.width==792 and p.rect.height==612 for p in pdf)
    assert '01/03/26' in text and '01/02/26' in text and 'preceding per component' not in text
    assert 'Gas ART' in text and 'Gas VEN' not in text
    assert 'Override Pull' not in text
    for page in pdf:
        for b in page.get_text('blocks'):
            assert b[0]>=0 and b[1]>=0 and b[2]<=page.rect.width+1 and b[3]<=page.rect.height+1
    html=handoff_html(s)
    assert '<svg ' in html and '<line ' in html and '01/03/26' in html


def test_export_escaping_and_long_lab_values_not_lost():
    s=new_sheet('P4102');s['labs']=parsed('CUSTOM\t'+('X'*500)+'\t01/03/2026')
    s['labs']['rows'][0]['value']='<script>alert(1)</script> '+('long-value '*40)+'ENDLABTOKEN'
    html=handoff_html(s)
    assert '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert 'ENDLABTOKEN' in ''.join(p.get_text() for p in doc)


# v6.30: make time-window routing tests independent of the machine's clock.
from datetime import datetime, timezone
from lab_windows import display_clock
@pytest.fixture(autouse=True)
def fixed_routing_clock():
    with display_clock(datetime(2026,1,3,20,0,tzinfo=timezone.utc)):
        yield
