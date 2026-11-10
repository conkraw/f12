from recovery_helpers import assert_retained
"""Synthetic regression tests for I/K/L/M, migration and observed tidal volume."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from observations import (empty_neuro, neuro_rows, parse_neuro, validate_neuro,
                          parse_nutrition, validate_nutrition, format_nutrition)
from models import (new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault,
                    fields_with_medications, save_sheet_in, automatic_vitals, ValidationError)
from importing import import_sections
from ventilation import parse_ventilation, format_ventilation, LABELS
from noninvasive import parse_respiratory
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf, handoffs_html
from batching import available_handoffs
from medications import upsert_rule
from security import open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]


def block(key, content):
    from parser import SECTION_NAMES
    return key * 12 + '\n' + SECTION_NAMES[key] + ':\n' + content + '\n' + key * 12


def imp(text, sheet=None):
    result = import_sections(sheet or new_sheet('P4102'), text, new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet is not None
    return result.sheet


def populated():
    return imp(block('i','10/31/26\t15.3 kg (66%, Z= 0.41)*') + '\n' +
               block('k','Target Arousal Level (SBS): SBS -1') + '\n' +
               block('l','WAT-1 Total Score\nWAT-1 total score (0-12): 0') + '\n' +
               block('m','ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg'))


@pytest.mark.parametrize('source,content,expected', [
    ('k','Target Arousal Level (SBS): SBS -1','SBS -1'),
    ('k','Target Arousal Level (SBS): SBS 0','SBS 0'),
    ('k','Target Arousal Level (SBS): SBS +1','SBS +1'),
    ('k','Target Arousal Level (RASS): RASS -2','RASS -2'),
    ('k','SBS -1','SBS -1'),
    ('k','Target Arousal Level: Awake and calm','Awake and calm'),
    ('l','WAT-1 Total Score\nWAT-1 total score (0-12): 0','0'),
    ('l','WAT-1 total score (0-12): [0-3] 1','[0-3] 1'),
    ('l','0','0'),
    ('l','WAT-1\t3','3'),
    ('m','ICP Mean (mmHg): 5 mmHg','5 mmHg'),
    ('m','ICP Mean (mmHg): 0 mmHg','0 mmHg'),
    ('m','CPP: 72 mmHg','72 mmHg'),
    ('m','ICP Mean (mmHg): [2-8] 5 mmHg','[2-8] 5 mmHg'),
])
def test_neuro_values_are_preserved(source,content,expected):
    result = parse_neuro(content,source)
    assert not result.error
    assert result.rows[0]['value'] == expected
    assert result.rows[0]['section'] == 'Neurologic'
    assert result.rows[0]['include'] is True


@pytest.mark.parametrize('key,body', [
    ('k','Target Arousal Level:'), ('l','WAT Score:\nWAT-1 Total Score'), ('m','ICP Trends:'),
    ('k','Target Arousal Level (SBS):'), ('l','WAT-1 total score (0-12): --'),
    ('m','ICP Mean (mmHg): N/A\nCPP: not documented'),
    ('k','None'), ('l','Not documented.'), ('m','\n \t\n'),
])
def test_empty_headings_and_placeholders_add_no_values(key,body):
    result = parse_neuro(body,key)
    assert not result.error and result.rows == []


def test_no_score_is_inferred_from_scale_range_in_heading():
    assert not parse_neuro('WAT-1 total score (0-12):', 'l').rows


def test_icp_and_cpp_stay_separate_and_in_order():
    rows = parse_neuro('ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg','m').rows
    assert [r['label'] for r in rows] == ['ICP Mean (mmHg)', 'CPP']


def test_neuro_duplicate_conflict_is_atomic():
    sheet = populated(); before = deepcopy(sheet)
    result = import_sections(sheet,block('a','1. Changed')+'\n'+block('m','CPP: 50 mmHg\nCPP: 60 mmHg'),new_vault()['settings'])
    assert_retained(result, before, "m")
    assert sheet == before


def test_identical_neuro_line_is_not_doubled():
    result = parse_neuro('CPP: 72 mmHg\nCPP: 72 mmHg','m')
    assert not result.error and len(result.rows) == 1


@pytest.mark.parametrize('key,body', [('k','Different field: 8'),('l','An unreadable fragment'),('m','An unreadable fragment')])
def test_unreadable_neuro_data_is_not_silently_dropped(key,body):
    assert parse_neuro(body,key).error


@pytest.mark.parametrize('weight,z', [('15.3','0.41'),('11.6','-0.15'),('6.1','-3.54'),('12','0'),('10.00','+0.25')])
def test_weight_and_z_only(weight,z):
    source='NUTRITION:\nWt Readings from Last 1 Encounters:\n10/31/26\t'+weight+' kg (66%, Z= '+z+')*\n* Growth percentiles are based on a chart.'
    result=parse_nutrition(source)
    assert not result.error
    assert result.data == {'weight':weight+' kg','z_score':z,'include':True}
    text=format_nutrition(result.data)
    assert '%' not in text and '10/31' not in text and '*' not in text and 'chart' not in text


def test_missing_z_not_invented_from_percentile():
    result=parse_nutrition('10/31/26 15.3 kg (66%)*')
    assert not result.error and result.data['z_score']=='' and result.issues
    assert format_nutrition(result.data)=='Weight: 15.3 kg'


def test_explicit_weight_label():
    result=parse_nutrition('Weight: 15.3 kg (Z-score= 0.41)')
    assert result.data['weight']=='15.3 kg' and result.data['z_score']=='0.41'


def test_no_nutrient_or_dose_quantity_used_as_weight():
    result=parse_nutrition('NUTRITION:\nProtein: 10 g\nFeeding: 2 g/kg/day\nWeight: --')
    assert not result.error and result.data is None


def test_latest_weight_by_date_not_numerical_magnitude():
    result=parse_nutrition('10/31/26 15.3 kg (66%, Z= 0.41)*\n11/02/26 15.2 kg (Z= 0.40)*')
    assert result.data['weight']=='15.2 kg'


def test_same_date_weights_keep_source_order_with_notice():
    result=parse_nutrition('11/2/26 15.2 kg (Z= 0.40)\n11/2/26 15.3 kg (Z= 0.41)')
    assert result.data['weight']=='15.2 kg' and result.issues


@pytest.mark.parametrize('body',['Weight: -1 kg','Weight: 0 kg','10/31/26 15.3 kg (Z= invalid)','2/31/26 15.3 kg (Z= 0.1)'])
def test_invalid_weight_source_is_rejected(body):
    assert parse_nutrition(body).error


@pytest.mark.parametrize('key',['weight','z_score','include'])
def test_invalid_saved_nutrition_is_rejected(key):
    data={'weight':'15.3 kg','z_score':'0.41','include':True};data[key]=[]
    with pytest.raises(ValueError):validate_nutrition(data)


def test_included_empty_neuro_clears_only_its_own_source():
    sheet=populated()
    revised=imp(block('l',''),sheet)
    assert revised['neuro_vitals']['l']==[]
    assert revised['neuro_vitals']['k']==sheet['neuro_vitals']['k']
    assert revised['neuro_vitals']['m']==sheet['neuro_vitals']['m']
    assert revised['nutrition']==sheet['nutrition']


def test_e_only_paste_does_not_erase_neuro_observations():
    sheet=populated()
    revised=imp(block('e','Heart Rate: [90-120] 100'),sheet)
    assert revised['neuro_vitals']==sheet['neuro_vitals']
    assert 'WAT-1' in automatic_vitals(revised)['Neurologic']


def test_missing_i_and_klm_leave_data_unchanged():
    sheet=populated();revised=imp(block('a','1. New synthetic diagnosis'),sheet)
    assert revised['nutrition']==sheet['nutrition'] and revised['neuro_vitals']==sheet['neuro_vitals']


def test_empty_i_clears_weight_not_manual_demographics_or_neuro():
    sheet=populated(); sheet['fields']['Demographics / Weight']='Manual demographic note'
    revised=imp(block('i',''),sheet)
    assert revised['nutrition'] is None and revised['fields']['Demographics / Weight']=='Manual demographic note'
    assert revised['neuro_vitals']==sheet['neuro_vitals']


def test_repeated_import_does_not_duplicate_automatic_data():
    sheet=populated()
    for _ in range(3):
        sheet=imp(block('l','WAT-1 total score (0-12): 0'),sheet)
    assert len(sheet['neuro_vitals']['l'])==1
    assert fields_with_medications(sheet)['Neurologic'].count('WAT-1')==1


def test_neuro_above_manual_notes_medications_weight_below_diagnoses():
    settings=new_vault()['settings']
    settings['medication_mappings']=upsert_rule([], 'acetaminophen','Neurologic')
    source=(ROOT/'examples/synthetic_neuro_weight.txt').read_text()
    sheet=import_sections(new_sheet('P4102'),source,settings).sheet
    sheet['fields']['Neurologic']='Manual neuro note'
    fields=fields_with_medications(sheet)
    text=fields['Neurologic']
    assert text.index('WAT-1') < text.index('ICP Mean') < text.index('CPP:') < text.index('Fever Control') < text.index('acetaminophen') < text.index('Manual neuro note')
    assert fields['Diagnoses'].endswith('----\nWeight: 15.3 kg\nZ-score: 0.41\nDosing weight: none')
    assert 'Weight:' not in sheet['fields']['Diagnoses']
    assert fields_with_medications(sheet)==fields


def test_target_arousal_order_first():
    text=fields_with_medications(populated())['Neurologic']
    assert 'Target Arousal' not in text
    assert text.index('WAT-1')<text.index('ICP Mean')<text.index('CPP:')


def test_neuro_e_vitals_route_to_neuro():
    from vitals import parse_vitals
    result=parse_vitals('ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg\nWAT-1: 0\nTarget Arousal Level (SBS): SBS -1')
    assert not result.error and all(r['section']=='Neurologic' for r in result.rows)


@pytest.mark.parametrize('field,body', [('neuro',block('m','ICP Mean (mmHg): 5 mmHg')),('weight',block('i','10/31/26 15.3 kg (Z= 0.41)'))])
def test_new_content_alone_is_not_omitted_from_print_all(field,body):
    sheet=imp(body)
    assert list(available_handoffs(new_vault(),{'P4102':sheet}))==['P4102']
    if field=='neuro':sheet['neuro_vitals']['m'][0]['include']=False
    else:sheet['nutrition']['include']=False
    assert not available_handoffs(new_vault(),{'P4102':sheet})


def test_all_exports_preserve_values_and_omit_growth_metadata():
    sheet=populated();sheet['fields']['Diagnoses']='Synthetic diagnosis'
    text=handoff_text(sheet)
    html=handoff_html(sheet)
    pdftext='\n'.join(p.extract_text() for p in PdfReader(BytesIO(handoff_pdf(sheet))).pages)
    for output in [text,html,pdftext]:
        for value in ['15.3 kg','0.41','72 mmHg','5 mmHg']:
            assert value in output
        assert '66%' not in output and '10/31/26' not in output and 'Growth percentiles' not in output
        assert output.index('Synthetic diagnosis')<output.index('Weight:')<output.index('Z-score:')


def test_two_room_print_keeps_observed_vt_and_neuro_values_separate():
    first=imp((ROOT/'examples/synthetic_neuro_weight.txt').read_text())
    second=imp((ROOT/'examples/synthetic_observed_vt.txt').read_text(),new_sheet('P4104'))
    reader=PdfReader(BytesIO(handoffs_pdf([first,second])))
    assert len(reader.pages)==2
    assert '72 mmHg' in reader.pages[0].extract_text() and '162 mL' not in reader.pages[0].extract_text()
    assert '160 mL' in reader.pages[1].extract_text() and '72 mmHg' not in reader.pages[1].extract_text()
    assert second['ventilation']['values']['Vt (observed, mL)'] == '162 mL'
    assert '162 mL' not in reader.pages[1].extract_text()  # Volume-targeted print profile uses set TV.
    assert all(float(p.mediabox.width)>float(p.mediabox.height) for p in reader.pages)
    assert handoffs_html([first,second]).count('Weight:')==2


def test_hidden_new_observations_and_weight_not_printed():
    sheet=populated();sheet['nutrition']['include']=False
    for rows in sheet['neuro_vitals'].values():
        for row in rows:row['include']=False
    fields=fields_with_medications(sheet)
    assert fields['Neurologic']=='CAPD: None\n-----\nFever Control: None' and fields['Diagnoses']=='Dosing weight: none'
    assert sheet['nutrition']['weight']=='15.3 kg'


def test_text_in_neuro_value_is_html_escaped():
    sheet=populated();sheet['neuro_vitals']['l'][0]['value']='<script>example</script>'
    html=handoff_html(sheet)
    assert '<script>example</script>' not in html and '&lt;script&gt;' in html


def test_observed_tidal_volume_separate_from_set_and_target():
    source='Vent Mode: Pressure Control - Intermittent Mandatory Ventilation\nVt Set/Target ml: 170\nVt (Set, mL): 160 mL\nVt (observed, mL): 162 mL\nPEEP (cm H2O): 5 cm H2O'
    result=parse_ventilation(source)
    assert not result.error
    text=format_ventilation(result.data)
    assert 'Set TV: 160 mL' not in text  # PC print profile uses set pressure instead.
    assert result.data['values']['Vt (Set, mL)'] == '160 mL'
    assert text.index('Observed TV: 162 mL') < text.index('Set PEEP')
    assert '170' not in text


@pytest.mark.parametrize('label',['Vt (observed, mL)','VT (OBSERVED, ML)','vt (observed, ml)'])
def test_observed_label_is_case_insensitive(label):
    result=parse_respiratory('Vent Mode: Volume Targeted Pressure Control - PS\n'+label+': 162 mL',None)
    assert not result.error and result.invasive['values']['Vt (observed, mL)']=='162 mL'


def test_missing_observed_is_not_copied_from_set():
    result=parse_ventilation('Vent Mode: Volume Control\nVt (Set, mL): 160 mL')
    assert 'Vt (observed, mL)' not in result.data['values']


def test_observed_duplicate_conflict_is_rejected():
    result=parse_ventilation('Vent Mode: Volume Control\nVt (observed, mL): 162 mL\nVt (observed, mL): 163 mL')
    assert result.error


def test_new_c_snapshot_without_observed_clears_previous_value():
    sheet=imp(block('c','Vent Mode: Volume Control\nVt (observed, mL): 162 mL'))
    sheet=imp(block('c','Vent Mode: Volume Control\nVt (Set, mL): 160 mL'),sheet)
    assert 'Vt (observed, mL)' not in sheet['ventilation']['values']


def legacy_v6():
    vault=save_sheet_in(new_vault(),populated())
    vault['schema']=6;vault.pop("reset_generation", None);vault["settings"].pop("medication_groups", None);vault["settings"].pop("medication_gi_groups", None);vault['settings'].pop('medication_infusions', None)
    for sheet in vault['rooms'].values():
        sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas', None);sheet.pop('neuro_vitals');sheet.pop('nutrition');sheet.pop('cultures');sheet.pop('dosing_weight');sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas', None);sheet.pop('viral_panel', None);sheet.pop('admission_date')
    vault['rooms']['P4102']['fields']['Other']='Do not lose this existing note'
    return vault


def test_schema6_migration_preserves_every_old_field_and_does_not_mutate():
    old=legacy_v6();before=deepcopy(old)
    new=upgrade_vault(old)
    assert old==before and new['schema']==33
    for key,value in old['rooms']['P4102'].items():assert new['rooms']['P4102'][key]==value
    assert new['settings']==dict(old['settings'], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    assert new['rooms']['P4102']['neuro_vitals']==empty_neuro() and new['rooms']['P4102']['nutrition'] is None


def test_schema6_encrypted_archive_opens_with_same_key_and_preserves_notes():
    old=legacy_v6();key=Fernet.generate_key().decode()
    ciphertext=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    new=open_vault(ciphertext,key)
    assert new['schema']==33 and new['rooms']['P4102']['fields']['Other']==old['rooms']['P4102']['fields']['Other']


def test_new_observations_encrypt_roundtrip():
    vault=save_sheet_in(new_vault(),populated());key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(vault,key),key)==vault


def test_malformed_old_schema_not_silently_overwritten():
    old=legacy_v6();old['rooms']['P4102']['unexpected']='Do not drop this'
    with pytest.raises(ValidationError):upgrade_vault(old)


def test_callback_edits_zero_and_negative_values(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=populated()
    ss['test_neuro']='0'
    app.neuro_row_change('P4102','l',0,'value','test_neuro')
    assert ss['drafts']['P4102']['neuro_vitals']['l'][0]['value']=='0'
    ss['test_weight']='-0.25';app.nutrition_change('P4102','z_score','test_weight')
    assert ss['drafts']['P4102']['nutrition']['z_score']=='-0.25'


def test_callback_rejects_invalid_weight_without_loss(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=populated()
    ss['test_weight']='not a weight';app.nutrition_change('P4102','weight','test_weight')
    assert ss['drafts']['P4102']['nutrition']['weight']=='15.3 kg' and ss['test_weight']=='15.3 kg'


def test_cross_room_callback_does_not_edit(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=populated()
    open_room(app,'P4104')
    ss['test_weight']='25 kg';app.nutrition_change('P4102','weight','test_weight')
    assert ss['drafts']['P4102']['nutrition']['weight']=='15.3 kg'


def test_new_patient_clears_all_new_fields(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=populated()
    app.start_new_patient()
    assert ss['drafts']['P4102']['nutrition'] is None and ss['drafts']['P4102']['neuro_vitals']==empty_neuro()


def test_session_v6_migration_preserves_unsaved_drafts(app):
    ss=app.st.session_state;old=legacy_v6();ss.update(vault=old,drafts={'P4102':deepcopy(old['rooms']['P4102'])},base_sheets=deepcopy(old['rooms']))
    ss['drafts']['P4102']['fields']['Neurologic']='Unsaved edit'
    ss['vent_old']='old index'
    app.upgrade_existing_session()
    assert ss['vault']['schema']==33 and ss['drafts']['P4102']['fields']['Neurologic']=='Unsaved edit'
    assert 'vent_old' not in ss


def test_one_click_example_with_ui_stub_and_batch_downloads(app,monkeypatch):
    open_room(app);ss=app.st.session_state
    app.load_neuro_sample();app.create_handoff()
    assert not ss['import_result']['errors'] and ss['paste']==''
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['nutrition']['weight']=='15.3 kg'


def test_neuro_hide_restore_callbacks_keep_records(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=populated()
    ss['hide']=False;app.neuro_row_change('P4102','m',0,'include','hide')
    assert 'ICP Mean' not in fields_with_medications(ss['drafts']['P4102'])['Neurologic']
    ss['hide']=True;app.neuro_row_change('P4102','m',0,'include','hide')
    assert 'ICP Mean' in fields_with_medications(ss['drafts']['P4102'])['Neurologic']


def test_long_handoff_continuation_keeps_weight_and_observations_once():
    sheet=populated()
    sheet['fields']['Diagnoses']='\n'.join('Synthetic diagnosis line '+str(n) for n in range(85))
    reader=PdfReader(BytesIO(handoff_pdf(sheet)))
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>1
    for value in ['Weight: 15.3 kg','Z-score: 0.41','CPP: 72 mmHg']:
        assert text.count(value)==1
    assert 'Synthetic diagnosis line 84' in ' '.join(text.split())


def test_zero_observed_volume_is_retained_not_treated_as_missing():
    result=parse_ventilation('Vent Mode: Volume Control\nVt (observed, mL): 0 mL')
    assert result.data['values']['Vt (observed, mL)']=='0 mL'


def test_nutrition_without_diagnosis_does_not_fabricate_diagnosis_heading():
    sheet=imp(block('i','10/31/26 15.3 kg (Z= 0.41)'))
    from exports import patient_column
    column=patient_column(sheet,fields_with_medications(sheet))
    assert 'Weight: 15.3 kg' in column and 'Diagnoses:' not in column


def test_loader_for_observed_example_sets_current_paste_without_saving(app):
    open_room(app)
    app.load_observed_sample();app.create_handoff()
    ss=app.st.session_state
    assert not ss['import_result']['errors']
    assert ss['drafts']['P4102']['ventilation']['values']['Vt (observed, mL)']=='162 mL'
    assert ss['vault']['rooms']=={}
