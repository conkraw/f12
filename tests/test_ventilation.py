from migration_helpers import strip_v6_fields
from copy import deepcopy
from pathlib import Path
import pytest
from ventilation import LABELS, parse_ventilation, format_ventilation, mode_rule, validate_ventilation
from parser import parse_smartphrase
from importing import import_sections
from medications import parse_medications, remap, upsert_rule, rule_for_inline_mapping, suggested_key
from models import new_sheet, new_vault, fields_with_medications, apply_ventilation, apply_medications, upgrade_vault, save_sheet_in
from security import generate_key, seal_vault, open_vault

SAMPLE=(Path(__file__).parents[1]/'examples'/'synthetic_smartphrase.txt').read_text()
BLOCK=parse_smartphrase(SAMPLE).blocks['c']
EXPECTED='''Mode: PRVC-PS
Set RR: 16
Set TV: 160 mL
Observed PIP: 24 cm H2O
Set PEEP: 5 cm H2O
Inspiratory Time: 1 sec
Pressure Support: 10 cm H2O
FiO2: 35 %'''


def test_exact_requested_fields_and_order():
    result=parse_ventilation(BLOCK)
    assert result.status=='included' and not result.error
    assert format_ventilation(result.data)==EXPECTED
    assert len(format_ventilation(result.data).splitlines())==8


def test_noise_and_unrequested_values_excluded():
    text=format_ventilation(parse_ventilation(BLOCK).data)
    for omitted in ['Vent ID','Machine','Ventilator On','Verified','resuscitator','Charge','Vt Set/Target','Resp Rate Observed','Rise Time','Humidification','Heater','Minute Ventilation','999','99']:
        assert omitted not in text


@pytest.mark.parametrize('mode',['BiLevel','Bilevel Non Invasive Ventilation','BiPAP','CPAP','CPAP/PS','CPAP + PS','NIV','Non-invasive pressure control','High flow nasal cannula','HFNC'])
def test_noninvasive_labels_do_not_create_vent_block(mode):
    result=parse_ventilation(BLOCK.replace('Volume Targeted Pressure Control - PS',mode))
    assert not result.error and result.status=='excluded' and result.data is None


@pytest.mark.parametrize('mode',['Volume Targeted Pressure Control - PS','Volume Targeted Pressure Control - Intermittent Mandatory Ventilation','Pressure Control','Volume Control','PRVC','SIMV','SIMV/PRVC + PS'])
def test_supported_label_families(mode):
    assert mode_rule(mode)=='included'


def test_unknown_mode_not_guessed():
    result=parse_ventilation(BLOCK.replace('Volume Targeted Pressure Control - PS','Unfamiliar mode'))
    assert result.status=='unknown' and result.data is None and result.issues


def test_missing_set_volume_does_not_use_target_volume():
    result=parse_ventilation(BLOCK.replace('Vt (Set, mL): 160 mL\n',''))
    assert not result.error
    assert 'Vt (Set, mL)' not in result.data['values']
    assert '999' not in format_ventilation(result.data)


def test_missing_set_rate_does_not_use_observed_rate():
    result=parse_ventilation(BLOCK.replace('Resp Rate (Set): 16\n',''))
    assert 'Resp Rate (Set)' not in result.data['values']
    assert '99' not in format_ventilation(result.data)


def test_values_not_recalculated_or_units_invented():
    block=BLOCK.replace('FiO2 (%): 35 %','FiO2 (%): 0.35').replace('Insp Time (sec): 1 sec','Insp Time (sec): (S) 1 sec')
    text=format_ventilation(parse_ventilation(block).data)
    assert 'FiO2: 0.35 %' in text and 'Inspiratory Time: 1 sec' in text
    assert 'Mean Airway Pressure' not in text
    assert parse_ventilation(block).data['values']['Insp Time (sec)'] == '(S) 1 sec'


def test_duplicate_identical_fields_not_repeated():
    result=parse_ventilation(BLOCK+'\nFiO2 (%): 35 %')
    assert not result.error and format_ventilation(result.data).count('FiO2')==1


def test_duplicate_conflicting_field_blocks_import():
    result=parse_ventilation(BLOCK+'\nFiO2 (%): 80 %')
    assert result.error and result.data is None


def test_blank_mode_with_values_is_error():
    assert parse_ventilation('Invasive Ventilation:\nFiO2 (%): 35 %').error


def test_empty_section_clears_vent_without_claiming_normal():
    result=parse_ventilation('Invasive Ventilation:\n')
    assert result.status=='empty' and result.data is None and not result.error


