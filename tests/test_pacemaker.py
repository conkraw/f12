"""Synthetic W-parser, import, save and export regression cases."""
from copy import deepcopy
from io import BytesIO
import json
import re
import pytest
from pypdf import PdfReader
from pacemaker import (parse_pacemaker, format_pacemaker, pacemaker_text,
                       validate_pacemaker, normalize_rate)
from models import new_sheet, new_vault, validate_sheet, save_sheet_in, upgrade_vault, SCHEMA_VERSION, fields_with_medications
from importing import import_sections
from parser import parse_smartphrase
from batching import available_handoffs
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf
from import_review import review_summary
from security import generate_key, seal_vault, open_vault
from error_store import new_error_event
from test_callbacks import app, open_room
from test_ui_smoke import equip

BODY = 'Pacemaker:\n\t01/02/26 2000\nPacemaker\nPacemaker\tYes\nPacemaker Type\tTransthoracic\nPacer Mode\tAAI\nTemporary Wires\tEpicardial\nAtrial Rate (beats/min)\t140 BPM\nAtrial Output (milliamps)\t10 milliamps'

def block(body=BODY, letter='w'):
    return letter*12+'\n'+body+'\n'+letter.upper()*12

def imported(body=BODY, sheet=None):
    r=import_sections(sheet or new_sheet('P4102'),block(body),new_vault()['settings'])
    assert not r.errors,r.errors
    return r.sheet


def test_tabular_example_extracts_mode_and_atrial_rate_only():
    r=parse_pacemaker(BODY)
    assert not r.error and not r.issues and not r.diagnostics
    assert format_pacemaker(r.data)=='Pacemaker: AAI at 140 bpm'
    assert 'milliamps' not in json.dumps(r.data) and 'Transthoracic' not in json.dumps(r.data)

@pytest.mark.parametrize('mode,field,expected',[
    ('AAI','Atrial','AAI at 140 bpm'),('AOO','Atrial','AOO at 140 bpm'),
    ('AAIR','Atrial','AAIR at 140 bpm'),('VVI','Ventricular','VVI at 140 bpm'),
    ('VOO','Ventricular','VOO at 140 bpm'),('VVIR','Ventricular','VVIR at 140 bpm'),
])
@pytest.mark.parametrize('sep',['\t',': ','  '])
def test_mode_matching_rate(mode,field,expected,sep):
    r=parse_pacemaker('Pacemaker'+sep+'Yes\nPacer Mode'+sep+mode+'\n'+field+' Rate (beats/min)'+sep+'140 BPM')
    assert not r.error
    assert format_pacemaker(r.data)=='Pacemaker: '+expected

@pytest.mark.parametrize('body',['','Pacemaker:','Pacemaker:\nNo data recorded','Pacemaker:\nNone','Pacemaker\tNo',BODY.replace('Pacemaker\tYes','Pacemaker\tNo')])
def test_empty_or_no_pacemaker_clears_display(body):
    r=parse_pacemaker(body)
    assert not r.error and r.data is None
    s=imported(body,imported());assert s['pacemaker'] is None
    assert not pacemaker_text(s)

@pytest.mark.parametrize('state',['Off','Standby'])
def test_explicit_inactive_state_never_prints_active_rate(state):
    r=parse_pacemaker(BODY+'\nPacer Status\t'+state)
    assert not r.error and format_pacemaker(r.data)=='Pacemaker: '+state


def test_atrial_and_ventricular_fields_are_not_swapped():
    r=parse_pacemaker(BODY+'\nVentricular Rate (beats/min)\t80 BPM')
    assert format_pacemaker(r.data)=='Pacemaker: AAI at 140 bpm'
    r=parse_pacemaker(BODY.replace('AAI','VVI')+'\nVentricular Rate (beats/min)\t80 BPM')
    assert format_pacemaker(r.data)=='Pacemaker: VVI at 80 bpm'


def test_missing_atrial_rate_does_not_use_ventricular_or_vitals():
    r=parse_pacemaker('Pacemaker\tYes\nPacer Mode\tAAI\nVentricular Rate (beats/min)\t90 BPM\nHeart Rate\t140\nAtrial Output (milliamps)\t10')
    assert not r.error and r.diagnostics
    assert format_pacemaker(r.data)=='Pacemaker: AAI | Rate: UNK'


def test_missing_mode_retains_explicit_chamber_not_inferred_code():
    r=parse_pacemaker('Pacemaker\tYes\nVentricular Rate (beats/min)\t95 BPM')
    assert format_pacemaker(r.data)=='Pacemaker: Mode UNK | Ventricular rate: 95 bpm'
    assert r.diagnostics


def test_generic_rate_is_used_without_heart_rate_fallback():
    r=parse_pacemaker('Pacer Mode: VVI\nRate (beats/min): 90\nHeart Rate: 180')
    assert format_pacemaker(r.data)=='Pacemaker: VVI at 90 bpm'


