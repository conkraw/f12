"""6.49 regressions: standalone (S) markers and no opening source sample.

Fixtures are short synthetic source fragments, not patient records.
"""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import pytest
from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_sections
from models import new_sheet, new_vault, save_sheet_in, validate_sheet, automatic_vitals
from noninvasive import parse_respiratory, read_fields
from security import generate_key, seal_vault, open_vault
from user_guide import default_guide
from ventilation import parse_ventilation, format_ventilation, mode_rule, is_present, home_vent
from ventilator_modes import MODE_SPECS, spec, display_mode, control_family, strip_setting_marker
from lab_windows import display_clock
from feeds import parse_feeds
from test_callbacks import app, open_room
from test_ui_smoke import equip, Panel

NOW = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
MODE = 'Volume Targeted Pressure Control - Intermittent Mandatory Ventilation'
C = '''Invasive Ventilation:
Mode: Vent Mode: (S) Volume Targeted Pressure Control - Intermittent Mandatory Ventilation
Respiratory Rate: Resp Rate (Set): 20
Set PIP:
Observed PIP: PIP Observed (cm H2O)  Avg: 23 cm H2O  Min: 21 cm H2O  Max: 26 cm H2O
Set TV: Vt (Set, mL): 210 mL
Observed TV: No data recorded
Set PEEP: PEEP (cm H2O): 7 cm H2O
Inspiratory Time: Insp Time (sec): 0.8 sec
FiO2: FiO2 set (%): 55 %
Pressure Support: Pressure Support (cm H2O): 9 cm H20
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
'''
D = '''Non-invasive Ventilation:
O2 Delivery Method: CPAP/Bi-PAP mask
Total Inspiratory Pressure (cm H2O): 12 cmH20
Expiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20
FiO2 (%): 55 %
O2 Flow Rate (L/min): 25 L/min
'''
EXPECTED = '''Mode: PRVC-IMV
Set RR: 20
Set TV: 210 mL
Observed PIP: Avg: 23 Min: 21 Max: 26 cm H2O
Set PEEP: 7 cm H2O
Inspiratory Time: 0.8 sec
Pressure Support: 9 cm H2O
FiO2: 55 %'''


def block(letter, text):
    return letter*24+'\n'+text+'\n'+letter*24+'\n'


