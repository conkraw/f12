"""Room autosave and print presentation regressions. Uses synthetic data only."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time
import pytest
import fitz

from test_callbacks import app, open_room
from test_ui_smoke import equip
from models import new_sheet, new_vault, save_sheet_in, validate_sheet, fields_with_medications, upgrade_vault
from github_store import StorageError, ConflictError
from medications import parse_medications, destination_for
from cultures import parse_cultures, cultures_text
from viral import parse_viral_panel, viral_text
from microbiology_display import culture_markup, viral_markup, is_organism_result
from exports import handoff_pdf, handoffs_pdf, handoff_html, handoffs_html, handoff_text, download_payload
from print_time import eastern_print_time, PRINT_TIME_SCRIPT
from security import seal_vault, open_vault
from cryptography.fernet import Fernet


class Store:
    def __init__(self, failure=None, state=None):
        self.calls=[]
        self.failure=failure
        self.state=state
    def save(self, candidate, sha):
        # A switch must not change the active room before storage acknowledges.
        if self.state is not None:
            assert self.state['current_room']=='P4102'
        self.calls.append((deepcopy(candidate),sha))
        if self.failure:
            raise self.failure
        return 'updated-sha'


def change_room(app, store=None, target='P4104'):
    app.st.session_state['room_choice']=target
    app.room_changed(store)


def clinical_sheet(room='P4102'):
    s=new_sheet(room)
    s['fields']['Diagnoses']='Synthetic example'
    s['vitals']=[{'label':'Temperature','value':'37.2 C','section':'Infectious Disease','include':True}]
    # Use the public parser for the actual vital record schema.
    from vitals import parse_vitals
    s['vitals']=parse_vitals('VITALS:\nTemp: 37.2 C').rows
    s['cultures']=parse_cultures('''CULTURES:
Collected\tSpecimen Info\tOrganism
01/04/26\tBlood, Venous\tNo growth (Preliminary)
01/03/26\tSwab from Pericardium\tCandida parapsilosis
\t\tStaphylococcus aureus
''').data
    s['viral_panel']=parse_viral_panel('''Respiratory Viral Panel:
Component\tValue\tDate
HUMRHINENRNA\tDetected (A)\t01/03/2026
RESPSYNVRNA\tNot Detected\t01/03/2026
''').data
    validate_sheet(s)
    return s


def test_autosave_writes_outgoing_room_then_opens_target(app):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='Synthetic outgoing'
    ss['vault_sha']='old-sha'
    store=Store(state=ss)
    change_room(app,store)
    assert len(store.calls)==1 and store.calls[0][1]=='old-sha'
    assert store.calls[0][0]['rooms']['P4102']['fields']['Diagnoses']=='Synthetic outgoing'
    assert 'P4104' not in store.calls[0][0]['rooms']
    assert ss['current_room']==ss['room_choice']=='P4104'
    assert ss['vault_sha']=='updated-sha'
    assert ss['base_sheets']['P4102']==ss['vault']['rooms']['P4102']
    assert ss['drafts']['P4104']['fields']['Diagnoses']==''


@pytest.mark.parametrize('failure',[StorageError('Network unavailable'),ConflictError('Changed elsewhere'),RuntimeError('Simulated unexpected failure')])
def test_failed_autosave_keeps_room_draft_widgets_and_pending_paste(app,failure):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='Keep these results'
    key=app.edit_key(ss['drafts']['P4102'],'Neurologic')
    ss[key]='Last-second edit'
    ss['paste']='Synthetic unimported text'
    original=deepcopy(ss['vault'])
    change_room(app,Store(failure))
    assert ss['current_room']==ss['room_choice']=='P4102'
    assert ss['drafts']['P4102']['fields']['Diagnoses']=='Keep these results'
    assert ss[key]=='Last-second edit' and ss['paste']=='Synthetic unimported text'
    assert ss['vault']==original and 'P4104' not in ss['drafts']
    assert ss['notice'][0]=='error'


def test_retry_after_failed_save_keeps_pending_edit(app):
    open_room(app)
    ss=app.st.session_state
    key=app.edit_key(ss['drafts']['P4102'],'Neurologic')
    ss[key]='Captured on retry'
    change_room(app,Store(StorageError('Offline')))
    store=Store()
    change_room(app,store)
    assert ss['current_room']=='P4104'
    assert ss['vault']['rooms']['P4102']['fields']['Neurologic']=='Captured on retry'


def test_stale_base_blocks_room_switch_without_network_write(app):
    open_room(app)
    ss=app.st.session_state
    other=new_sheet('P4102')
    other['fields']['Diagnoses']='Saved elsewhere'
    ss['vault']=save_sheet_in(ss['vault'],other)
    store=Store()
    change_room(app,store)
    assert not store.calls and ss['current_room']==ss['room_choice']=='P4102'
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses']=='Saved elsewhere'


def test_unchanged_room_does_not_write_again(app):
    open_room(app)
    store=Store()
    app.save_room(store)
    store.calls.clear()
    change_room(app,store)
    assert not store.calls and app.st.session_state['current_room']=='P4104'


def test_same_room_selection_does_not_save_or_clear(app):
    open_room(app)
    app.st.session_state['paste']='Pending synthetic text'
    store=Store()
    change_room(app,store,'P4102')
    assert not store.calls and app.st.session_state['paste']=='Pending synthetic text'


@pytest.mark.parametrize('target',['Other room','Choose a room'])
def test_special_room_choice_saves_before_hiding_editor(app,target):
    open_room(app)
    app.st.session_state['drafts']['P4102']['fields']['Diagnoses']='Current synthetic record'
    store=Store()
    change_room(app,store,target)
    assert len(store.calls)==1
    assert app.st.session_state['room_choice']==target


@pytest.mark.parametrize('target',['Other room','Choose a room'])
def test_special_room_choice_restored_on_failure(app,target):
    open_room(app)
    change_room(app,Store(StorageError('No connection')),target)
    assert app.st.session_state['room_choice']=='P4102'


def test_custom_room_switch_uses_same_save_path(app):
    open_room(app)
    ss=app.st.session_state
    ss.update(room_choice='Other room',other_room='p4301')
    store=Store()
    app.open_room(store)
    assert ss['current_room']=='P4301' and len(store.calls)==1


def test_session_only_mode_is_labelled_without_claim_of_github_save(app):
    open_room(app)
    change_room(app)
    assert app.st.session_state['current_room']=='P4104'
    assert 'session only' in app.st.session_state['notice'][1]


def test_expired_room_callback_cannot_write(app):
    open_room(app)
    app.st.session_state['last_activity']=time.monotonic()-1001
    store=Store()
    change_room(app,store)
    assert not store.calls and not app.st.session_state


def test_invalid_pending_value_does_not_move_room(app):
    open_room(app)
    s=app.st.session_state['drafts']['P4102']
    app.st.session_state['demo_'+s['id']+'_admission_date']='02/30/2026'
    store=Store()
    change_room(app,store)
    assert not store.calls and app.st.session_state['current_room']=='P4102'


def test_capture_every_editor_family_before_switch(app):
    open_room(app)
    ss=app.st.session_state
    app.load_neuro_sample();app.create_handoff()
    s=ss['drafts']['P4102']
    s['cultures']=clinical_sheet()['cultures']
    s['viral_panel']=clinical_sheet()['viral_panel']
    s['medications']=parse_medications('Medications:\n• Synthetic medicine\t10 mg\tOral\tq6h').rows
    # Render populates actual keys. Make pending edits without running callbacks.
    ss[app.edit_key(s,'Respiratory')]='Pending respiratory note'
    row=s['medications'][0]
    ss['med_draft_'+row['id']+'_dose']='12 mg'
    ss['med_draft_'+row['id']+'_section']='Neurologic'
    ss['demo_'+s['id']+'_dosing_weight']='11 kg'
    ss['weight_'+s['id']+'_z_score']='0.5'
    ss['culture_'+s['cultures']['rows'][1]['id']+'_organisms']='Candida species'
    ss['viral_'+s['viral_panel']['rows'][0]['id']+'_name']='Combined viral target'
    for source,rows in s['neuro_vitals'].items():
        if rows:
            ss['neuro_'+s['id']+'_'+source+'_0']='0'
            break
    store=Store()
    change_room(app,store)
    saved=ss['vault']['rooms']['P4102']
    assert saved['fields']['Respiratory']=='Pending respiratory note'
    assert saved['medications'][0]['dose']=='12 mg'
    assert saved['medications'][0]['section']=='Neurologic'
    assert destination_for('Synthetic medicine',ss['vault']['settings']['medication_mappings'])=='Neurologic'
    assert saved['dosing_weight']=='11 kg' and saved['nutrition']['z_score']=='0.5'
    assert saved['cultures']['rows'][1]['organisms']==['Candida species']
    assert saved['viral_panel']['rows'][0]['name']=='Combined viral target'


def test_pending_mapping_survives_failed_write_then_retry(app):
    open_room(app)
    ss=app.st.session_state
    s=ss['drafts']['P4102']
    s['medications']=parse_medications('Medications:\n• Synthetic medicine\t10 mg\tOral\tq6h').rows
    row=s['medications'][0]
    ss['med_draft_'+row['id']+'_section']='Neurologic'
    change_room(app,Store(StorageError('Offline')))
    change_room(app,Store())
    assert destination_for('Synthetic medicine',ss['vault']['settings']['medication_mappings'])=='Neurologic'


def test_late_old_room_callbacks_do_not_mutate_saved_data(app):
    open_room(app)
    ss=app.st.session_state
    key=app.edit_key(ss['drafts']['P4102'],'Neurologic')
    ss[key]='Before switch'
    change_room(app)
    old=deepcopy(ss['vault']['rooms']['P4102'])
    app.update_field('P4102','Neurologic',key)
    app.ventilation_change('P4102','Vent Mode','stale_key')
    assert ss['drafts']['P4102']==old


def test_example_buttons_absent_from_handoff_screen(app,monkeypatch):
    open_room(app)
    equip(app,monkeypatch)
    labels=[]
    app.st.button=lambda label,*args,**kwargs:labels.append(label) or False
    app.handoff_page(None)
    assert not any('example' in label.casefold() for label in labels)
    assert 'Clear pasted text' in labels


def test_callback_widgets_pass_actual_store(app,monkeypatch):
    open_room(app)
    equip(app,monkeypatch)
    controls=[]
    original=app.st.selectbox
    def select(label,*args,**kwargs):
        controls.append((label,kwargs))
        return original(label,*args,**kwargs)
    app.st.selectbox=select
    store=Store()
    app.handoff_page(store)
    assert next(x for label,x in controls if label=='Room')['args']==(store,)


@pytest.mark.parametrize('instant,expected',[
    (datetime(2026,11,7,1,15,9,tzinfo=timezone.utc),'11/06/2026 08:15:09 PM EST'),
    (datetime(2026,7,1,12,30,tzinfo=timezone.utc),'07/01/2026 08:30:00 AM EDT'),
    (datetime(2026,11,1,5,30,tzinfo=timezone.utc),'11/01/2026 01:30:00 AM EDT'),
    (datetime(2026,11,1,6,30,tzinfo=timezone.utc),'11/01/2026 01:30:00 AM EST'),
])
def test_timezone_season_and_repeated_hour(instant,expected):
    assert eastern_print_time(instant)==expected


def test_naive_print_timestamp_rejected():
    with pytest.raises(ValueError): eastern_print_time(datetime(2026,1,1))


def test_same_print_stamp_on_each_room_and_continuation():
    first=new_sheet('P4102')
    first['fields']['Neurologic']='\n'.join('Synthetic row '+str(i) for i in range(130))
    second=new_sheet('P4104')
    instant=datetime(2026,11,7,1,15,9,tzinfo=timezone.utc)
    stamp=eastern_print_time(instant)
    doc=fitz.open(stream=handoffs_pdf([first,second],instant),filetype='pdf')
    assert len(doc)>2
    for page in doc:
        assert page.get_text().count(stamp)==1
        hits=page.search_for('Print prepared:')
        assert hits and hits[0].x0<25 and hits[0].y0<35


def test_html_stamp_updates_only_on_print_event():
    html=handoffs_html([clinical_sheet(),clinical_sheet('P4104')],datetime(2026,11,7,1,tzinfo=timezone.utc))
    assert html.count('data-print-time>')==2
    assert html.count('data-print-time>11/06/2026 08:00:00 PM EST')==2
    assert html.count('Lab windows evaluated: 11/06/2026 08:00:00 PM EST')==2
    assert "window.addEventListener('beforeprint'" in html
    assert "timeZone: 'America/New_York'" in html
    assert 'Saved (UTC)' not in html


def test_download_defers_clock_and_uses_isolated_snapshot(monkeypatch):
    import exports
    s=clinical_sheet()
    calls=[]
    def stamp(instant=None):
        calls.append(instant)
        return '01/01/2026 01:02:03 PM EST'
    monkeypatch.setattr(exports,'eastern_print_time',stamp)
    generate=download_payload([s],'pdf')
    assert not calls
    s['fields']['Diagnoses']='MUTATED_AFTER_RENDER'
    data=generate()
    assert len(calls)==1
    doc=fitz.open(stream=data,filetype='pdf')
    assert 'MUTATED_AFTER_RENDER' not in ''.join(p.get_text() for p in doc)
    assert '01/01/2026 01:02:03 PM EST' in doc[0].get_text()


@pytest.mark.parametrize('kind',['pdf','html','text'])
def test_download_content_and_expiry(kind):
    data=download_payload([clinical_sheet()],kind)()
    assert isinstance(data,bytes)
    with pytest.raises(ValueError,match='expired'):
        download_payload([clinical_sheet()],kind,time.monotonic()-1)()


@pytest.mark.parametrize('text',[
    'Candida parapsilosis','Staphylococcus aureus','Streptococcus pneumoniae',
    'Beta hemolytic Streptococcus, Group A','Gram positive cocci','Yeast',
    'Candida species (Preliminary)',
])
def test_positive_organism_formats_bold(text):
    assert is_organism_result(text)


@pytest.mark.parametrize('text',[
    'No growth','No growth (Preliminary)','No growth (In process)',
    'Not Detected','Negative','No organisms seen','No significant growth',
    'Pending','Pending identification','In process','Preliminary','Final',
    'Normal respiratory flora','Mixed skin flora','Cancelled','Specimen rejected',
    'Candida not isolated','Negative for Candida','Not performed','',
])
def test_nonpositive_result_not_bold(text):
    assert not is_organism_result(text)


def test_new_viral_heading_plain_text_without_markup():
    s=clinical_sheet()
    assert viral_text(s['viral_panel'])=='Rapid Viral Panel: Rhinovirus/enterovirus'
    assert 'Positive:' not in handoff_text(s)
    assert '<b>' not in handoff_text(s)


def test_positive_fonts_and_no_growth_font_in_pdf():
    data=handoff_pdf(clinical_sheet())
    doc=fitz.open(stream=data,filetype='pdf')
    spans=[span for page in doc for block in page.get_text('dict')['blocks'] if 'lines' in block
           for line in block['lines'] for span in line['spans']]
    for name in ('Candida','Staphylococcus','Rhinovirus'):
        found=[x for x in spans if name in x['text']]
        assert found and all('Bold' in x['font'] for x in found)
    found=[x for x in spans if 'NGTD' in x['text']]
    assert found and all('Bold' not in x['font'] for x in found)


def test_html_organisms_bold_but_notes_escaped():
    s=clinical_sheet()
    s['fields']['Neurologic']='<b>do not trust markup</b>'
    html=handoff_html(s)
    assert '<b>Candida parapsilosis</b>' in html
    assert '<b>Rhinovirus/enterovirus</b>' in html
    assert '<b>No growth' not in html
    assert '&lt;b&gt;do not trust markup&lt;/b&gt;' in html


def test_positive_labels_cannot_inject_scripts_or_reportlab_tags():
    s=clinical_sheet()
    s['viral_panel']['rows'][0]['name']='<script>alert(1)</script>'
    s['cultures']['rows'][1]['organisms']=['Candida <img src="bad"/>']
    html=handoff_html(s)
    assert '<script>alert(1)</script>' not in html
    assert '<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>' in html
    assert '<img src="bad"/>' not in html
    assert handoff_pdf(s).startswith(b'%PDF')


def test_no_new_storage_schema_or_saved_markup():
    s=clinical_sheet()
    vault=save_sheet_in(new_vault(),s)
    original=deepcopy(vault)
    key=Fernet.generate_key().decode()
    rendered=handoff_html(s)+str(handoff_pdf(s))
    assert rendered
    assert vault==original and '<b>' not in str(vault)
    assert open_vault(seal_vault(vault,key),key)==vault
    assert upgrade_vault(vault)==vault