def test_dual_chamber_rates_stay_labelled_when_different():
    r=parse_pacemaker(BODY.replace('AAI','DDD')+'\nVentricular Rate (beats/min)\t90 BPM')
    assert format_pacemaker(r.data)=='Pacemaker: DDD | Atrial rate: 140 bpm | Ventricular rate: 90 bpm'


def test_dual_chamber_equal_rates_can_be_compact():
    r=parse_pacemaker(BODY.replace('AAI','DDD')+'\nVentricular Rate (beats/min)\t140 BPM')
    assert format_pacemaker(r.data)=='Pacemaker: DDD at 140 bpm'

@pytest.mark.parametrize('extra',['Pacer Mode\tVVI','Atrial Rate (beats/min)\t120 BPM','Pacer Rate\t120 BPM'])
def test_conflicts_fail_only_w_and_hide_retained_snapshot(extra):
    before=imported();original=deepcopy(before)
    text=block('Diagnoses:\n1. Synthetic updated diagnosis','a')+'\n'+block(BODY+'\n'+extra)
    r=import_sections(before,text,new_vault()['settings'])
    assert r.errors and r.skipped==['w']
    assert before==original and r.sheet['pacemaker']==before['pacemaker']
    assert r.sheet['fields']['Diagnoses']=='Synthetic updated diagnosis'
    assert not pacemaker_text(r.sheet) and 'prior pacemaker settings hidden' in review_summary(r.sheet)
    assert 'AAI at 140' not in handoff_text(r.sheet)
    payload=json.dumps(new_error_event(r.diagnostics))
    assert '"140"' not in payload and 'AAI' not in payload

@pytest.mark.parametrize('rate',['ten','140 | 150','10 milliamps','140-160','-1','<script>'])
def test_unreadable_rate_not_guessed(rate):
    assert parse_pacemaker(BODY.replace('140 BPM',rate)).error

@pytest.mark.parametrize('rate',['0','140.5','140 bpm','140 beats/min','(S) 140 BPM'])
def test_rate_normalization_retains_documented_number(rate):
    assert normalize_rate(rate) in ('0','140.5','140')


def test_w_case_insensitive_and_independent_update():
    s=imported();s['fields']['Cardiovascular']='MANUAL CV NOTES'
    s['fields']['Respiratory']='MANUAL RESP NOTES'
    before=deepcopy(s)
    r=import_sections(s,block(BODY.replace('140 BPM','135 BPM')).upper(),new_vault()['settings'])
    assert not r.errors and pacemaker_text(r.sheet)=='Pacemaker: AAI at 135 bpm'
    for key in before:
        if key!='pacemaker':assert r.sheet[key]==before[key]
    r2=import_sections(r.sheet,block('Diagnoses:\n1. Example','a'),new_vault()['settings'])
    assert r2.sheet['pacemaker']==r.sheet['pacemaker']


def test_malformed_w_preserves_other_imports():
    text=block('Diagnoses:\n1. Example','a')+'\n'+'w'*12+'\n'+BODY
    r=import_sections(imported(),text,new_vault()['settings'])
    assert r.errors and r.sheet['fields']['Diagnoses']=='Example'
    assert not pacemaker_text(r.sheet)


def test_pacing_position_below_vitals_before_infusions_and_notes():
    s=imported()
    s['fields']['Cardiovascular']='SYNTHETIC CV NOTE'
    r=import_sections(s,block('VITALS:\nHeart Rate: [90-150] 140\nBP: 100/60\nCVP (mean): 8 mmHg','e'),new_vault()['settings'])
    assert not r.errors
    s=r.sheet
    for text in [fields_with_medications(s)['Cardiovascular'], handoff_html(s)]:
        assert text.index('CVP')<text.index('Pacemaker: AAI at 140 bpm')<text.index('SYNTHETIC CV NOTE')
    assert '<b>Pacemaker: AAI at 140 bpm</b>' in handoff_html(s)
    pdf=PdfReader(BytesIO(handoff_pdf(s)))
    assert len(pdf.pages)==1
    assert 'Pacemaker: AAI at 140 bpm' in re.sub(r'\s+', ' ', pdf.pages[0].extract_text())


def test_hidden_pacer_not_in_any_export_but_stored():
    s=imported();s['pacemaker']['include']=False
    assert not pacemaker_text(s)
    assert 'AAI at 140' not in handoff_text(s)
    assert 'AAI at 140' not in handoff_html(s)
    assert s['pacemaker']['atrial_rate']=='140'


