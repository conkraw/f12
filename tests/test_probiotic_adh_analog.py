"""User-requested display mappings. Synthetic orders only, no dose inference."""
from copy import deepcopy

import pytest

from categories import apply_category_rules, catalog, default_categories, medication_blocks, placement, set_category_rule
from exports import handoff_html, handoff_text
from fen_gi import effective_section, set_gi_rule, apply_gi_rules
from medication_groups import set_group_rule, apply_group_rules
from medications import DESTINATIONS, parse_medications
from models import new_vault, new_sheet, validate_vault
from security import generate_key, open_vault, seal_vault


def order(name, route='Oral'):
    parsed = parse_medications(name + '\tSYNTHETIC_DOSE\t' + route + '\tDaily\t\t\t')
    assert not parsed.error and len(parsed.rows) == 1
    return parsed.rows[0]


@pytest.mark.parametrize('name', ['lactobacillus', 'Lactobacillus rhamnosus (GG)',
    'lactobacillus acidophilus capsule', 'lactobacillus (CULTURELLE)',
    'Or: [START ON 11/14/2026] lactobacillus rhamnosus', 'lactobacillus/bifidobacterium'])
def test_lactobacillus_default(name):
    row = order(name)
    before = deepcopy(row)
    assert placement(row)['id'] == 'gi:probiotic'
    assert placement(row)['name'] == 'Probiotic'
    assert effective_section(row) == 'FEN / GI'
    assert row == before


@pytest.mark.parametrize('name', ['desmopressin', 'desmopressin acetate',
    'desmopressin (DDAVP) tablet', 'DDAVP', 'DESMOpressin nasal spray',
    'And: [START ON 11/14/2026] desmopressin injection'])
@pytest.mark.parametrize('route', ['Oral', 'Intravenous', 'Nasal', 'Subcutaneous'])
def test_desmopressin_default_all_formulations(name, route):
    row = order(name, route)
    before = deepcopy(row)
    assert placement(row)['id'] == 'group:adh_analog'
    assert placement(row)['name'] == 'ADH Analog'
    assert effective_section(row) == 'Neurologic'
    assert row == before


@pytest.mark.parametrize('name', ['vasopressin', 'desmopressinX', 'ddavpX',
    'lactobacillusX', 'lactobacillus-like compound', 'lactulose', 'synthetic with lactobacillus'])
def test_no_unintended_matches(name):
    assert placement(order(name))['id'] not in {'gi:probiotic', 'group:adh_analog'}


@pytest.mark.parametrize('name,target,label', [('lactobacillus', 'gi:probiotic', 'Probiotic'),
    ('desmopressin', 'group:adh_analog', 'ADH Analog')])
def test_render_backfill_roundtrip_no_patient_mutation(name, target, label):
    vault = new_vault()
    new_ids = {'gi:probiotic', 'group:adh_analog'}
    vault['settings']['medication_categories'] = [c for c in default_categories() if c['id'] not in new_ids]
    row = order(name + ' SYNTHETIC_MEDICATION')
    sheet = new_sheet('P4102')
    sheet['medications'] = [row]
    sheet['fields']['Diagnoses'] = 'SYNTHETIC_UNCHANGED_PATIENT'
    vault['rooms']['P4102'] = sheet
    before = deepcopy(vault)
    validate_vault(vault)
    assert target in {c['id'] for c in catalog(vault['settings'])}
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == before
    emitted = [v['id'] for section in DESTINATIONS for _, v in medication_blocks(section, '', [row]) if isinstance(v, dict)]
    assert emitted == [row['id']]
    for text in (handoff_text(sheet), handoff_html(sheet)):
        assert label in text
        assert text.count('SYNTHETIC_MEDICATION') == 1
        assert 'SYNTHETIC_DOSE' in text
    assert vault == before


@pytest.mark.parametrize('name,target', [('lactobacillus', 'gi:probiotic'), ('desmopressin', 'group:adh_analog')])
def test_hidden_and_explicit_category_choices_preserved(name, target):
    row = order(name + ' SYNTHETIC_MEDICATION')
    row['hidden'] = True
    sheet = new_sheet('P4102')
    sheet['medications'] = [row]
    assert 'SYNTHETIC_MEDICATION' not in handoff_text(sheet)
    settings = set_category_rule(new_vault()['settings'], name, 'system:Other Medications')
    mapped = apply_category_rules([row], settings)[0]
    assert placement(mapped)['id'] == 'system:Other Medications'
    settings = set_category_rule(settings, name, target)
    assert placement(apply_category_rules([row], settings)[0])['id'] == target


def test_new_modes_available_for_admin_mapping_rules():
    row = order('synthetic product')
    gi_rules = set_gi_rule([], row, 'probiotic')
    assert placement(apply_gi_rules([row], gi_rules)[0])['id'] == 'gi:probiotic'
    group_rules = set_group_rule([], row, 'adh_analog')
    assert placement(apply_group_rules([row], group_rules)[0])['id'] == 'group:adh_analog'
