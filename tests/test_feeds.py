"""Synthetic T-block parsing, display, recovery, persistence and workflow tests."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from feeds import (parse_feeds, feeds_text, feeds_for_output, feeding_method, validate_feeds, METHODS)
from importing import import_sections
from models import (new_sheet, new_vault, save_sheet_in, upgrade_vault, SCHEMA_VERSION,
                    validate_sheet, validate_vault, fields_with_medications)
from parser import parse_smartphrase
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, print_fit_report
from security import seal_vault, open_vault, generate_key
from batching import available_handoffs
from import_review import review_summary
from error_store import new_error_event
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_print_fit_reset import Store
from test_rooms_infusions import med

NJ = 'Gastric Tube Nasojejunal 8 Fr Right nostril'
PEG = 'Gastrostomy/Enterostomy Percutaneous endoscopic gastrostomy (PEG) LUQ'
GT = 'Gastrostomy/Enterostomy Gastrostomy 1 14 Fr. LLQ'
J = 'Gastrostomy/Enterostomy Jejunostomy 2 14 Fr. LUQ'
LABEL = 'Continuous Tube Feeding Ordered Rate  mL/hr (not calculated)'


def wrap(body, letter='t'):
    return letter*12+'\n'+body+'\n'+letter.upper()*12+'\n'


def source(device=NJ, rate='24 mL', formula='Synthetic formula'):
    return f'{device}-{LABEL}: {rate}\n{device}-Tube Feeding: {formula}'


def parsed(body):
    result=parse_feeds(body)
    assert not result.error, result.error
    return result


def imported(body, before=None):
    result=import_sections(before or new_sheet('P4102'), wrap(body), new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


def test_sample_style_rate_qualified_by_header_and_clean_formula():
    r=parsed(source())
    row=r.data['rows'][0]
    assert row['rate']=='24 mL/hr' and row['method']=='NJ' and row['rate_source']=='primary'
    assert feeds_text(r.data)=='Feeds:\nFeeding Method: NJ\nSynthetic formula @ 24 mL/hr'
    assert not r.diagnostics


@pytest.mark.parametrize('device,method',[
    (NJ,'NJ'),(PEG,'PEG'),(GT,'GT'),(J,'J'),
    ('Gastrostomy/Enterostomy Gastrojejunostomy tube','GJ'),('PEG-J LUQ','PEG-J'),
    ('Gastric Tube Nasogastric Left nostril','NG'),('Gastric Tube Orogastric','OG'),
    ('Gastric Tube Nasoduodenal','ND'),('PEJ LUQ','PEJ'),('G-tube','GT'),
    ('Gastrostomy/Enterostomy','UNK'),('Gastric Tube Other (Comment)','UNK'),
    ('Nasoenteric (post-pyloric) tube','Post-pyloric'),('Oral','PO'),
])
def test_explicit_method_abbreviations(device,method):
    assert feeding_method(device)==method
    assert parsed(source(device)).data['rows'][0]['method']==method


@pytest.mark.parametrize('method',METHODS)
def test_method_editor_allows_display_choices(method):
    row=parsed(source()).data['rows'][0];row['method']=method
    validate_feeds({'rows':[row]})


@pytest.mark.parametrize('mark',['[REMOVED]','[removed]','[ REMOVED ]'])
def test_removed_lines_never_supply_formula_or_rate(mark):
    text=source(PEG,'32 mL','Other (Comment) (Synthetic vanilla)')+'\n'+mark+' '+source('Gastric Tube Old','99 mL','REMOVED SENTINEL').replace('\n','\n'+mark+' ')
    r=parsed(text)
    assert len(r.data['rows'])==1
    assert 'REMOVED SENTINEL' not in json.dumps(r.data)
    assert feeds_text(r.data)=='Feeds:\nFeeding Method: PEG\nSynthetic vanilla @ 32 mL/hr'


@pytest.mark.parametrize('formula,expected',[
    ('Other (Comment) (Synthetic formula)','Synthetic formula'),
    (' (synthetic spelling) ','synthetic spelling'),
    ('Formula Infant (with MBM)','Formula Infant (with MBM)'),
    ('Other (Comment)','UNK'), ('','UNK'), ('--','UNK'),
])
def test_formula_preserves_words_and_qualifiers(formula,expected):
    r=parsed(source(formula=formula))
    assert expected+' @ 24 mL/hr' in feeds_text(r.data)


def test_multiple_active_devices_do_not_share_a_rate_or_formula():
    r=parsed(source(NJ,'22 mL','Formula A')+'\n'+GT+'-Tube Feeding: (Formula B)')
    rows=r.data['rows']
    assert len(rows)==2
    assert [(x['method'],x['formula'],x['rate']) for x in rows]==[('NJ','Formula A','22 mL/hr'),('GT','Formula B','')]
    assert 'Formula B @ UNK' in feeds_text(r.data)


def test_distinct_same_route_devices_do_not_share_fields():
    r=parsed(source(NJ,'22 mL','Formula A')+'\n'+source(NJ.replace('Right','Left'),'14 mL','Formula B'))
    assert len(r.data['rows'])==2
    assert [x['rate'] for x in r.data['rows']]==['22 mL/hr','14 mL/hr']


@pytest.mark.parametrize('backup',[
    'Back Up Feed Rate: 18 mL/hr', 'Back Up Feed Rate (mL/hr): 18',
    f'Back Up Feed Rate: {NJ}-{LABEL}: 18 mL',
    f'{NJ}-Back Up Feed Rate (mL/hr): 18 mL',
])
def test_usable_backup_rate(backup):
    r=parsed(NJ+'-Tube Feeding: Synthetic formula\n'+backup)
    row=r.data['rows'][0]
    assert row['rate']=='18 mL/hr' and row['rate_source']=='backup'


def test_primary_rate_wins_over_backup():
    r=parsed(source()+'\nBack Up Feed Rate: 18 mL/hr')
    assert r.data['rows'][0]['rate']=='24 mL/hr'
    assert r.data['rows'][0]['rate_source']=='primary'


@pytest.mark.parametrize('value',['87 mL','87','87 ml over 12 hr','87 mL/day'])
def test_backup_intake_is_not_rate(value):
    r=parsed(J+'-Tube Feeding: (Synthetic pediatric)\nBack Up Feed Intake: '+J+'-Intake (mL): '+value)
    assert r.data['rows'][0]['rate']==''
    assert r.data['rows'][0]['backup_intake']==value
    assert feeds_text(r.data).endswith('Synthetic pediatric @ UNK')
    assert value not in feeds_text(r.data)


@pytest.mark.parametrize('bad',['87 mL','87','10-20 mL/hr','10 | 20 mL/hr','1 L/hr','10 mL/kg/hr','abc'])
def test_backup_rate_without_usable_units_or_single_value_is_unknown(bad):
    r=parsed(NJ+'-Tube Feeding: Synthetic formula\nBack Up Feed Rate: '+bad)
    assert r.data['rows'][0]['rate']==''
    assert r.diagnostics


@pytest.mark.parametrize('rate',['0 mL','0.5 mL','12.50 mL','1000 mL','1,000 mL','22 mL/hr','22 mL/h','22 ml/hour','22 mL per hour'])
def test_rate_precision_zero_and_unit_variants(rate):
    r=parsed(source(rate=rate))
    assert r.data['rows'][0]['rate']
    assert r.data['rows'][0]['rate_source']=='primary'


def test_formula_with_explicit_inline_hourly_rate():
    r=parsed(NJ+'-Tube Feeding: Synthetic formula @ 16.5 mL/hr')
    assert r.data['rows'][0]['formula']=='Synthetic formula'
    assert r.data['rows'][0]['rate']=='16.5 mL/hr'


def test_conflicting_primary_does_not_fall_back_or_choose_largest():
    r=parsed(source()+'\n'+NJ+'-'+LABEL+': 29 mL\nBack Up Feed Rate: 13 mL/hr')
    assert r.data['rows'][0]['rate']=='' and r.diagnostics


def test_duplicate_equal_rates_do_not_duplicate_device():
    r=parsed(source()+'\n'+NJ+'-'+LABEL+': 24.0 mL')
    assert len(r.data['rows'])==1 and r.data['rows'][0]['rate']=='24 mL/hr'
    assert not r.diagnostics


def test_conflicting_formula_is_unknown_not_combined():
    r=parsed(source()+'\n'+NJ+'-Tube Feeding: Different formula')
    assert r.data['rows'][0]['formula']=='' and r.diagnostics


def test_global_backup_not_borrowed_for_multiple_tubes():
    r=parsed(NJ+'-Tube Feeding: Formula A\n'+GT+'-Tube Feeding: Formula B\nBack Up Feed Rate: 15 mL/hr')
    assert all(not row['rate'] for row in r.data['rows']) and r.diagnostics


def test_plain_explicit_fields_are_supported():
    r=parsed('Feeds:\nFeeding Method: NG\nFormula: Synthetic pediatric\nRate: 17 mL/hr')
    assert feeds_text(r.data)=='Feeds:\nFeeding Method: NG\nSynthetic pediatric @ 17 mL/hr'


@pytest.mark.parametrize('body',['','Feeds:','None','No data','[REMOVED] '+source().replace('\n','\n[REMOVED] ')])
def test_empty_or_removed_only_T_clears_previous(body):
    old=imported(source());s=imported(body,old)
    assert s['feeds'] is None and old['feeds'] is not None
    assert not feeds_text(s['feeds'])


def test_omitting_T_preserves_snapshot_and_other_fields():
    old=imported(source());before=deepcopy(old)
    r=import_sections(old,wrap('Diagnoses:\n1. Synthetic change','a'),new_vault()['settings'])
    assert r.sheet['feeds']==old['feeds'] and old==before
    for key in before:
        if key!='fields':assert r.sheet[key]==before[key]


def test_new_T_replaces_without_duplicates_and_preserves_medications_notes():
    old=imported(source());old['fields']['FEN / GI']='UNTOUCHED NOTE'
    old['medications']=[med('pantoprazole','5 mg','Oral','Daily','', 'Other Medications')]
    s=imported(source(rate='28 mL'),old)
    assert len(s['feeds']['rows'])==1 and s['medications']==old['medications']
    assert s['fields']==old['fields']
    assert feeds_text(s['feeds']).endswith('28 mL/hr')


def test_no_cross_section_or_previous_feed_rate_fallback():
    old=imported(source())
    text=wrap(NJ+'-Tube Feeding: Formula B')+wrap('NUTRITION:\nWeight: 20 kg','i')+wrap('Orders Placed This Encounter\n• Infant feeding\nTube feeding continuous rate (mL/hr): 35','r')
    r=import_sections(old,text,new_vault()['settings'])
    assert r.sheet['feeds']['rows'][0]['rate']==''


def test_failed_T_import_keeps_unrelated_sections_and_hides_retained_feeds():
    old=imported(source())
    r=import_sections(old,wrap('Malformed feeding text')+wrap('Diagnoses:\n1. New synthetic diagnosis','a'),new_vault()['settings'])
    assert r.errors and r.sheet['fields']['Diagnoses']=='New synthetic diagnosis'
    assert r.sheet['feeds']==old['feeds']
    assert feeds_for_output(r.sheet) is None
    assert 'prior feeds hidden' in review_summary(r.sheet)
    output=fields_with_medications(r.sheet)['FEN / GI']
    assert 'Not updated. Review needed.' in output and 'Synthetic formula' not in output
    assert 'Synthetic formula' not in handoff_html(r.sheet)


def test_partial_conflict_displays_readable_fields_and_unknown_rate():
    r=import_sections(new_sheet('P4102'),wrap(source()+'\n'+NJ+'-'+LABEL+': 30 mL'),new_vault()['settings'])
    assert not r.errors and r.sheet['import_warnings']['t']
    assert feeds_for_output(r.sheet) is not None
    assert 'Synthetic formula @ UNK' in fields_with_medications(r.sheet)['FEN / GI']


def test_bad_divider_leaves_T_retained_hidden_and_a_imported():
    old=imported(source())
    r=import_sections(old,wrap('Diagnoses:\n1. New','a')+'\ntttttttt\n'+source(),new_vault()['settings'])
    assert r.errors and r.sheet['fields']['Diagnoses']=='New'
    assert feeds_for_output(r.sheet) is None and r.sheet['feeds']==old['feeds']


def test_multiple_patient_sections_still_rejected():
    s=imported(source())
    r=import_sections(s,wrap(source())+'\n'+wrap(source(rate='99 mL')),new_vault()['settings'])
    assert r.sheet is None and r.errors


def test_sources_escaped_and_no_raw_removed_row_in_archive_or_exports():
    s=imported(source(formula='<img src=x onerror=alert(1)>')+'\n[REMOVED] '+NJ+'-Tube Feeding: SECRET REMOVED')
    html=handoff_html(s)
    assert '<img src=x' not in html and '&lt;img' in html
    v=save_sheet_in(new_vault(),s);key=generate_key();token=seal_vault(v,key)
    assert b'<img' not in token
    assert 'SECRET REMOVED' not in json.dumps(open_vault(token,key))
    assert open_vault(token,key)==v


def test_diagnostics_are_technical_only_and_serializable():
    r=parse_feeds(source(formula='PRIVATE_FORMULA_SENTINEL')+'\n'+NJ+'-'+LABEL+': 12 | 16 mL')
    event=new_error_event(r.diagnostics)
    assert 'PRIVATE_FORMULA_SENTINEL' not in json.dumps(event)
    assert NJ not in json.dumps(event) and '12 | 16' not in json.dumps(event)


def test_io_then_feeds_then_medication_groups_in_all_exports():
    text=wrap(source())+'\n'+wrap('Intake\t101 ml\nOutput\t80 ml\nNet\t21 ml','s')
    r=import_sections(new_sheet('P4102'),text,new_vault()['settings']);s=r.sheet
    s['medications']=[med('pantoprazole','5 mg','Oral','Daily','', 'Other Medications')]
    s['fields']['FEN / GI']='Separate note'
    plain=fields_with_medications(s)['FEN / GI']
    assert plain.index('Intake:') < plain.index('Feeds:') < plain.index('GI prophylaxis') < plain.index('Separate note')
    html=handoff_html(s);assert '<b>Feeds:</b>' in html
    assert 'Feeding Method: NJ' in handoff_text(s)
    pdf=PdfReader(BytesIO(handoff_pdf(s)))
    assert len(pdf.pages)==1
    t=pdf.pages[0].extract_text();assert 'Feeding Method: NJ' in t and '24 mL/hr' in t


def test_feeds_only_room_in_print_all_and_exclusion_removes_it():
    s=imported(source())
    assert 'P4102' in available_handoffs(new_vault(),{'P4102':s})
    s['feeds']['rows'][0]['include']=False
    assert not available_handoffs(new_vault(),{'P4102':s})


def test_two_room_print_all_keeps_feeds_separate_and_page_fit_works():
    a=imported(source(formula='ROOM_A_FORMULA'));b=deepcopy(a);b['room']='P4104'
    b['feeds']['rows'][0]['formula']='ROOM_B_FORMULA'
    pdf=PdfReader(BytesIO(handoffs_pdf([a,b])))
    assert len(pdf.pages)==2
    assert 'ROOM_A_FORMULA' in pdf.pages[0].extract_text() and 'ROOM_B_FORMULA' not in pdf.pages[0].extract_text()
    assert 'ROOM_B_FORMULA' in pdf.pages[1].extract_text()


def test_old18_migration_preserves_every_original_field_settings_and_generation():
    v=save_sheet_in(new_vault(),new_sheet('P4102'));v['schema']=18
    v['reset_generation']='e'*32
    v['rooms']['P4102'].pop('feeds');v['rooms']['P4102'].pop("devices", None);v['rooms']['P4102'].pop("neuro_devices", None);v['rooms']['P4102'].pop("pacemaker", None);v['rooms']['P4102'].pop("diet", None)
    before=deepcopy(v);key=generate_key()
    old_token=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    new=open_vault(old_token,key)
    assert v==before and new['schema']==SCHEMA_VERSION==33
    assert new['settings']==before['settings'] and new['reset_generation']==before['reset_generation']
    assert new['rooms']['P4102']==dict(before['rooms']['P4102'],feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert open_vault(seal_vault(new,key),key)==new


def test_invalid_old18_is_not_silently_rewritten():
    v=new_vault();v['schema']=18;v['rooms']['P4102']=new_sheet('P4102')
    with pytest.raises(ValueError):upgrade_vault(v)


def test_session18_migration_preserves_unsaved_feeds_unrelated_fields(app):
    open_room(app);app.save_room(None);ss=app.st.session_state
    ss['vault']['schema']=18;ss['vault']['reset_generation']='f'*32
    for sheet in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):sheet.pop('feeds');sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None)
    ss['drafts']['P4102']['fields']['FEN / GI']='Unsaved note'
    app.upgrade_existing_session()
    assert ss['vault']['schema']==33 and ss['vault']['reset_generation']=='f'*32
    assert ss['drafts']['P4102']['feeds'] is None and ss['drafts']['P4102']['fields']['FEN / GI']=='Unsaved note'


def test_editor_changes_and_room_autosave_capture_unblurred_value(app):
    open_room(app);ss=app.st.session_state;s=imported(source());ss['drafts']['P4102']=s
    row=s['feeds']['rows'][0];key='feed_'+row['id']+'_rate'
    ss[key]='17.5 mL/hr'
    snapshot=app.editor_snapshot('P4102')
    assert snapshot['feeds']['rows'][0]['rate']=='17.5 mL/hr'
    assert snapshot['feeds']['rows'][0]['rate_source']=='manual'
    assert row['rate']=='24 mL/hr'
    open_room(app,'P4104')
    assert ss['vault']['rooms']['P4102']['feeds']['rows'][0]['rate']=='17.5 mL/hr'
    assert not any(k.startswith('feed_') for k in ss)


def test_invalid_editor_rate_does_not_change_record(app):
    open_room(app);ss=app.st.session_state;s=imported(source());ss['drafts']['P4102']=s
    row=s['feeds']['rows'][0];key='feed_'+row['id']+'_rate';ss[key]='70 mL'
    app.feed_row_change('P4102',row['id'],'rate',key)
    assert row['rate']=='24 mL/hr' and ss[key]=='24 mL/hr' and ss['notice'][0]=='error'


def test_editor_unk_exclude_restore_and_wrong_room_guard(app):
    open_room(app);ss=app.st.session_state;s=imported(source());ss['drafts']['P4102']=s
    row=s['feeds']['rows'][0];key='feed_'+row['id']+'_rate';ss[key]='UNK'
    app.feed_row_change('P4104',row['id'],'rate',key);assert row['rate']=='24 mL/hr'
    app.feed_row_change('P4102',row['id'],'rate',key);assert row['rate']==''
    key='feed_'+row['id']+'_include';ss[key]=False
    app.feed_row_change('P4102',row['id'],'include',key);assert not feeds_text(s['feeds'])
    ss[key]=True;app.feed_row_change('P4102',row['id'],'include',key);assert 'UNK' in feeds_text(s['feeds'])


def test_ui_render_and_downloads_with_t_section(app,monkeypatch):
    open_room(app);app.st.session_state['drafts']['P4102']=imported(source())
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(k.startswith('feed_') for k in app.st.session_state)
    assert any(isinstance(d,bytes) and d.startswith(b'%PDF') for _,d in downloads)


def test_reset_clears_feeds_and_widget_values_without_changing_rules(app):
    open_room(app);ss=app.st.session_state;s=imported(source());ss['drafts']['P4102']=s
    ss['feed_'+s['feeds']['rows'][0]['id']+'_formula']='Unsaved formula'
    app.save_room(None);before=deepcopy(ss['vault']['settings'])
    app.clear_all_handoffs(None)
    assert not ss['drafts'] and not ss['vault']['rooms']
    assert not any(k.startswith('feed_') for k in ss)
    assert ss['vault']['settings']==before


@pytest.mark.parametrize('field,value',[('method','IV'),('rate','24 mL'),('formula','a\nb'),('rate_source','guess'),('include','yes'),('device','x'*601)])
def test_validation_rejects_unsafe_values(field,value):
    d=parsed(source()).data;d['rows'][0][field]=value
    with pytest.raises(ValueError):validate_feeds(d)
