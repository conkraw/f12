"""Source-pattern regressions. No full patient records or identifiers are stored."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import pytest
from pypdf import PdfReader
from models import new_sheet, new_vault, save_sheet_in, fields_with_medications, validate_sheet
from ventilation import parse_ventilation, format_ventilation, home_vent, LABELS, unwrap_vent_line
from noninvasive import parse_respiratory, format_noninvasive
from importing import import_sections
from security import generate_key, seal_vault, open_vault
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from ventilator_modes import MODE_SPECS, display_mode, control_family
from test_callbacks import app, open_room

PC = '''Invasive Ventilation:
Mode: Vent Mode: Pressure Control - Intermittent Mandatory Ventilation
Respiratory Rate: Resp Rate (Set): 12
Set PIP: PIP Set (cm H2O): 35 cm H2O
Observed PIP: PIP Observed (cm H2O)  Avg: 35 cm H2O  Min: 35 cm H2O  Max: 35 cm H2O
Set TV:
Observed TV: Vt Insp ml  Avg: 70.5  Min: 69  Max: 72
Set PEEP: PEEP (cm H2O): 14 cm H2O
Inspiratory Time: Insp Time (sec): 1 sec
FiO2: FiO2 set (%): 45 %
Pressure Support: Pressure Support (cm H2O): 21 cm H20
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
'''
PC_EXPECTED = '''Mode: PC-IMV
Set RR: 12
Set PIP: 35 cm H2O
Observed PIP: Avg: 35 Min: 35 Max: 35 cm H2O
Observed TV: Avg: 70.5 Min: 69 Max: 72 mL
Set PEEP: 14 cm H2O
Inspiratory Time: 1 sec
Pressure Support: 21 cm H2O
FiO2: 45 %'''
PRVC = '''Invasive Ventilation:
Mode: Vent Mode: Volume Targeted Pressure Control - Continuous Mandatory Ventilation
Respiratory Rate: Resp Rate (Set): 18
Set PIP:
Observed PIP: PIP Observed (cm H2O)  Avg: 19.7 cm H2O  Min: 8.8 cm H2O  Max: 26 cm H2O
Set TV: Vt (Set, mL): 35 mL
Observed TV: No data recorded
Set PEEP: PEEP (cm H2O): 5 cm H2O
Inspiratory Time: Insp Time (sec): 0.9 sec
FiO2:
Pressure Support: Pressure Support (cm H2O): 10 cm H20
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
'''
HOME = '''Invasive Ventilation:
Mode: Vent Mode: Volume Targeted Pressure Control - Intermittent Mandatory Ventilation
Respiratory Rate: Resp Rate (Set): 10
Set PIP:
Observed PIP: PIP Observed (cm H2O)  Avg: 15.6 cm H2O  Min: 15 cm H2O  Max: 16 cm H2O
Set TV: Vt (Set, mL): 450 mL
Observed TV: No data recorded
Set PEEP: PEEP (cm H2O): 5 cm H2O
Inspiratory Time:
FiO2:
Pressure Support:
Home Ventilator Settings:
Pmin: Pmin: 10 cmH2O
Pmax: Pmax: 20 cmH2O
Timin: Ti Min: 0.9
Timax: Ti Max: 1.2
'''

def wrapped(c, d=None):
    return 'c'*20+'\n'+c+'\n'+'c'*20 + ('\n'+'d'*20+'\n'+d+'\n'+'d'*20 if d is not None else '')


def imported(c, room='P4102', d=None):
    result=import_sections(new_sheet(room),wrapped(c,d),new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    return result.sheet


def test_pc_requested_order_and_exact_values():
    r=parse_respiratory(PC, 'O2 Delivery Method: Trach tube\nFiO2 (%): 50 %')
    assert not r.error and not r.devices
    assert format_ventilation(r.invasive)==PC_EXPECTED
    assert 'TVe' not in format_ventilation(r.invasive)
    assert r.invasive['mode']=='Pressure Control - Intermittent Mandatory Ventilation'
    assert r.invasive['values']['PIP Observed (cm H2O)'].startswith('Avg: 35')


def test_prvc_cmv_requested_profile():
    text=format_ventilation(parse_ventilation(PRVC).data)
    assert text=='''Mode: PRVC
Set RR: 18
Set TV: 35 mL
Observed PIP: Avg: 19.7 Min: 8.8 Max: 26 cm H2O
Set PEEP: 5 cm H2O
Inspiratory Time: 0.9 sec
Pressure Support: 10 cm H2O'''
    assert 'Observed PIP:' in text and 'Set PIP:' not in text and 'Observed TV:' not in text and 'No data' not in text


def test_prvc_imv_keeps_subtype_but_uses_volume_target():
    c=PRVC.replace('Continuous Mandatory','Intermittent Mandatory').replace('18','16').replace('35 mL','200 mL')
    text=format_ventilation(parse_ventilation(c).data)
    assert 'Mode: PRVC-IMV' in text and 'Set TV: 200 mL' in text


def test_home_device_and_all_four_bounds():
    r=parse_ventilation(HOME)
    assert not r.error and home_vent(r.data)
    assert format_ventilation(r.data)=='''Device: Home Vent
Mode: PRVC
Set RR: 10
Set TV: 450 mL
Observed PIP: Avg: 15.6 Min: 15 Max: 16 cm H2O
Set PEEP: 5 cm H2O
Pmin: 10 cm H2O
Pmax: 20 cm H2O
Tmin: 0.9 sec
Tmax: 1.2 sec'''


@pytest.mark.parametrize('blank',['','--','N/A','None','No data recorded'])
def test_empty_home_template_never_calls_device_home(blank):
    c=PC.replace('Pmin:\n','Pmin: '+blank+'\n')
    r=parse_ventilation(c)
    assert not r.error and not home_vent(r.data)
    assert 'Home Vent' not in format_ventilation(r.data)


@pytest.mark.parametrize('pmin',['0','10','10 cmH2O','(S) 10 cmH2O'])
def test_numeric_pmin_triggers_home_including_zero(pmin):
    r=parse_ventilation(PC.replace('Pmin:\n','Pmin: '+pmin+'\n'))
    assert home_vent(r.data)
    assert 'Mode: PC\n' in format_ventilation(r.data)
    assert 'Set TV:' not in format_ventilation(r.data)


@pytest.mark.parametrize('mode,code',[
 ('Volume Control - Intermittent Mandatory Ventilation','VC-IMV'),
 ('Volume Control - Continuous Mandatory Ventilation','VC-CMV'),
 ('VC','VC'), ('PC','PC'), ('PC - IMV','PC-IMV'),
 ('Volume Targeted PC - IMV','PRVC-IMV'),
 ('Volume Targeted PC - CMV','PRVC'),
 ('Volume Targeted PC - PS','PRVC-PS'),
])
def test_explicit_mode_aliases(mode,code):
    r=parse_ventilation(PRVC.replace('Volume Targeted Pressure Control - Continuous Mandatory Ventilation', mode))
    assert not r.error and r.data is not None
    assert format_ventilation(r.data).splitlines()[0]=='Mode: '+code
    if code.startswith('VC'):
        assert 'Set TV: 35 mL' in format_ventilation(r.data)


@pytest.mark.parametrize('mode,spec', list(MODE_SPECS.items()))
def test_all_screenshot_mode_abbreviations_have_declared_mapping(mode,spec):
    assert display_mode(mode)==spec[0]
    assert control_family(mode)==spec[1]


def test_pc_never_uses_observed_pip_as_set():
    c=PC.replace('Set PIP: PIP Set (cm H2O): 35 cm H2O','Set PIP:')
    r=parse_ventilation(c)
    assert not r.error and any('PIP Set' in issue for issue in r.issues)
    assert 'Set PIP:' not in format_ventilation(r.data)
    assert r.data['values']['PIP Observed (cm H2O)']


def test_pc_pressure_above_peep_comment_not_dropped_or_added_again():
    c=PC.replace('Set PIP: PIP Set (cm H2O): 35 cm H2O','Set PIP: PIP Set (cm H2O): 21 cm H2O (PC above PEEP = Total PIP 35)')
    r=parse_ventilation(c)
    assert 'Set PIP: 21 cm H2O (PC above PEEP = Total PIP 35)' in format_ventilation(r.data)
    assert '49 cm' not in format_ventilation(r.data)


@pytest.mark.parametrize('label,out',[
 ('Vt Insp ml','Observed TV'),('Vt Exp ml','Observed TV'),
 ('VTI','Observed TV'),('VTE','Observed TV'),
 ('Vt (observed, mL)','Observed TV'),
])
def test_observed_volume_source_kind_is_not_interchanged(label,out):
    c=PC.replace('Vt Insp ml',label)
    assert out+': Avg: 70.5 Min: 69 Max: 72 mL' in format_ventilation(parse_ventilation(c).data)


def test_expiratory_volume_preferred_when_both_exist_without_merging():
    c=PC+'\nVt Exp ml: Avg: 65 Min: 60 Max: 68'
    r=parse_ventilation(c)
    assert 'Observed TV: Avg: 65 Min: 60 Max: 68 mL' in format_ventilation(r.data)
    assert 'Avg: 70.5' not in format_ventilation(r.data)
    assert 'Vt Insp ml' in r.data['values']
    assert 'Vt Exp ml' in r.data['values']


def test_single_observed_value_does_not_invent_range():
    c=PC.replace('Vt Insp ml  Avg: 70.5  Min: 69  Max: 72','Vt Insp ml: 70')
    text=format_ventilation(parse_ventilation(c).data)
    assert 'Observed TV: 70 mL' in text and 'Observed TV: Avg:' not in text


def test_last_observed_rate_and_target_volume_never_replace_set_values():
    c=PRVC.replace('Resp Rate (Set): 18','').replace('Set TV: Vt (Set, mL): 35 mL','Set TV:')
    c+='\nResp Rate Observed: 29\nVt Set/Target ml: 39'
    text=format_ventilation(parse_ventilation(c).data)
    assert 'Set TV:' not in text and 'Set RR:' not in text


def test_c_empty_fio2_not_recovered_from_d_or_saved_settings():
    c=parse_respiratory(PRVC,'FiO2 (%): 65 %')
    assert not c.error and 'FiO2' not in format_ventilation(c.invasive)


def test_set_fio2_preferred_but_both_fields_retained():
    r=parse_ventilation(PC+'\nFiO2 (%): 50 %')
    assert 'FiO2: 45 %' in format_ventilation(r.data)
    assert r.data['values']['FiO2 (%)']=='50 %'


@pytest.mark.parametrize('label',['Pmin','Pmax','Ti Min','Ti Max','PIP Set (cm H2O)','Vt Insp ml'])
def test_new_fields_survive_encryption(label):
    s=imported(HOME)
    s['ventilation']['values'][label]='9'
    v=save_sheet_in(new_vault(),s); k=generate_key()
    encrypted=seal_vault(v,k)
    assert open_vault(encrypted,k)==v
    assert b'Home Vent' not in encrypted


def test_conflict_rejects_respiratory_section_but_other_import_succeeds():
    original=imported(PC)
    text=wrapped(PC+'\nResp Rate (Set): 99')+'\n'+'a'*20+'\nDiagnoses:\n1. Synthetic update\n'+'a'*20
    r=import_sections(original,text,new_vault()['settings'])
    assert r.errors and r.sheet['ventilation']==original['ventilation']
    assert 'Synthetic update' in r.sheet['fields']['Diagnoses']
    assert 'cd' in r.sheet['import_warnings']
    assert 'IMPORT REVIEW' not in handoff_text(r.sheet)


def test_blank_duplicate_field_is_not_conflict_or_replacement():
    r=parse_ventilation(PC+'\nSet PIP:\nPIP Set (cm H2O): 35 cm H2O')
    assert not r.error and r.data['values']['PIP Set (cm H2O)']=='35 cm H2O'


def test_ti_min_and_max_are_not_misread_as_range_labels():
    assert unwrap_vent_line('Timin: Ti Min: 0.9')=='Ti Min: 0.9'
    assert unwrap_vent_line('Timax: Ti Max: 1.2')=='Ti Max: 1.2'


@pytest.mark.parametrize('mode', ['Bilevel Non Invasive Ventilation', 'Continuous Positive Airway Pressure - Non Invasive Ventilation'])
def test_new_wrappers_keep_existing_niv_and_hfnc_logic(mode):
    c='Invasive Ventilation:\nMode: Vent Mode: '+mode+'\nFiO2: FiO2 (%): 30 %\nSet PEEP: PEEP (cm H2O): 6 cm H2O'
    d='O2 Delivery Method: High flow nasal cannula\nTotal Inspiratory Pressure (cm H2O): 12 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20\nO2 Flow Rate (L/min): 8 L/min\nFiO2 (%): 40 %'
    r=parse_respiratory(c,d)
    assert not r.error and not r.invasive
    assert [x['device'] for x in r.devices]==(['BiPAP','HFNC'] if mode.startswith('Bilevel') else ['CPAP','HFNC'])


@pytest.mark.parametrize('mode,device',[
 ('Average Volume-Assured Pressure Support - Non Invasive Ventilation','AVAPS NIV'),
 ('Neurally Adjusted Ventilatory Assist - Non Invasive Ventilation','NAVA NIV'),
])
def test_named_advanced_niv_keeps_own_name_not_guessed_bipap(mode,device):
    r=parse_respiratory('Mode: Vent Mode: '+mode+'\nFiO2: FiO2 (%): 30 %','O2 Delivery Method: Mask')
    assert not r.error and not r.invasive
    assert r.devices[0]['device']==device
    assert 'BiPAP' not in format_noninvasive(r.devices)


def test_ps_cpap_with_ett_is_not_niv_but_explicit_hfnc_remains_hfnc():
    c='Mode: Vent Mode: Pressure Support - Continuous Positive Airway Pressure\nSet PEEP: PEEP (cm H2O): 5 cm H2O\nPressure Support: Pressure Support (cm H2O): 8 cm H2O'
    r=parse_respiratory(c,'O2 Delivery Method: Endotracheal tube')
    assert not r.error and 'Mode: PS-CPAP' in format_ventilation(r.invasive)
    r=parse_respiratory(c,'O2 Delivery Method: High flow nasal cannula\nO2 Flow Rate (L/min): 6 L/min\nFiO2 (%): 35 %')
    assert not r.error and r.invasive is None and any(x['device']=='HFNC' for x in r.devices)


def test_unrelated_sections_preserve_previous_ventilator():
    s=imported(HOME); before=deepcopy(s['ventilation'])
    r=import_sections(s,'a'*20+'\nDiagnoses:\n1. New synthetic\n'+'a'*20,new_vault()['settings'])
    assert r.sheet['ventilation']==before


def test_empty_new_template_clears_prior_settings_without_inventing_support():
    s=imported(HOME)
    c='Invasive Ventilation:\nMode:\nSet PIP:\nSet TV:\nObserved TV: No data recorded\nHome Ventilator Settings:\nPmin:\nPmax:\nTimin:\nTimax:'
    r=import_sections(s,wrapped(c,'Non-invasive Ventilation:'),new_vault()['settings'])
    assert not r.errors and r.sheet['ventilation'] is None and r.sheet['noninvasive']==[]


@pytest.mark.parametrize('label', ['Pmin','Pmax','Ti Min','Ti Max','PIP Set (cm H2O)','Vt Insp ml'])
def test_editor_callback_and_pending_capture_for_new_fields(app,label):
    open_room(app); ss=app.st.session_state; s=imported(HOME)
    app.set_editor('P4102',s)
    index=LABELS.index(label); key='vent_'+s['id']+'_'+str(index)
    ss[key]='7'
    app.ventilation_change('P4102',label,key)
    assert ss['drafts']['P4102']['ventilation']['values'][label]=='7'
    ss[key]='8'
    snap=app.editor_snapshot('P4102')
    assert snap['ventilation']['values'][label]=='8'


def test_exports_one_room_each_no_cross_patient_vent_values():
    a=imported(PC);b=imported(HOME,'P4104')
    doc=PdfReader(BytesIO(handoffs_pdf([a,b])))
    assert len(doc.pages)==2
    assert 'PC-IMV' in doc.pages[0].extract_text()
    assert 'Home Vent' not in doc.pages[0].extract_text()
    assert 'Home Vent' in doc.pages[1].extract_text()
    assert 'Tmin: 0.9 sec' in doc.pages[1].extract_text()
    assert 'PC-IMV' not in doc.pages[1].extract_text()
    for text in (handoff_text(a),handoff_html(a)):
        assert 'Observed TV: Avg: 70.5 Min: 69 Max: 72 mL' in text
        assert 'Vent Mode:' not in text
