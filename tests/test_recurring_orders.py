from recovery_helpers import assert_retained
"""R import is independent of result parsing. All fixtures are synthetic."""
from copy import deepcopy
from io import BytesIO
import json
import re
import uuid
from pathlib import Path
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from recurring_orders import (parse_orders, classify_order, recurring_frequency, validate_orders,
                              selected_orders, orders_text, order_line, empty_orders)
from parser import parse_smartphrase
from importing import import_sections
from models import (new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault,
                    fields_with_medications, save_sheet_in, SCHEMA_VERSION, section_label)
from exports import handoff_pdf, handoffs_pdf, handoff_html, handoff_text
from batching import available_handoffs
from github_store import seal_vault, open_vault
from test_callbacks import app, open_room


def order(name='CBC', frequency='Daily', count=3, extra=''):
    return ('•\t' + name + '\n\tTiming:\tRecurring (' + frequency + ')\n' +
            ('\tNumber of Occurrences:\t' + str(count) + '\n' if count is not None else '') + extra)


def block(*orders):
    return 'Orders Placed This Encounter\nProcedures\n' + ''.join(orders)


def wrap(content):
    return 'r'*16+'\n'+content+'\n'+'R'*16


def read(text):
    result=parse_orders(text)
    assert not result.error,result.error
    return result.data


