"""Synthetic U/V device parsing, removal, persistence, export and callback checks."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from devices import (parse_devices, validate_devices, devices_text, devices_markup,
                     evd_text, devices_for_output, device_line, KINDS)
from importing import import_sections
from parser import parse_smartphrase
from models import (new_sheet, new_vault, upgrade_vault, validate_sheet, validate_vault,
                    fields_with_medications, automatic_vitals, save_sheet_in, SCHEMA_VERSION)
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf, print_layout_info
from batching import available_handoffs
from security import open_vault, seal_vault, generate_key
from import_review import review_summary
from error_store import new_error_event
from test_callbacks import app, open_room
from test_ui_smoke import equip

PIV = 'Peripheral IV 01/03/26 Anterior;Right Forearm-Site Assessment: Clean, Dry, Intact'
EVD = 'Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Clamped'


def block(text, letter='u'):
    return letter*12+'\n'+text+'\n'+letter.upper()*12


def imported(text, before=None):
    result = import_sections(before or new_sheet('P4102'), text, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize('prefix,kind,needle', [
    ('Peripheral IV 01/03/26 Right Hand', 'PIV', 'PIV Right Hand'),
    ('PICC 01/03/26 Double-lumen Left Femoral vein', 'PICC', 'PICC Double-lumen Left Femoral vein'),
    ('CVC 01/03/26 Double-lumen Non-tunneled Right Femoral', 'CVC', 'CVC Double-lumen'),
    ('Arterial Line 01/03/26 Left Radial', 'Arterial line', 'Arterial line Left Radial'),
    ('Urethral Catheter Straight-tip 8 Fr.', 'Urinary catheter', 'Urinary catheter Straight-tip 8 Fr.'),
    ('Urethral Catheter Non-latex 6 Fr.', 'Urinary catheter', 'Non-latex 6 Fr.'),
    ('Surgical Airway Bivona Cuffed 4.0', 'Trach', 'Trach Bivona Cuffed 4.0'),
    ('Surgical Airway Shiley Cuffed 6', 'Trach', 'Trach Shiley Cuffed 6'),
    ('Gastric Tube 01/03/26 Nasojejunal 8 Fr Right nostril', 'Feeding tube', 'NJ 8 Fr Right nostril'),
    ('Gastric Tube Nasogastric Left nostril', 'Feeding tube', 'NG Left nostril'),
    ('Gastrostomy/Enterostomy Percutaneous endoscopic gastrostomy (PEG) LUQ', 'Feeding tube', 'PEG LUQ'),
    ('Chest Tube 1 Other (Comment) Pleural', 'Drain', 'Chest Tube 1 Other (Comment) Pleural'),
    ('Drain 01/03/26 Inferior;Right Pleural', 'Drain', 'Drain Inferior, Right Pleural'),
    ('Drain 01/03/26 Closed drain, to suction Inferior;Left;Midline Mediastinal', 'Drain', 'Closed drain, to suction'),
])
def test_device_identification_and_compact_labels(prefix, kind, needle):
    result = parse_devices(prefix+'-Site Assessment: ASSESSMENT_SENTINEL')
    assert not result.error and not result.diagnostics
    row = result.data['rows'][0]
    assert row['kind'] == kind
    assert needle in device_line(row)
    assert 'ASSESSMENT_SENTINEL' not in json.dumps(result.data)


@pytest.mark.parametrize('mark', ['[REMOVED]', '[removed]', '[ Removed ]'])
@pytest.mark.parametrize('desc', [
    'PICC 01/02/26 Right Arm', 'CVC 01/02/26 Left Femoral',
    'Peripheral IV Right Wrist', 'Arterial Line Right Radial',
    'Gastric Tube Nasojejunal 8 Fr Right nostril',
    'Urethral Catheter 8 Fr.', 'Surgical Airway Shiley Cuffed 6',
    'Chest Tube Right Pleural', 'Drain Left Pleural',
    'Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor',
])
def test_all_removed_non_ett_devices_are_discarded(mark, desc):
    for letter in ('u','v'):
        result = parse_devices(mark+' '+desc+'-Drain Status: Clamped', letter)
        assert not result.error and result.data is None
        assert not result.diagnostics


def test_removed_ett_history_does_not_show_as_current_airway():
    s=imported(block('Endotracheal Tube:\n[REMOVED] ETT 4.5 mm-Secured at (cm): 15 cm'))
    text=devices_text(s)
    assert 'ETT history (removed)' in text
    assert 'Last Airway Size: 4.5 mm' in text and 'Last Secure Site: 15 cm' in text
    assert 'lip' not in text.lower() and 'nares' not in text.lower()


def test_current_and_removed_ett_never_share_depth_or_size():
    s=imported(block('ETT 3.5 mm-Secured at (cm): 10 cm\n[REMOVED] ETT 4 mm-Secured at (cm): (S) 12 cm'))
    rows=s['devices']['rows'];assert len(rows)==2
    assert rows[0]['size']=='3.5 mm' and rows[0]['secured']=='10 cm'
    assert rows[1]['size']=='4 mm' and rows[1]['secured']=='12 cm' and rows[1]['removed']
    text=devices_text(s);assert text.index('Last Airway Size: 3.5 mm') < text.index('history (removed)')


def test_two_undated_removed_etts_are_retained_not_assigned_false_chronology():
    s=imported(block('[REMOVED] ETT 3 mm-Secured at (cm): 9 cm\n[REMOVED] ETT 4 mm-Secured at (cm): 12 cm'))
    assert len(s['devices']['rows'])==2
    assert devices_text(s).count('history (removed)')==2


def test_gastric_tube_under_airway_header_is_not_ett():
    s=imported(block('Endotracheal Tube:\nGastric Tube 01/03/26 Nasojejunal 8 Fr Right nostril-Secured at (cm): 62 cm\nETT 4 mm-Secured at (cm): 18 cm'))
    rows=s['devices']['rows'];assert [r['kind'] for r in rows]==['Feeding tube','ETT']
    assert 'Last Secure Site: 18 cm' in devices_text(s)
    assert 'Last Secure Site: 62 cm' not in devices_text(s)


def test_same_device_repeated_assessments_are_not_multiple_devices():
    r=parse_devices(PIV+'\n'+PIV.replace('Clean, Dry, Intact','Dry'))
    assert len(r.data['rows'])==1


def test_same_type_different_dates_or_sites_stay_separate():
    r=parse_devices(PIV+'\n'+PIV.replace('Right','Left')+'\n'+PIV.replace('01/03/26','01/04/26'))
    assert len(r.data['rows'])==3


def test_conflicting_security_depths_are_unknown_not_last_lowest_or_first():
    r=parse_devices('ETT 4 mm-Secured at (cm): 18 cm\nETT 4 mm-Secured at (cm): 21 cm')
    assert not r.error and r.data['rows'][0]['secured']=='UNK'
    assert r.diagnostics[0]['code']=='device_conflict'


def test_status_and_security_merge_for_identical_device_only():
    r=parse_devices('Surgical Airway Bivona Cuffed 4-Status: Secured\nSurgical Airway Bivona Cuffed 4-Site Assessment: Clean')
    assert len(r.data['rows'])==1 and r.data['rows'][0]['status']=='Secured'


@pytest.mark.parametrize('status', ['Clamped','Open','Draining','Open to drain at 10 cm H2O'])
def test_evd_status_prints_in_neuro_and_not_in_footer(status):
    s=imported(block(EVD.replace('Clamped',status),'v'))
    assert automatic_vitals(s)['Neurologic']=='CAPD: None\nEVD: '+status
    assert 'EVD: '+status in fields_with_medications(s)['Neurologic']
    assert not devices_text(s)
    assert 'EVD: '+status in handoff_html(s)


def test_evd_below_neuro_observations_before_infusion_notes():
    s=imported(block('Target Arousal Level:\nTarget Arousal Level (SBS): SBS -1','k')+'\n'+block('ICP Trends:\nICP Mean (mmHg): 5 mmHg\nCPP: 65 mmHg','m')+'\n'+block(EVD,'v'))
    s['fields']['Neurologic']='NEURO NOTE'
    text=fields_with_medications(s)['Neurologic']
    assert 'Target Arousal' not in text
    assert text.index('CAPD:') < text.index('ICP Mean') < text.index('EVD: Clamped') < text.index('NEURO NOTE')
    html=handoff_html(s);assert html.index('EVD: Clamped')<html.index('NEURO NOTE')


def test_icp_bolt_not_called_evd_from_shared_heading():
    s=imported(block('Intracranial Pressure Monitor:\nIntracranial Pressure/Ventriculostomy Intraparenchymal ICP monitor-Status: Monitoring','v'))
    assert not evd_text(s)
    assert 'Intraparenchymal' in devices_text(s)
    assert 'EVD:' not in handoff_text(s)


def test_missing_evd_status_is_unk_not_assumed_clamped():
    r=parse_devices(EVD.split('-Drain Status')[0]+'-Drain Status:', 'v')
    assert r.data['rows'][0]['status']=='UNK'
    assert r.diagnostics and 'device_missing_status' in str(r.diagnostics)


def test_unknown_device_with_labeled_property_is_retained_with_notice():
    r=parse_devices('Example novel device Right chest-Status: Secured')
    assert r.data['rows'][0]['kind']=='Other'
    assert r.diagnostics[0]['code']=='device_unclassified'


def test_non_device_prose_is_omitted_without_echo_in_error_log():
    result=import_sections(new_sheet('P4102'),block(PIV+'\nPRIVATE_SENTINEL arbitrary note'),new_vault()['settings'])
    assert result.sheet['devices'] and result.diagnostics
    event=new_error_event(result.diagnostics)
    assert 'PRIVATE_SENTINEL' not in json.dumps(event)
    assert 'PRIVATE_SENTINEL' not in handoff_text(result.sheet)


def test_both_sections_update_independently_and_omit_keeps_existing():
    s=imported(block(PIV)+'\n'+block(EVD,'v'))
    both=deepcopy(s)
    s=imported(block('Lines:'),s)
    assert s['devices'] is None and s['neuro_devices']==both['neuro_devices']
    s=imported(block(PIV),s)
    assert s['devices'] and s['neuro_devices']==both['neuro_devices']
    s=imported(block('Intracranial Pressure Monitor:','v'),s)
    assert s['neuro_devices'] is None and s['devices']


def test_missing_u_close_skips_only_u_hides_prior_inventory():
    s=imported(block(PIV))
    text='uuuuuuuu\nLines:\n'+PIV+'\n'+block('Diagnoses:\n1. New synthetic diagnosis','a')
    r=import_sections(s,text,new_vault()['settings'])
    assert r.errors and r.sheet['devices']==s['devices']
    assert r.sheet['fields']['Diagnoses']=='New synthetic diagnosis'
    assert devices_for_output(r.sheet) is None
    assert not devices_text(r.sheet)
    assert 'prior devices hidden' in review_summary(r.sheet)


def test_v_failure_hides_old_evd_not_other_neuro_vitals():
    s=imported(block(EVD,'v')+'\n'+block('WAT Score:\nWAT-1 total score (0-12): 0','l'))
    r=import_sections(s,'vvvvvvvv\nIntracranial Pressure Monitor:\n'+EVD,new_vault()['settings'])
    assert r.errors and r.sheet['neuro_devices']==s['neuro_devices']
    assert not evd_text(r.sheet)
    assert 'WAT-1' in fields_with_medications(r.sheet)['Neurologic']


def test_successful_reimport_clears_only_matching_device_warning():
    s=imported(block(PIV)+'\n'+block(EVD,'v'))
    r=import_sections(s,'uuuuuuuu\nLines:\n'+PIV+'\nvvvvvvvv\nIntracranial Pressure Monitor:\n'+EVD,new_vault()['settings'])
    assert set(r.sheet['import_warnings'])=={'u','v'}
    s=imported(block(PIV),r.sheet)
    assert 'u' not in s['import_warnings'] and 'v' in s['import_warnings']


@pytest.mark.parametrize('bad', [None, 12, True, [], 'x'*30001])
def test_invalid_input_does_not_crash(bad):
    assert parse_devices(bad).error


@pytest.mark.parametrize('field,value', [('date','99/99/26'), ('date','today'), ('label',''), ('size','1\n2'), ('secured','x'*251), ('include',1), ('removed','false'), ('kind','Not a kind')])
def test_invalid_edit_rejected(field,value):
    row=parse_devices(PIV).data['rows'][0];row[field]=value
    with pytest.raises(ValueError):validate_devices({'rows':[row]})


def test_removed_non_ett_cannot_be_injected_into_saved_inventory():
    row=parse_devices(PIV).data['rows'][0];row['removed']=True
    with pytest.raises(ValueError):validate_devices({'rows':[row]})


def test_duplicate_row_ids_rejected():
    row=parse_devices(PIV).data['rows'][0]
    with pytest.raises(ValueError):validate_devices({'rows':[row,deepcopy(row)]})


def test_html_escapes_labels_and_status_no_script_injection():
    s=imported(block(PIV)+'\n'+block(EVD,'v'))
    s['devices']['rows'][0]['label']='PIV <script>alert(1)</script> & test'
    s['neuro_devices']['rows'][0]['status']='<b>NOT MARKUP</b>'
    html=handoff_html(s)
    assert '<script>alert' not in html and '&lt;script&gt;' in html
    assert '&lt;b&gt;NOT MARKUP&lt;/b&gt;' in html


def test_schema19_migration_keeps_every_previous_field_generation_and_times():
    v=save_sheet_in(new_vault(),new_sheet('P4102'));v['schema']=19
    for s in v['rooms'].values():s.pop('devices');s.pop('neuro_devices');s.pop("pacemaker", None);s.pop("diet", None)
    v['reset_generation']='d'*32
    v['rooms']['P4102']['fields']['Access']='MANUAL LINE NOTE'
    before=deepcopy(v);key=generate_key()
    old=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    migrated=open_vault(old,key)
    assert v==before and migrated['schema']==SCHEMA_VERSION==33
    assert migrated['settings']==before['settings'] and migrated['reset_generation']==before['reset_generation']
    for room,s in before['rooms'].items():assert migrated['rooms'][room]==dict(s, devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert open_vault(seal_vault(migrated,key),key)==migrated


def test_old19_with_unexpected_field_is_not_silently_discarded():
    v=new_vault();v['schema']=19;v['rooms']['P4102']=new_sheet('P4102')
    v['rooms']['P4102'].pop('devices');v['rooms']['P4102'].pop('neuro_devices');v['rooms']['P4102'].pop("pacemaker", None);v['rooms']['P4102'].pop("diet", None)
    v['rooms']['P4102']['unknown']='KEEP'
    with pytest.raises(ValueError):upgrade_vault(v)


def test_current_devices_roundtrip_encrypted_no_plaintext():
    s=imported(block(PIV)+'\n'+block(EVD,'v'));v=save_sheet_in(new_vault(),s)
    key=generate_key();blob=seal_vault(v,key)
    assert b'Clamped' not in blob and b'Forearm' not in blob
    assert open_vault(blob,key)==v


def test_device_only_and_evd_only_handoffs_included_in_print_all():
    a=imported(block(PIV));b=imported(block(EVD,'v'));b['room']='P4104'
    ready=available_handoffs(new_vault(),{'P4102':a,'P4104':b})
    assert len(ready)==2
    pdf=PdfReader(BytesIO(handoffs_pdf(list(ready.values()))))
    assert len(pdf.pages)==2
    assert 'PIV' in pdf.pages[0].extract_text() and 'EVD: Clamped' in pdf.pages[1].extract_text()


def test_footer_at_bottom_of_one_page_pdf_and_manual_notes_kept():
    s=imported(block(PIV)+'\n'+block(EVD,'v'))
    s['fields']['Access']='MANUAL ACCESS'
    s['fields']['Other']='MANUAL OTHER'
    text=PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()
    assert text.index('Goals / Follow-up')<text.index('Devices:')<text.index('MANUAL ACCESS')
    assert 'MANUAL OTHER' in text
    assert print_layout_info(s)['fits_one_page']


def test_long_device_inventory_is_not_clipped_by_autofit():
    rows='\n'.join('Peripheral IV 01/03/26 Right location '+str(n)+'-Site Assessment: Clean' for n in range(85))
    s=imported(block(rows))
    pdf=PdfReader(BytesIO(handoff_pdf(s)))
    text='\n'.join(p.extract_text() for p in pdf.pages)
    text = re.sub(r'\s+', ' ', text)
    for n in range(85):assert 'Right location '+str(n) in text


def test_edit_callback_autosave_snapshot_and_no_cross_room_writes(app):
    open_room(app);ss=app.st.session_state
    ss['paste']=block(PIV)+'\n'+block(EVD,'v');app.create_handoff()
    s=ss['drafts']['P4102'];row=s['neuro_devices']['rows'][0]
    key='device_'+row['id']+'_status';ss[key]='Open to drain'
    app.device_row_change('P4102','neuro_devices',row['id'],'status',key)
    assert row['status']=='Open to drain'
    ss[key]='Clamped'
    assert app.editor_snapshot('P4102')['neuro_devices']['rows'][0]['status']=='Clamped'
    app.device_row_change('P4104','neuro_devices',row['id'],'status',key)
    assert row['status']=='Open to drain'
    app.device_row_change('P4102','neuro_devices',row['id'],'status',key)
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['neuro_devices']['rows'][0]['status']=='Clamped'


def test_invalid_date_callback_restores_old_value(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block(PIV);app.create_handoff()
    row=ss['drafts']['P4102']['devices']['rows'][0];key='device_'+row['id']+'_date'
    ss[key]='12/35/26';app.device_row_change('P4102','devices',row['id'],'date',key)
    assert row['date']=='01/03/26' and ss[key]=='01/03/26'


def test_full_page_stub_has_unique_device_controls_and_exports(app,monkeypatch):
    open_room(app);ss=app.st.session_state
    ss['paste']=block(PIV+'\nETT 4 mm-Secured at (cm): 18 cm')+'\n'+block(EVD,'v');app.create_handoff()
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_room_switch_removes_device_widgets_and_autosaves(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block(PIV);app.create_handoff()
    row=ss['drafts']['P4102']['devices']['rows'][0];ss['device_'+row['id']+'_label']='PIV EDITED'
    open_room(app,'P4104')
    assert ss['vault']['rooms']['P4102']['devices']['rows'][0]['label']=='PIV EDITED'
    assert not any(k.startswith('device_') for k in ss)
    assert ss['drafts']['P4104']['devices'] is None


def test_schema19_session_upgrade_preserves_unsaved_draft(app):
    open_room(app);app.save_room(None);ss=app.st.session_state
    ss['vault']['schema']=19
    for s in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):
        s.pop('devices');s.pop('neuro_devices');s.pop("pacemaker", None);s.pop("diet", None)
    ss['drafts']['P4102']['fields']['Neurologic']='UNSAVED MANUAL NOTE'
    app.upgrade_existing_session()
    assert ss['drafts']['P4102']['fields']['Neurologic']=='UNSAVED MANUAL NOTE'
    assert ss['drafts']['P4102']['devices'] is None and ss['vault']['schema']==33

@pytest.mark.parametrize('text', ['Endotracheal Tube: None','Urinary Catheter: --','Intracranial Pressure Monitor: No data recorded','No EVD','No ETT present','Tracheostomy Tube: N/A'])
def test_empty_headers_and_absence_statements_do_not_invent_devices(text):
    for section in ('u','v'):
        r=parse_devices(text,section)
        assert r.data is None and not r.error and not r.diagnostics


def test_unknown_date_not_inferred_from_current_date():
    r=parse_devices('CVC Right Internal jugular-Site Assessment: Clean')
    assert r.data['rows'][0]['date']==''


def test_device_named_date_preserved_not_replaced_by_assessment_prose():
    r=parse_devices('PICC 01/03/26 Left Arm-Site Assessment: Changed dressing on 01/05/26')
    assert r.data['rows'][0]['date']=='01/03/26'
    assert '01/05/26' not in json.dumps(r.data)


def test_device_failure_does_not_replace_previous_manual_access_notes():
    s=new_sheet('P4102');s['fields']['Access']='Manually confirmed line'
    r=import_sections(s,'uuuuuuuu\nLines:\n'+PIV,new_vault()['settings'])
    assert r.sheet['fields']['Access']=='Manually confirmed line'
    assert 'Manually confirmed line' in handoff_text(r.sheet)


def test_explicit_security_location_and_depth_stay_with_same_ett():
    s=imported(block('ETT 4 mm-Secured at (cm): 18 cm\nETT 4 mm-Secured Location: Right naris'))
    assert len(s['devices']['rows'])==1
    assert s['devices']['rows'][0]['secured']=='18 cm, Right naris'
    assert 'Last Secure Site: 18 cm, Right naris' in devices_text(s)


def test_new_patient_and_shared_reset_clear_device_snapshots(app):
    from handoff_reset import cleared_vault
    open_room(app);ss=app.st.session_state
    ss['paste']=block(PIV)+'\n'+block(EVD,'v');app.create_handoff();app.save_room(None)
    app.start_new_patient()
    assert ss['drafts']['P4102']['devices'] is None and ss['drafts']['P4102']['neuro_devices'] is None
    cleared=cleared_vault(ss['vault'])
    assert cleared['rooms']=={} and cleared['settings']==ss['vault']['settings']
