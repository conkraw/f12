"""v6.33 regressions with synthetic orders only. No live clinical integration."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import re
import pytest
import fitz
from cryptography.fernet import Fernet
from infusion_rates import (parse_last_admin, validate_admin_fields, administration_display,
                            continuous_order, requested_titration, merge_admin_edits)
from medications import parse_medications, format_medication, validate_medication, remap, upsert_rule
from infusions import infusion_entry, cardiovascular_body
from fen_gi import (automatic_group, effective_section, group_for, set_gi_rule,
                   apply_gi_rules, validate_gi_rules, fen_gi_body)
from models import (new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault,
                    fields_with_medications, save_sheet_in, SCHEMA_VERSION)
from security import seal_vault, open_vault
from parser import parse_smartphrase
from importing import import_sections
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_workflow_print import Store, change_room

STAMP = datetime(2026, 1, 8, 16, 0, tzinfo=timezone.utc)
HEADER = 'Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n'


def order(name='nitroprusside infusion', dose='0.1-6 mcg/kg/min (Dosing Weight)',
          route='Intravenous', frequency='Continuous', rate='2.52 mL/hr at 01/08/26 1016',
          admin='6 mcg/kg/min at 01/08/26 1016', section='Cardiovascular', spaced=False):
    cells = [name, dose, route, frequency, 'PRIVATE_PROVIDER_SENTINEL', rate, admin]
    line = '•\t' + '\t'.join(cells)
    if spaced:
        line = '•\u2002\u2002' + '\u2002\u2002'.join(cells)
    result = parse_medications(HEADER + line)
    assert not result.error, result.issues
    assert len(result.rows) == 1
    row = result.rows[0]
    row['section'] = section
    return row


def text_pdf(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(page.get_text() for page in doc)


@pytest.mark.parametrize('name', ['nitroprusside infusion', 'sodium nitroprusside infusion',
                                 'niCARdipine (Cardene) infusion', 'norepinephrine infusion',
                                 'noradrenaline infusion', 'Levophed infusion'])
def test_named_titration_uses_last_admin_not_range_or_pump(name):
    row = order(name=name)
    before = deepcopy(row)
    assert requested_titration(row)
    out = infusion_entry(row, rich=True, handoff_only=True)
    assert '<b><u>Last Admin rate: 6 mcg/kg/min</u></b>' in out
    assert 'Recorded rate: 2.52 mL/hr' in out
    assert '01/08/26 1016' in out
    assert '0.1-6' not in out and '(Dosing Weight)' not in out
    assert row == before and row['dose'] == '0.1-6 mcg/kg/min (Dosing Weight)'
    assert '0.1-6' not in format_medication(row)


@pytest.mark.parametrize('name', ['esmolol infusion', 'milrinone infusion', 'fentanyl infusion',
                                 'heparin infusion', 'synthetic continuous infusion'])
def test_other_continuous_orders_use_actual_rate_without_drug_list_inference(name):
    row = order(name=name, dose='1 mcg/kg/min', admin='0.25 mcg/kg/min at 01/08/26 1200')
    assert administration_display(row)[1] == '0.25 mcg/kg/min'
    assert row['dose'] == '1 mcg/kg/min'
    assert 'Dose: 1 mcg/kg/min' not in infusion_entry(row)


@pytest.mark.parametrize('value', ['0 mcg/kg/min', '0.01 mcg/kg/min', '2.5 mg/hr', '10 Units/kg/hr',
                                  '0.0001 units/kg/min', '100 ng/kg/min', '.25 mg/kg/h', '1,000 mcg/hr',
                                  '2 µg/kg/min', '3 μg/min', '4 ug/kg/hour', '1 mL/hr'])
def test_explicit_rate_units_preserved(value):
    d = parse_last_admin(value + ' at 01/08/26 1016')
    assert d['last_admin_rate'] == value and d['last_admin_status'] == 'rate'
    validate_admin_fields(d)


@pytest.mark.parametrize('prefix', ['', 'Rate/Dose Change: ', 'Rate Verify: ', 'New Bag: ', 'Restarted: ', 'Given: '])
def test_labeled_actual_rate_is_read_only_when_numeric_rate_present(prefix):
    data = parse_last_admin(prefix + '0.5 mcg/kg/min at 01/08/26 1200')
    assert data['last_admin_rate'] == '0.5 mcg/kg/min'


@pytest.mark.parametrize('admin', ['', 'Rate Verify at 01/08/26 1100', 'New Bag at 01/08/26 1100',
                                  'Given at 01/08/26 1100', '2 mg at 01/08/26 1100',
                                  '0.1-6 mcg/kg/min at 01/08/26 1100',
                                  '1 mcg/kg/min at 01/08/26 1100 2 mcg/kg/min at 01/08/26 1200',
                                  '1 mcg/kg/min at 02/31/26 1100', 'PRIVATE_ADMIN_SENTINEL'])
def test_ambiguous_or_absent_rate_never_substitutes_ordered_range(admin):
    row = order(admin=admin)
    out = infusion_entry(row)
    assert 'Last Admin rate: UNK' in out
    assert 'Dose: 0.1-6' not in out and 'PRIVATE_ADMIN' not in json.dumps(row)
    assert row['last_admin_rate'] == ''


@pytest.mark.parametrize('status,stored', [('Stopped','stopped'), ('Paused','paused'), ('Held','held'),
                                          ('Not given','not_given'), ('Not administered','not_administered'),
                                          ('Discontinued','discontinued')])
def test_nonrunning_event_keeps_exact_meaning_and_does_not_print_old_pump_rate(status,stored):
    row = order(admin=status + ' at 01/08/26 1200')
    assert row['last_admin_status'] == stored
    out = infusion_entry(row)
    assert 'Last Admin: ' + status in out
    assert 'Recorded rate' not in out and '2.52 mL/hr' not in out
    assert row['last_rate'] == '2.52 mL/hr' and row['include']
    assert '@ 2.52' not in format_medication(row)


def test_zero_rate_prints_as_zero_not_missing_or_discontinued():
    row = order(admin='0 mcg/kg/min at 01/08/26 1200', rate='0 mL/hr at 01/08/26 1200')
    for text in [format_medication(row), infusion_entry(row)]:
        assert 'Last Admin rate: 0 mcg/kg/min' in text and 'UNK' not in text
        assert 'discontinued' not in text.lower()


@pytest.mark.parametrize('frequency', ['q6h', 'q30 min PRN', 'Once', 'Continuous PRN', 'Daily'])
def test_intermittent_and_prn_doses_not_replaced(frequency):
    row = order(name='fentanyl injection', dose='5 mcg', frequency=frequency,
                admin='0.3 mcg/kg/hr at 01/08/26 1000')
    assert not continuous_order(row) and 'last_admin_rate' not in row
    assert 'Dose: 5 mcg' in format_medication(row)
    assert 'Last Admin rate' not in format_medication(row)


def test_pn_total_amount_and_status_do_not_become_hourly_rate():
    for admin in ('246 mL at 01/08/26 1000', 'New Bag at 01/08/26 1000', 'Rate Verify at 01/08/26 1000'):
        row = order(name='Pediatric 2-in-1 PN (Continuous)', dose='246 mL', frequency='Continuous PN', admin=admin,
                    rate='10.3 mL/hr at 01/08/26 1000',section='FEN / GI')
        assert 'Dose: 246 mL' in format_medication(row)
        assert '@ 10.3 mL/hr' in format_medication(row)
        assert not row['last_admin_rate']


def test_custom_handoff_text_remains_authoritative():
    row = order()
    row['custom_text'] = 'Clinician-checked custom text'
    assert infusion_entry(row) == row['custom_text']
    assert format_medication(row) == row['custom_text']


def test_different_orders_never_share_last_admin():
    a = order(admin='1 mcg/kg/min at 01/08/26 1000')
    b = order(admin='3 mcg/kg/min at 01/08/26 1200')
    out = cardiovascular_body('', [a, b])
    assert out.count('nitroprusside infusion') == 2
    assert 'Last Admin rate: 1' in out and 'Last Admin rate: 3' in out


@pytest.mark.parametrize('field,value', [('last_admin_rate','6'), ('last_admin_rate','5 mg'),
                                        ('last_admin_rate','0.1-6 mcg/kg/min'), ('last_admin_rate','-1 mg/hr'),
                                        ('last_admin_time','PRIVATE_NAME'), ('last_admin_time','01/08/26 2561'),
                                        ('last_admin_status','running probably')])
def test_invalid_manual_admin_fields_rejected(field,value):
    row = order()
    row[field] = value
    with pytest.raises(ValueError): validate_medication(row)


def test_provider_and_raw_admin_never_saved_including_invalid_fields():
    row = order(admin='PRIVATE_ADMIN_SENTINEL at 01/08/26 1000')
    assert 'PRIVATE_' not in json.dumps(row)
    assert row['last_admin_status'] == 'unreadable'
    assert 'provider' not in row and 'raw_admin' not in row


def test_spaced_input_with_seven_visible_fields_matches_tabs():
    a, b = order(), order(spaced=True)
    a.pop('id'); b.pop('id')
    assert a == b


def test_spaced_input_preserves_pn_connectors_and_blank_topical_dose():
    d='\u2002'
    rows=[d.join(['Pediatric 2-in-1 PN (Continuous)','246 mL','Intravenous','Continuous PN','PRIVATE_PROVIDER','10.3 mL/hr at 01/08/26 1000','Rate Verify at 01/08/26 1000']),
          d.join(['fat emulsion syringe','2 g/kg (Dosing Weight)','Intravenous','Continuous PN','PRIVATE_PROVIDER','1.75 mL/hr at 01/08/26 1000','7 g at 01/08/26 1000']),
          d.join(['zinc oxide ointment','','Topical','PRN','PRIVATE_PROVIDER','',''])]
    source='Medications:\nMedication'+d+'Dose'+d+'Route'+d+'Frequency'+d+'Provider'+d+'Last Rate'+d+'Last Admin\n'
    source += '•'+d+rows[0]+'\n'+d+'And\n•'+d+rows[1]+'\n•'+d+rows[2]
    r=parse_medications(source)
    assert not r.error and len(r.rows)==3
    assert r.rows[1]['name'].startswith('And: fat emulsion')
    assert r.rows[1]['dose']=='2 g/kg (Dosing Weight)' and r.rows[2]['dose']==''
    assert r.rows[2]['route']=='Topical' and r.rows[2]['frequency']=='PRN'


def test_single_spaced_numeric_rate_not_assigned_to_ambiguous_column():
    r=parse_medications('Medications:\n•\u2002nitroprusside infusion\u20020.1-6 mcg/kg/min\u2002Intravenous\u2002Continuous\u2002PRIVATE_PROVIDER\u20026 mcg/kg/min at 01/08/26 1016')
    assert not r.error
    assert r.rows[0]['last_admin_rate']==r.rows[0]['last_rate']==''
    assert any('boundary' in w for w in r.rows[0]['warnings'])
    assert 'UNK' in format_medication(r.rows[0])


def test_ordinary_space_prose_is_not_a_table():
    assert parse_medications('Medications:\n• nitroprusside 0.1-6 mcg/kg/min Intravenous Continuous Private Provider 6 mcg/kg/min').error


@pytest.mark.parametrize('name',['ondansetron injection 2 mg', 'ondansetron (Zofran) tablet',
                                'ondansetron ODT tablet', 'Zofran injection',
                                '[Held by provider] ondansetron suspension',
                                '[START ON 1/9/2026] ondansetron tablet'])
@pytest.mark.parametrize('frequency',['q8h PRN','q8h'])
def test_ondansetron_grouped_in_fengi_automatically(name,frequency):
    row=order(name=name,dose='2 mg',frequency=frequency,admin='2 mg at 01/08/26 1000',section='Other Medications')
    assert automatic_group(row)==group_for(row)=='antiemetic'
    assert effective_section(row)=='FEN / GI'
    out=fen_gi_body('',[row],None)
    assert out.startswith('Antiemetics\n') and name in out and frequency in out


def test_unrelated_name_not_grouped_and_explicit_override_respected():
    row=order(name='synthetic different drug with ondansetron comment',frequency='q8h')
    assert not automatic_group(row)
    row['name']='ondansetron injection'
    rules=set_gi_rule([],row,'other')
    altered=apply_gi_rules([row],rules)[0]
    assert not group_for(altered) and effective_section(altered)=='Cardiovascular'
    rules=set_gi_rule([],row,'antiemetic')
    validate_gi_rules(rules)
    assert group_for(apply_gi_rules([row],rules)[0])=='antiemetic'


def test_hidden_ondansetron_does_not_print():
    row=order(name='ondansetron injection',frequency='q8h')
    row['hidden']=True
    assert not fen_gi_body('',[row],None)


def synthetic_sheet():
    s=new_sheet('P4102')
    s['fields']['Diagnoses']='Synthetic formatting test'
    s['medications']=[order(),order(name='ondansetron (Zofran) injection 2 mg',dose='2 mg',frequency='q8h PRN',admin='2 mg at 01/08/26 1000',section='Other Medications')]
    return s


def test_text_html_pdf_all_have_same_rate_and_one_antiemetic():
    s=synthetic_sheet(); before=deepcopy(s)
    for output in [handoff_text(s,STAMP),handoff_html(s,STAMP),text_pdf(handoff_pdf(s,STAMP))]:
        flat=re.sub(r'\s+',' ',output)
        assert 'Last Admin rate: 6' in flat and '0.1-6' not in flat
        assert 'Antiemetics' in flat
        assert output.count('ondansetron')==1
    h=handoff_html(s,STAMP)
    assert '<b><u>Last Admin rate: 6 mcg/kg/min</u></b>' in h
    assert s==before


def test_two_room_print_keeps_each_rate():
    a=synthetic_sheet(); b=synthetic_sheet(); b['room']='P4104'
    b['medications'][0]['last_admin_rate']='0.5 mcg/kg/min'
    data=handoffs_pdf([a,b],STAMP)
    with fitz.open(stream=data,filetype='pdf') as doc:
        assert len(doc)==2
        assert 'Last Admin rate: 6' in doc[0].get_text()
        assert 'Last Admin rate: 0.5' in doc[1].get_text()


def test_old_archive_migration_preserves_rows_notes_and_save_times():
    v=new_vault(); v['rooms']['P4102']=synthetic_sheet()
    for row in v['rooms']['P4102']['medications']:
        for key in ('last_admin_rate','last_admin_time','last_admin_status'):row.pop(key,None)
    v['schema']=24
    before=deepcopy(v); out=upgrade_vault(v)
    assert out['schema']==33 and v==before
    out['schema']=24
    assert out==before


def test_new_fields_and_antiemetic_rules_roundtrip_encrypted():
    v=new_vault();s=synthetic_sheet();v=save_sheet_in(v,s)
    v['settings']['medication_gi_groups']=set_gi_rule([],s['medications'][1],'antiemetic')
    key=Fernet.generate_key().decode()
    token=seal_vault(v,key)
    assert b'mcg/kg/min' not in token
    assert open_vault(token,key)==v


def test_new_b_replaces_admin_fields_and_other_sections_remain():
    s=synthetic_sheet();s['fields']['Neurologic']='Keep separate note'
    source='b'*12+'\n'+HEADER+'• nitroprusside infusion\t0.1-6 mcg/kg/min\tIntravenous\tContinuous\t\t\t\n'+'b'*12
    r=import_sections(s,source,new_vault()['settings'])
    assert not r.errors and r.sheet['fields']['Neurologic']=='Keep separate note'
    assert r.sheet['medications'][0]['last_admin_rate']==''
    assert '6 mcg/kg/min [' not in format_medication(r.sheet['medications'][0])


def test_admin_callback_and_room_switch_capture_latest_edit(app):
    open_room(app);ss=app.st.session_state
    row=order();ss['drafts']['P4102']['medications']=[row]
    prefix='med_draft_'+row['id']+'_'
    ss[prefix+'last_admin_status']='rate'
    ss[prefix+'last_admin_rate']='2 mcg/kg/min'
    app.medication_row_change('P4102',row['id'],'last_admin_rate',prefix+'last_admin_rate')
    assert row['last_admin_rate']=='2 mcg/kg/min' and row['last_admin_time']==''
    ss[prefix+'last_admin_rate']='3 mcg/kg/min' # blurred edit delivered with room switch
    ss[prefix+'last_admin_time']='01/08/26 1300'
    store=Store(state=ss);change_room(app,store)
    saved=ss['vault']['rooms']['P4102']['medications'][0]
    assert saved['last_admin_rate']=='3 mcg/kg/min' and saved['last_admin_time']=='01/08/26 1300'
    assert saved['dose']=='0.1-6 mcg/kg/min (Dosing Weight)'


def test_admin_status_callback_removes_only_current_rate(app):
    open_room(app);ss=app.st.session_state;row=order();ss['drafts']['P4102']['medications']=[row]
    key='med_draft_'+row['id']+'_last_admin_status';ss[key]='stopped'
    app.medication_row_change('P4102',row['id'],'last_admin_status',key)
    assert row['last_admin_status']=='stopped' and row['last_admin_rate']==''
    assert row['last_rate']=='2.52 mL/hr'


def test_invalid_admin_edit_rolls_back(app):
    open_room(app);ss=app.st.session_state;row=order();ss['drafts']['P4102']['medications']=[row]
    before=deepcopy(row);key='med_draft_'+row['id']+'_last_admin_rate';ss[key]='not a rate'
    app.medication_row_change('P4102',row['id'],'last_admin_rate',key)
    assert row==before and ss['notice'][0]=='error'


def test_readonly_editor_does_not_add_optional_fields_to_legacy_row(app,monkeypatch):
    open_room(app);ss=app.st.session_state;row=order()
    for key in ('last_admin_rate','last_admin_time','last_admin_status'):row.pop(key)
    ss['drafts']['P4102']['medications']=[row]
    before=deepcopy(ss['drafts']['P4102'])
    equip(app,monkeypatch);app.medication_editor([row],'P4102',None)
    snapshot=app.editor_snapshot('P4102')
    assert not any(key.startswith('last_admin_') for key in snapshot['medications'][0])
    snapshot['medications'][0].pop('infusion_mode',None)
    assert snapshot==before


def test_antiemetic_choice_remembered_without_order_duplication(app):
    open_room(app);ss=app.st.session_state
    row=order(name='synthetic antiemetic',frequency='q8h',dose='2 mg');ss['drafts']['P4102']['medications']=[row]
    key='med_draft_'+row['id']+'_gi_mode';ss[key]='antiemetic'
    app.medication_row_change('P4102',row['id'],'gi_mode',key)
    assert ss['vault']['settings']['medication_gi_groups'][0]['mode']=='antiemetic'
    snapshot=app.editor_snapshot('P4102');out=handoff_text(snapshot,STAMP)
    assert out.count('synthetic antiemetic')==1 and 'Antiemetics' in out