def test_pacer_only_room_in_print_all_and_no_cross_room_mix():
    a=imported();b=imported(BODY.replace('AAI','VVI').replace('Atrial Rate','Ventricular Rate').replace('140 BPM','90 BPM'));b['room']='P4104'
    ready=available_handoffs(new_vault(),{'P4102':a,'P4104':b})
    assert len(ready)==2
    pdf=PdfReader(BytesIO(handoffs_pdf(list(ready.values()))))
    assert len(pdf.pages)==2
    assert 'AAI at 140' in re.sub(r'\s+', ' ', pdf.pages[0].extract_text()) and 'VVI at 90' not in re.sub(r'\s+', ' ', pdf.pages[0].extract_text())
    assert 'VVI at 90' in re.sub(r'\s+', ' ', pdf.pages[1].extract_text())


def test_schema20_migration_preserves_all_prior_data():
    v=save_sheet_in(new_vault(),new_sheet('P4102'));v['schema']=20
    v['rooms']['P4102'].pop('pacemaker');v['rooms']['P4102'].pop("diet", None);before=deepcopy(v)
    m=upgrade_vault(v)
    assert m['schema']==SCHEMA_VERSION==33 and v==before
    assert m['rooms']['P4102']==dict(before['rooms']['P4102'],pacemaker=None,diet=None)
    assert m['settings']==v['settings'] and m['reset_generation']==v['reset_generation']


def test_encrypted_round_trip_includes_pacer():
    v=save_sheet_in(new_vault(),imported());k=generate_key()
    encrypted=seal_vault(v,k)
    # A three-character fragment can occur by chance in base64 ciphertext.
    assert b'\"mode\": \"AAI\"' not in encrypted
    assert open_vault(encrypted,k)==v


def test_callbacks_capture_pending_edit_autosave_new_room(app):
    open_room(app);ss=app.st.session_state;app.set_editor('P4102',imported())
    s=ss['drafts']['P4102'];key='pacer_'+s['id']+'_atrial_rate'
    ss[key]='145'
    app.pacemaker_change('P4104','atrial_rate',key)
    assert s['pacemaker']['atrial_rate']=='140'
    app.pacemaker_change('P4102','atrial_rate',key)
    assert ss['drafts']['P4102']['pacemaker']['atrial_rate']=='145'
    ss[key]='150'
    open_room(app,'P4104')
    assert ss['vault']['rooms']['P4102']['pacemaker']['atrial_rate']=='150'
    assert ss['drafts']['P4104']['pacemaker'] is None and key not in ss


def test_invalid_callback_retains_value(app):
    open_room(app);app.set_editor('P4102',imported());ss=app.st.session_state
    s=ss['drafts']['P4102'];key='pacer_'+s['id']+'_atrial_rate';ss[key]='bad'
    app.pacemaker_change('P4102','atrial_rate',key)
    assert ss[key]=='140' and ss['drafts']['P4102']['pacemaker']['atrial_rate']=='140'


def test_new_patient_clears_old_pacing(app):
    open_room(app);app.set_editor('P4102',imported());app.start_new_patient()
    assert app.st.session_state['drafts']['P4102']['pacemaker'] is None


def test_editor_smoke(app,monkeypatch):
    equip(app,monkeypatch);open_room(app);app.set_editor('P4102',imported())
    app.pacemaker_editor(app.st.session_state['drafts']['P4102'])


def test_unknown_source_values_escaped_in_html():
    s=imported();s['pacemaker']['mode']='<script>unsafe</script>'
    assert '<script>unsafe' not in handoff_html(s)
    assert '&lt;script&gt;' in handoff_html(s)

@pytest.mark.parametrize('field,value',[('mode',None),('status','random'),('include','yes'),('rate','10 mA')])
def test_model_rejects_invalid_pacer(field,value):
    s=imported();s['pacemaker'][field]=value
    with pytest.raises(ValueError):validate_sheet(s)


def test_session20_migration_keeps_saved_and_unsaved_notes(app):
    open_room(app)
    ss=app.st.session_state
    app.save_room(None)
    ss['vault']['schema']=20
    for sheet in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):
        sheet.pop('pacemaker');sheet.pop("diet", None)
    ss['drafts']['P4102']['fields']['Cardiovascular']='Unsaved synthetic note'
    old_saved=ss['vault']['rooms']['P4102']['updated_at']
    app.upgrade_existing_session()
    assert ss['vault']['schema']==33
    assert ss['drafts']['P4102']['pacemaker'] is None
    assert ss['drafts']['P4102']['fields']['Cardiovascular']=='Unsaved synthetic note'
    assert ss['vault']['rooms']['P4102']['updated_at']==old_saved


def test_pacer_content_same_across_text_html_pdf_after_manual_edit():
    s=imported();s['pacemaker']['atrial_rate']='145'
    assert 'Pacemaker: AAI at 145 bpm' in handoff_text(s)
    assert 'Pacemaker: AAI at 145 bpm' in handoff_html(s)
    text=PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()
    assert 'Pacemaker: AAI at 145 bpm' in re.sub(r'\s+',' ',text)