def sheet(text=None):
    result=import_sections(new_sheet('P4102'),wrap(text or block(order())),new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


@pytest.mark.parametrize('name,category',[
 ('XR chest 1 view','Chest X-ray'),('XR CHEST 2 VIEWS','Chest X-ray'),('CXR','Chest X-ray'),
 ('CBC','CBC'),('CBC auto differential','CBC'),('CBC and differential','CBC'),('Complete blood count','CBC'),
 ('Basic Metabolic Panel','BMP'),('BMP','BMP'),('Magnesium','Magnesium'),('MG','Magnesium'),
 ('Phosphorus','Phosphorus'),('Phosphorous','Phosphorus'),('Phosphate','Phosphorus'),
 ('APTT','Coagulation'),('PTT','Coagulation'),('Protime-INR','Coagulation'),('PT/INR','Coagulation'),
 ('Fibrinogen','Coagulation'),('Coagulation profile','Coagulation'),('PT','Coagulation'),
 ('BLOOD GAS, VENOUS','Blood gas'),('VENOUS BLOOD GASES W/ HGB AND O2 SAT','Blood gas'),
 ('POC CG8 VENOUS BY ISTAT','Blood gas'),('POC EG7 ARTERIAL BY ISTAT','Blood gas'),('POC CG4 CAPILLARY BY ISTAT','Blood gas'),
 ('Lactic acid','Lactic acid'),('Lactate','Lactic acid'),('Lactate, plasma','Lactic acid'),
])
def test_selected_test_types(name,category):
    assert classify_order(name).category==category
    assert len(read(block(order(name)))['rows'])==1


@pytest.mark.parametrize('name',[
 'Comprehensive Metabolic Panel','CMP','Potassium','Triglycerides','Type and screen',
 'MRSA SURVEILLANCE (NP), ON ADMISSION','Chest physiotherapy','ECG 12 lead','CT chest',
 'Respiratory culture','Vital Signs','Monitor intake and output','Pediatric Ventilator',
 'POC ACT (KAOLIN)','Prepare RBC: 1 Unit','Infusion lactate solution','Consult for CBC',
 'Monitor blood gases','Radiology chest CT','XR abdomen 1 view','[Discontinued] CBC','Platelet count','Manual Differential',
])
def test_other_test_types_not_silently_added(name):
    assert classify_order(name) is None
    assert read(block(order(name)))['rows']==[]


@pytest.mark.parametrize('timing,want',[
 ('Recurring (Morning draw)','Morning draw'),('Recurring (Daily)','Daily'),
 ('Recurring (Daily imaging)','Daily imaging'),('Recurring (Daily imgaging)','Daily imaging'),
 ('Recurring (Every 1 hour)','Q1H'),('Recurring (Every 12 hours)','Q12H'),
 ('Recurring (Q6H)','Q6H'),('Recurring (Every 30 minutes)','Q30MIN'),
 ('Recurring (Every 2 days)','Q2D'),('Recurring (Every shift)','Every shift'),
 ('Recurring (Weekly)','Weekly'),('Recurring (Every Monday)','Every Monday'),
 ('Recurring (BID)','BID'),('RECURRING ( DAILY )','Daily'),
])
def test_schedule_normalization(timing,want):
    assert recurring_frequency(timing)==want


@pytest.mark.parametrize('timing',[
 'Once','Daily','Recurring (Once)','Recurring (PROCEDURE ONCE)','Recurring (STAT)',
 'Recurring (Blood - Once)','Recurring (Continuous)','Recurring (Until discontinued)',
 'Recurring (Per protocol)','Recurring (Daily PRN)','Recurring (Every 0 hours)',
 'Recurring (On call)','Recurring (Routine)','Recurring (banana)',
])
def test_not_repeat_schedules(timing):
    assert recurring_frequency(timing) is None
    assert read(block(order().replace('Recurring (Daily)',timing)))['rows']==[]


def test_one_occurrence_scheduled_is_not_filtered_by_count():
    data=read(block(order('Magnesium','Morning draw',1)))
    assert '1 occurrence' in orders_text(data)


def test_duplicate_highest_count_keeps_source_row_not_sum():
    data=read(block(order('XR chest 1 view','Daily imaging',3),order('XR chest 1 view','Daily imaging',7)))
    assert len(data['rows'])==2
    assert len(selected_orders(data))==1
    assert selected_orders(data)[0]['occurrences']==7
    assert '10 occurrences' not in orders_text(data)


def test_duplicate_selection_is_order_independent_for_unequal_counts():
    a=read(block(order(count=8),order(count=4)))
    b=read(block(order(count=4),order(count=8)))
    assert [r['occurrences'] for r in selected_orders(a)]==[8]
    assert [r['occurrences'] for r in selected_orders(b)]==[8]


def test_duplicate_same_count_keeps_first_source_position():
    data=read(block(order(count=7),order(count=7)))
    assert selected_orders(data)[0]['source_index']==0


def test_name_alias_and_case_are_duplicates():
    data=read(block(order('APTT',count=8),order('ptt',count=5),order('CBC auto differential',count=6),order('CBC and differential',count=9)))
    assert [r['occurrences'] for r in selected_orders(data)]==[8,9]


def test_different_orders_and_schedules_not_collapsed():
    data=read(block(order('APTT'),order('Protime-INR'),order('CBC'),order('CBC and differential'),
                    order('BMP','Daily'),order('BMP','Morning draw'),order('BMP','Every 6 hours'),
                    order('BLOOD GAS, VENOUS','Every 1 hour'),order('BLOOD GAS, ARTERIAL','Every 1 hour'),
                    order('XR chest 1 view','Daily imaging'),order('XR chest 2 views','Daily imaging')))
    assert len(selected_orders(data))==11


def test_gas_panels_with_different_additives_remain_separate():
    data=read(block(order('BLOOD GAS, VENOUS'),order('VENOUS BLOOD GASES W/ HGB AND O2 SAT'),order('POC CG8 VENOUS BY ISTAT')))
    assert len(selected_orders(data))==3


def test_equivalent_interval_spelling_matches_but_daily_not_guessed_as_morning():
    data=read(block(order(frequency='Every 12 hours',count=5),order(frequency='Q12H',count=7),order(frequency='Morning draw',count=8)))
    assert len(selected_orders(data))==2
    assert [r['occurrences'] for r in selected_orders(data)]==[7,8]


def test_missing_count_is_explicit_and_lower_priority_than_known():
    data=read(block(order(count=None),order(count=5)))
    assert 'not listed' in order_line(data['rows'][0])
    assert selected_orders(data)[0]['occurrences']==5


@pytest.mark.parametrize('count',['abc','1.5','-1','99999999999','five',''])
def test_bad_counts_fail_without_guessing(count):
    result=parse_orders(block(order(count=count)))
    assert result.error


def test_zero_is_recorded_not_assumed_missing():
    assert '0 occurrences' in orders_text(read(block(order(count=0))))


def test_conflicting_timing_or_count_fails():
    assert parse_orders(block(order(extra='Timing: Recurring (Every 1 hour)\n'))).error
    assert parse_orders(block(order(extra='Number of Occurrences: 19\n'))).error


def test_whitespace_line_wrapping_and_nbsp():
    text=block(order('CBC', 'Daily', 4))
    text=text.replace('Timing:\tRecurring','Timing:\nRecurring').replace('Occurrences:\t4','Occurrences:\n4').replace('Daily','\u00a0Daily\u00a0')
    assert 'Daily | 4 occurrences' in orders_text(read(text))


def test_extra_comments_never_supply_recurrence_or_enter_saved_snapshot():
    text=block(order('Magnesium','Morning draw',5,extra='Reason for exam: PRIVATE_CONTEXT\nExpected Date: 11/01/2026\n'))
    data=read(text)
    assert 'PRIVATE_CONTEXT' not in json.dumps(data)
    assert '2026' not in json.dumps(data)
    assert selected_orders(data)[0]['occurrences']==5


def test_missing_bullet_blocks_instead_of_silently_clearing():
    text=block(order()).replace('•\t','')
    assert parse_orders(text).error


def test_framing_and_lower_upper_r():
    result=parse_smartphrase(wrap(block(order())))
    assert 'r' in result.blocks and not result.invalid
    assert len(sheet()['recurring_orders']['rows'])==1


@pytest.mark.parametrize('body',['','Orders Placed This Encounter\nProcedures','No orders found.'])
def test_explicit_empty_clears_r_only(body):
    original=sheet();original['fields']['Labs']='My note'
    result=import_sections(original,wrap(body),new_vault()['settings'])
    assert not result.errors
    assert result.sheet['recurring_orders']==empty_orders()
    assert result.sheet['fields']['Labs']=='My note'


def test_omitted_r_preserves_schedule_and_nonr_fields_do_not_change():
    original=sheet();before=deepcopy(original)
    result=import_sections(original,'a'*16+'\nDiagnoses:\nSynthetic change\n'+'a'*16,new_vault()['settings'])
    assert result.sheet['recurring_orders']==before['recurring_orders']
    assert original==before
    empty=import_sections(original,wrap(block(order('BMP'))),new_vault()['settings']).sheet
    for key in before:
        if key!='recurring_orders':
            assert empty[key]==before[key]


def test_invalid_r_does_not_partly_overwrite_any_imported_section():
    original=sheet();before=deepcopy(original)
    text='a'*16+'\nDiagnoses:\nSHOULD_NOT_APPLY\n'+'a'*16+'\n'+wrap(block(order(count='bad')))
    result=import_sections(original,text,new_vault()['settings'])
    assert_retained(result, before, "r")
    assert original==before


def test_new_schema_preserves_every_old_field_and_mapping():
    original=new_vault();original['schema']=13;original.pop("reset_generation", None);original["settings"].pop("medication_groups", None);original["settings"].pop("medication_gi_groups", None)
    s=new_sheet('P4102');s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop("intake_output", None);s.pop('recurring_orders');s['fields']['Labs']='LEGACY LAB NOTE'
    original['rooms']['P4102']=s
    before=deepcopy(original)
    upgraded=upgrade_vault(original)
    assert original==before and upgraded['schema']==SCHEMA_VERSION==33
    assert upgraded['rooms']['P4102']==dict(s,recurring_orders=None,intake_output=None,import_warnings={},feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert upgraded['settings']==dict(before['settings'], medication_gi_groups=[], medication_groups=[])


def test_encrypted_migration_and_roundtrip():
    v=new_vault();v['schema']=13;v.pop("reset_generation", None);v["settings"].pop("medication_groups", None);v["settings"].pop("medication_gi_groups", None);s=new_sheet('P4102');s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop("intake_output", None);s.pop('recurring_orders');v['rooms']['P4102']=s
    key=Fernet.generate_key().decode()
    legacy=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    upgraded=open_vault(legacy,key)
    upgraded=save_sheet_in(upgraded,sheet(block(order('Magnesium',count=17))))
    cipher=seal_vault(upgraded,key)
    assert b'Magnesium' not in cipher
    assert open_vault(cipher,key)==upgraded


def test_new_order_field_validates_strictly():
    data=read(block(order()))
    data['rows'][0]['occurrences']=True
    with pytest.raises(ValueError):validate_orders(data)
    data['rows'][0]['occurrences']=3
    data['rows'].append(deepcopy(data['rows'][0]))
    with pytest.raises(ValueError):validate_orders(data)


def test_orders_preserved_in_editor_but_removed_from_handoff_exports():
    s=sheet(block(order('Magnesium','Every 12 hours',17)))
    s['fields']['Labs']='MANUAL NOTE'
    f=fields_with_medications(s)
    assert f['Labs'].startswith('Magnesium | Q12H | 17 occurrences\n-----\nMANUAL NOTE')
    assert section_label('Labs')=='Labs/Imaging'
    html=handoff_html(s);txt=handoff_text(s)
    assert '<th>LABS/IMAGING</th>' not in html and '\nLABS/IMAGING\n' not in txt
    assert 'Q12H' not in html and '17 occurrences' not in txt
    pdf=PdfReader(BytesIO(handoff_pdf(s)));text=re.sub(r'\s+', ' ', ''.join(p.extract_text() for p in pdf.pages))
    assert 'LABS/IMAGING' not in text and '17 occurrences' not in text and 'MANUAL NOTE' not in text
    assert s['fields']['Labs'] == 'MANUAL NOTE' and s['recurring_orders']


def test_orders_only_room_prints_and_blank_import_stays_blank():
    s=sheet();assert available_handoffs(new_vault(),{'P4102':s})=={'P4102':s}
    s['recurring_orders']=empty_orders()
    assert not available_handoffs(new_vault(),{'P4102':s})


def test_print_all_includes_order_snapshots_separately():
    a=sheet(block(order('CBC',count=31)));b=sheet(block(order('Magnesium',count=19)));b['room']='P4104'
    pdf=PdfReader(BytesIO(handoffs_pdf([a,b])))
    assert len(pdf.pages)==2
    assert '31 occurrences' not in re.sub(r'\s+', ' ', pdf.pages[0].extract_text())
    assert '19 occurrences' not in re.sub(r'\s+', ' ', pdf.pages[1].extract_text())
    assert '31 occurrences' not in re.sub(r'\s+', ' ', pdf.pages[1].extract_text())


def test_callback_edit_and_exclusion(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=sheet()
    row=ss['drafts']['P4102']['recurring_orders']['rows'][0]
    key='rorder_'+row['id']+'_occurrences';ss[key]='8'
    app.recurring_order_change('P4102',row['id'],'occurrences',key)
    assert ss['drafts']['P4102']['recurring_orders']['rows'][0]['occurrences']==8
    ss[key]='bad';app.recurring_order_change('P4102',row['id'],'occurrences',key)
    assert ss[key]=='8'
    assert ss['drafts']['P4102']['recurring_orders']['rows'][0]['occurrences']==8
    inc='rorder_'+row['id']+'_include';ss[inc]=False
    app.recurring_order_change('P4102',row['id'],'include',inc)
    assert not orders_text(ss['drafts']['P4102']['recurring_orders'])


def test_latest_pending_edit_captured_before_room_autosave(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=sheet()
    row=ss['drafts']['P4102']['recurring_orders']['rows'][0]
    key='rorder_'+row['id']+'_occurrences';ss[key]='11'
    assert app.editor_snapshot('P4102')['recurring_orders']['rows'][0]['occurrences']==11
    ss['room_choice']='P4104';app.open_room(None)
    assert ss['current_room']=='P4104'
    assert ss['vault']['rooms']['P4102']['recurring_orders']['rows'][0]['occurrences']==11


def test_bad_pending_edit_keeps_outgoing_room_and_vault(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=sheet()
    row=ss['drafts']['P4102']['recurring_orders']['rows'][0]
    key='rorder_'+row['id']+'_occurrences';ss[key]='oops'
    ss['room_choice']='P4104';app.open_room(None)
    assert ss['current_room']=='P4102' and 'P4102' not in ss['vault']['rooms']


def test_ui_render_with_duplicate_and_excluded_rows(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app);ss=app.st.session_state
    s=sheet(block(order(count=3),order(count=7),order('Magnesium')))
    s['recurring_orders']['rows'][-1]['include']=False
    ss['drafts']['P4102']=s
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(data.startswith(b'%PDF') for _,data in downloads if isinstance(data,bytes))


def test_all_existing_sample_imports_continue_to_work():
    for file in (Path(__file__).parents[1]/'examples').glob('*.txt'):
        text=file.read_text()
        if file.name.startswith('synthetic_') and 'aaaaaaa' in text:
            result=import_sections(new_sheet('P4102'),text,new_vault()['settings'])
            assert not result.errors,(file.name,result.errors)