def imported(c=C, d=D, old=None, extra=''):
    with display_clock(NOW):
        result=import_sections(old or new_sheet('P4102'),block('c',c)+block('d',d)+extra,new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    return result.sheet


def test_wrapped_marker_no_longer_omits_invasive_vent_settings():
    r=parse_respiratory(C,D)
    assert not r.error and r.invasive is not None and r.devices==[]
    assert format_ventilation(r.invasive)==EXPECTED
    # Keep the raw mode marker and clinical values in the saved/editor record.
    assert r.invasive['mode']=='(S) '+MODE
    assert r.invasive['values']['Pressure Support (cm H2O)']=='9 cm H20'
    assert any('D-block non-invasive settings were not added' in s for s in r.issues)


@pytest.mark.parametrize('mode,definition',list(MODE_SPECS.items()))
@pytest.mark.parametrize('marker',['(S) ','(s) ','( S )\u00a0','(S)(S) '])
def test_all_named_modes_classify_and_abbreviate_with_marker(mode,definition,marker):
    assert spec(marker+mode)==definition
    assert display_mode(marker+mode)==definition[0]
    assert control_family(marker+mode)==definition[1]
    assert mode_rule(marker+mode)==('excluded' if definition[2] else 'included')


@pytest.mark.parametrize('mode,expected',[
    ('PC - IMV','PC-IMV'),('VC - CMV','VC-CMV'),('PS - CPAP','PS-CPAP'),
    ('PRVC-IMV','PRVC-IMV'),('PC','PC'),('VC','VC'),
    ('Pressure Control','PC'),('Pressure Regulated Volume Control','PRVC'),
])
def test_supported_short_and_generic_modes_keep_meaning(mode,expected):
    r=parse_ventilation('Vent Mode: (S) '+mode+'\nResp Rate (Set): (S) 12')
    assert r.data is not None and not r.error
    assert format_ventilation(r.data).startswith('Mode: '+expected+'\nSet RR: 12')


@pytest.mark.parametrize('marker',['(S)','( S )','(s)(S)'])
def test_markers_before_wrappers_and_known_nested_labels(marker):
    c=C.replace('Mode: Vent Mode: (S)', marker+' Mode: '+marker+' Vent Mode: '+marker)
    c=c.replace('Respiratory Rate: Resp Rate (Set): 20',
                'Respiratory Rate: '+marker+' Resp Rate (Set): '+marker+' 20')
    assert format_ventilation(parse_ventilation(c).data)==EXPECTED


@pytest.mark.parametrize('field,value,expected',[
    ('Resp Rate (Set)','0','Set RR: 0'),
    ('PIP Set (cm H2O)','25 cm H2O','Set PIP: 25 cm H2O'),
    ('PEEP (cm H2O)','8 cm H2O','Set PEEP: 8 cm H2O'),
    ('Insp Time (sec)','0.7 sec','Inspiratory Time: 0.7 sec'),
    ('Pressure Support (cm H2O)','10 cm H20','Pressure Support: 10 cm H2O'),
    ('FiO2 set (%)','45 %','FiO2: 45 %'),
    ('PIP Observed (cm H2O)','Avg: 27 Min: 23 Max: 29','Observed PIP: Avg: 27 Min: 23 Max: 29 cm H2O'),
    ('Vt Insp ml','Avg: 180 Min: 175 Max: 190','Observed TV: Avg: 180 Min: 175 Max: 190 mL'),
    ('Pmin','0 cmH2O','Pmin: 0 cm H2O'),
    ('Pmax','28 cmH2O','Pmax: 28 cm H2O'),
    ('Ti Min','0.5','Tmin: 0.5 sec'),
    ('Ti Max','1.4','Tmax: 1.4 sec'),
])
def test_marked_numeric_fields_preserve_value_and_units(field,value,expected):
    c='Vent Mode: (S) Pressure Control - Intermittent Mandatory Ventilation\nPmin: (S) 0 cmH2O\n'
    if field=='Pmin': c=c.split('\nPmin:')[0]+'\n'
    c+=field+': ( S ) '+value
    r=parse_ventilation(c)
    assert not r.error and r.data is not None
    assert r.data['values'][field]=='( S ) '+value
    assert expected in format_ventilation(r.data)


def test_marked_volume_target_keeps_safety_comment():
    r=parse_ventilation('Vent Mode: (S) '+MODE+'\nVt (Set, mL): (S) 450 mL (safety vt)')
    assert 'Set TV: 450 mL (safety vt)' in format_ventilation(r.data)


def test_pressure_above_peep_comment_not_removed_or_added_again():
    r=parse_ventilation('Vent Mode: (S) Pressure Control\nPIP Set (cm H2O): (S) 21 cm H2O (PC above PEEP)\nPEEP (cm H2O): 14 cm H2O')
    assert 'Set PIP: 21 cm H2O (PC above PEEP)' in format_ventilation(r.data)
    assert '35 cm H2O' not in format_ventilation(r.data)


@pytest.mark.parametrize('mode',['(X) '+MODE,'(Stopped) '+MODE,'(S) Unknown Mode','(S) Not Pressure Control'])
def test_unknown_mode_and_annotation_not_invented(mode):
    r=parse_ventilation('Vent Mode: '+mode+'\nResp Rate (Set): 20')
    assert r.data is None and r.status=='unknown'


@pytest.mark.parametrize('text',['(S)','( S )','(S) No data recorded','(s) --','(S)(S) None'])
def test_marked_blank_values_do_not_create_mode_or_setting(text):
    assert not is_present(text)
    r=parse_respiratory('Vent Mode: '+text+'\nPmin: '+text,'')
    assert r.invasive is None and r.devices==[] and not r.error


def test_matching_duplicates_differing_only_by_marker_not_conflicts():
    c=C+'\nVent Mode: '+MODE+'\nResp Rate (Set): (S) 20\nPEEP (cm H2O): ( S ) 7 cm H2O'
    r=parse_respiratory(c,D)
    assert not r.error and format_ventilation(r.invasive)==EXPECTED


@pytest.mark.parametrize('extra',['Vent Mode: (S) Pressure Control','Resp Rate (Set): (S) 99','PEEP (cm H2O): (S) 9 cm H2O'])
def test_genuine_conflicting_fields_remain_rejected(extra):
    r=parse_respiratory(C+'\n'+extra,D)
    assert r.error and r.invasive is None


def test_noninvasive_unchanged_with_marked_mode_and_values():
    c='Mode: Vent Mode: ( S ) Bilevel Non Invasive Ventilation\nFiO2: (S) 35 %'
    d='O2 Delivery Method: (S) High flow nasal cannula\nTotal Inspiratory Pressure (cm H2O): (S) 12 cmH20\nEPAP: (S) 6 cmH20\nO2 Flow Rate (L/min): (S) 20 L/min\nFiO2 (%): (S) 35 %'
    r=parse_respiratory(c,d)
    assert not r.error and r.invasive is None
    assert [x['device'] for x in r.devices]==['BiPAP','HFNC']
    assert r.devices[0]['values']=={'IPAP':'12 cmH20','EPAP':'6 cmH20','FiO2':'35 %'}


def test_marked_mode_still_authorizes_existing_sbs_fallback():
    s=imported(extra=block('k','SBS Last 24 Hours:\nLast SBS Ever: SBS -1'))
    with display_clock(NOW):
        assert 'SBS: -1 (last available)' in automatic_vitals(s)['Neurologic']
    assert s['sbs_vent_mode']==MODE


def test_failed_conflicting_import_keeps_original_and_blocks_sbs_fallback():
    old=imported(extra=block('k','SBS Last 24 Hours:\nLast SBS Ever: SBS -1'))
    r=import_sections(old,block('c',C+'\nResp Rate (Set): (S) 99'),new_vault()['settings'])
    assert r.errors and r.sheet['ventilation']==old['ventilation']
    with display_clock(NOW):
        assert '(last available)' not in automatic_vitals(r.sheet)['Neurologic']


def test_saved_marker_survives_encrypted_roundtrip_without_data_rewrite():
    s=imported()
    v=save_sheet_in(new_vault(),s)
    before=deepcopy(v)
    key=generate_key()
    restored=open_vault(seal_vault(v,key),key)
    assert restored==before
    assert format_ventilation(restored['rooms']['P4102']['ventilation'])==EXPECTED


def test_pdf_html_text_and_combined_pdf_include_marked_settings_once():
    s=imported()
    html=handoff_html(s,NOW)
    text=handoff_text(s,NOW)
    assert 'Mode: PRVC-IMV' in text and 'Mode: PRVC-IMV' in html
    assert '(S)' not in text and '(S)' not in html
    assert 'Vent Settings' in html
    pdf=PdfReader(BytesIO(handoff_pdf(s,NOW)))
    assert len(pdf.pages)==1
    extracted=pdf.pages[0].extract_text()
    assert extracted.count('Mode: PRVC-IMV')==1
    for phrase in ['Set RR: 20','Set TV: 210 mL','Set PEEP: 7 cm H2O','FiO2: 55 %']:
        assert phrase in extracted
    other=imported();other['room']='P4104'
    combined=PdfReader(BytesIO(handoffs_pdf([s,other],NOW)))
    assert len(combined.pages)==2
    assert all('Mode: PRVC-IMV' in p.extract_text() for p in combined.pages)


@pytest.mark.parametrize('with_room',[False,True])
def test_handoff_omits_source_sample_and_publish_stamp_but_keeps_instructions(app,monkeypatch,with_room):
    downloads=equip(app,monkeypatch)
    guide=default_guide()
    guide.update(smartphrase_name='PICUHANDOFFSMARTPHRASE',smartphrase_text='PRIVATE_TEMPLATE_SENTINEL',updated_at='2026-11-09T15:00:00+00:00')
    app.st.session_state['user_guide']=guide
    before=deepcopy(guide)
    if with_room: open_room(app)
    seen=[];captions=[];panels=[]
    app.st.markdown=lambda text,**kwargs:seen.append(text)
    app.st.caption=lambda text,**kwargs:captions.append(text)
    app.st.expander=lambda label,**kwargs:(panels.append(label) or Panel(app.st))
    def no_source(*args,**kwargs): raise AssertionError('Source sample must not render on Handoff')
    monkeypatch.setattr(app,'render_smartphrase',no_source)
    app.handoff_page(None)
    assert any('PICUHANDOFFSMARTPHRASE' in t for t in seen)
    assert not any('SmartPhrase saved in this session only:' in t or 'SmartPhrase published:' in t for t in captions)
    assert 'SmartPhrase source' not in panels
    assert not any('SmartPhrase source' in label for label,_ in downloads)
    assert all('PRIVATE_TEMPLATE_SENTINEL' not in t for t in seen)
    assert app.st.session_state['user_guide']==before


def test_source_definition_remains_editable_in_admin(app,monkeypatch):
    equip(app,monkeypatch)
    guide=default_guide();guide['smartphrase_text']='KEEP_IN_ADMIN'
    app.st.session_state['user_guide']=guide
    app.prepare_guide_editor(guide,reset=True)
    assert app.st.session_state['guide_edit_smartphrase_text']=='KEEP_IN_ADMIN'
    assert 'Reusable Epic SmartPhrase source text' in Path(app.__file__).read_text()


@pytest.mark.parametrize('header',['Back Up Feed Intake:', 'Back Up Feed Rate:', 'Back Up Feed Rate (mL/hr):'])
def test_empty_backup_feed_placeholder_is_empty_not_failed_import(header):
    r=parse_feeds('  \n'+header+' \t\n')
    assert not r.error and r.data is None


def test_blank_backup_line_does_not_hide_an_unknown_nonempty_line():
    r=parse_feeds('Back Up Feed Intake:\nUnrecognized feed entry')
    assert r.error and r.data is None


def test_blank_backup_feed_reimport_clears_old_feeds_and_warning():
    settings=new_vault()['settings']
    old=import_sections(new_sheet('P4102'),block('t','Feeding Method: NG\nFormula: Synthetic formula\nRate: 12 mL/hr'),settings).sheet
    assert old['feeds'] is not None
    r=import_sections(old,block('t','Back Up Feed Intake:'),settings)
    assert not r.errors and r.sheet['feeds'] is None
    assert 't' not in r.sheet['import_warnings']


def test_blank_backup_feed_does_not_remove_valid_formula_or_rate():
    r=parse_feeds('Feeding Method: NG\nFormula: Synthetic formula\nRate: 12 mL/hr\nBack Up Feed Intake:')
    assert not r.error and r.data['rows'][0]['rate']=='12 mL/hr'


@pytest.mark.parametrize('mode',['SIMV','PRVC/PS','PCV','VCV','A/C'])
def test_generic_supported_mode_drops_only_display_annotation(mode):
    r=parse_ventilation('Vent Mode: (S) '+mode+'\nResp Rate (Set): 14')
    assert not r.error and r.data is not None
    assert '(S)' not in format_ventilation(r.data)
    assert r.data['mode']=='(S) '+mode