def test_c_only_import_and_resp_separator_before_meds():
    s=new_sheet('P4102')
    s['fields']['Respiratory']='Manual respiratory note'
    meds=parse_medications('Medications:\n• albuterol\t5 mg/hr\tNebulization\tContinuous').rows
    s=apply_medications(s,remap(meds,upsert_rule([],'albuterol','Respiratory')))
    result=import_sections(s,'cccccccc\n'+BLOCK+'\ncccccccc',new_vault()['settings'])
    assert not result.errors
    resp=fields_with_medications(result.sheet)['Respiratory']
    assert resp.startswith('Vent Settings\n'+EXPECTED+'\n-----\nBeta-Agonist\nalbuterol')
    assert resp.endswith('-----\nManual respiratory note')
    assert 'Vent Mode' not in result.sheet['fields']['Respiratory']


def test_valid_noninvasive_import_clears_previous_auto_block_keeps_meds_notes():
    s=apply_ventilation(new_sheet('P4102'),parse_ventilation(BLOCK).data)
    s['fields']['Respiratory']='Keep manual note'
    result=import_sections(s,'cccccccc\nInvasive Ventilation:\nVent Mode: CPAP\ncccccccc',new_vault()['settings'])
    assert result.sheet['ventilation'] is None
    assert result.sheet['fields']['Respiratory']=='Keep manual note'
    assert '-----' not in fields_with_medications(result.sheet)['Respiratory']


def test_paste_without_c_preserves_previous_vent_block():
    s=apply_ventilation(new_sheet('P4102'),parse_ventilation(BLOCK).data)
    result=import_sections(s,'aaaaaaaa\nDiagnoses:\n1. Practice\naaaaaaaa',new_vault()['settings'])
    assert result.sheet['ventilation']==s['ventilation']


def test_d_and_e_values_never_mix_into_c():
    text='cccccccc\n'+BLOCK.replace('FiO2 (%): 35 %\n','')+'\ncccccccc\ndddddddd\nNon-invasive Ventilation:\nFiO2 (%): 90 %\ndddddddd\neeeeeeee\nVITALS:\nFiO2 (%): 100 %\neeeeeeee'
    result=import_sections(new_sheet('P4102'),text,new_vault()['settings'])
    assert 'FiO2 (%)' not in result.sheet['ventilation']['values']


def test_existing_schema_two_preserved_with_new_field():
    old=new_vault()
    old=save_sheet_in(old,new_sheet('P4102'))
    old['schema']=2;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old["settings"].pop("medication_gi_groups", None);old['settings'].pop('medication_infusions', None)
    strip_v6_fields(old)
    old['rooms']['P4102'].pop('ventilation')
    old['rooms']['P4102'].pop('noninvasive')
    old['rooms']['P4102']['fields']['Respiratory']='Old manual note'
    old['settings']['medication_mappings']=upsert_rule([],'acetaminophen','Neurologic')
    migrated=upgrade_vault(old)
    assert migrated['schema']==32 and old['schema']==2
    assert migrated['rooms']['P4102']['fields']['Respiratory']=='Old manual note'
    assert migrated['settings']['medication_mappings']==old['settings']['medication_mappings']
    assert migrated['rooms']['P4102']['ventilation'] is None


def test_ventilation_encrypted_roundtrip():
    s=apply_ventilation(new_sheet('P4102'),parse_ventilation(BLOCK).data)
    v=save_sheet_in(new_vault(),s)
    key=generate_key()
    data=seal_vault(v,key)
    assert b'Vent Mode' not in data
    assert open_vault(data,key)==v


def test_unknown_extra_vent_field_rejected():
    data=parse_ventilation(BLOCK).data
    data['values']['Machine']='Injected extra'
    with pytest.raises(ValueError): validate_ventilation(data)


def test_continuous_albuterol_maps_to_same_drug_prefix():
    assert suggested_key('albuterol continuous nebulizer solution')=='albuterol'


def test_inline_specific_formulation_does_not_overwrite_broad_rule():
    rules=upsert_rule([],'heparin','Hematology')
    assert rule_for_inline_mapping('heparin flush 10 units/mL',rules)==('heparin flush','prefix')


def test_inline_existing_exact_rule_updated_not_shadowed():
    name='albuterol nebulizer 2.5 mg'
    rules=upsert_rule([],'albuterol','Respiratory')
    rules=upsert_rule(rules,name,'Other Medications','exact')
    assert rule_for_inline_mapping(name,rules)==(name,'exact')
