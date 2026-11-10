"""Synthetic sodium review tests. No patient data is used."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from exports import handoff_html, handoff_text
from import_review import diagnostic
from labs import parse_labs
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from problem_review import review_text, set_decision, suggestions
from security import generate_key, open_vault, seal_vault


NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def sodium_sheet(rows):
    sheet = new_sheet('P4102')
    parsed = parse_labs(rows)
    assert not parsed.error, parsed.error
    sheet['labs'] = parsed.data
    sheet['admission_date'] = '11/01/2026'
    return sheet


def high_sodium(sheet):
    return [row for row in suggestions(sheet, NOW) if row['key'] == 'NA_HIGH']


@pytest.mark.parametrize('value,expected', [
    ('145', False), ('145.0 (H)', False), ('145.1', True),
    ('146', True), ('146 (H)', True), ('146*', True),
    ('146 mmol/L (H)', True), ('146 mEq/L', True),
    ('146 mg/dL', False), ('146 (L)', False),
    ('>145', True), ('>144', False), ('≥145', False), ('≥146', True),
    ('<150', False), ('≤150', False), ('146 | 150', False),
    ('Pending', False), ('146 hemolyzed', False), ('146 invalid', False),
])
def test_high_sodium_boundary_flags_comparators_and_units(value, expected):
    sheet = sodium_sheet(f'NA\t{value}\t11/10/2026 14:00')
    assert bool(high_sodium(sheet)) is expected


@pytest.mark.parametrize('component,expected', [
    ('NA', True), ('Na', True), ('Sodium', True),
    ('Urine Sodium', False), ('SODIUM, URINE', False), ('NAUR', False),
    ('Sodium chloride', False), ('Sodium bicarbonate', False),
])
def test_only_standard_blood_sodium_component_triggers(component, expected):
    sheet = sodium_sheet(f'{component}\t150\t11/10/2026')
    assert bool(high_sodium(sheet)) is expected


@pytest.mark.parametrize('rows,expected', [
    ('NA\t151 (H)\t11/09/2026\nSodium\t140\t11/10/2026', False),
    ('NA\t140\t11/09/2026\nSodium\t151 (H)\t11/10/2026', True),
    ('NA\t151\t11/10/2026 08:00\nNA\t140\t11/10/2026 14:00', False),
    ('NA\t140\t11/10/2026 08:00\nNA\t151\t11/10/2026 14:00', True),
    ('NA\t140\t11/10/2026\nNA\t151\t11/10/2026', False),
    ('NA\tPending\t11/10/2026\nNA\t151\t11/09/2026', False),
    ('NA\tHemolyzed\t11/10/2026\nNA\t151\t11/09/2026', False),
])
def test_latest_result_by_date_and_time_not_historical_maximum(rows, expected):
    assert bool(high_sodium(sodium_sheet(rows))) is expected


def test_future_preadmission_excluded_and_failed_import_do_not_trigger():
    sheet = sodium_sheet('NA\t150\t10/31/2026\nNA\t150\t11/11/2026\n'
                         'NA\t150\t11/10/2026 14:00')
    sheet['labs']['rows'][-1]['include'] = False
    assert not high_sodium(sheet)
    sheet['labs']['rows'][-1]['include'] = True
    assert high_sodium(sheet)
    sheet['import_warnings']['g'] = [diagnostic('g', 'section_parse_failed')]
    assert not high_sodium(sheet)


def test_hypernatremia_preserves_source_diagnoses_and_roundtrips_decisions():
    sheet = sodium_sheet('NA\t150 (H)\t11/10/2026 14:00')
    sheet['fields']['Diagnoses'] = 'Clinician-entered problem text'
    original = deepcopy(sheet)
    row, = high_sodium(sheet)
    assert row['label'] == 'Hypernatremia' and row['status'] == 'review'
    assert '150 (H)' in row['evidence'] and '11/10/2026 14:00' in row['evidence']
    assert review_text(sheet, NOW) == 'Hypernatremia'
    assert sheet == original
    for exporter in (handoff_text, handoff_html):
        output = exporter(sheet, printed_at=NOW)
        assert 'Hypernatremia' in output and 'Clinician-entered problem text' in output
    sheet = set_decision(sheet, row['key'], row['fingerprint'], 'dismissed', row['label'])
    validate_sheet(sheet)
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault
    assert not review_text(sheet, NOW)
    assert sheet['fields']['Diagnoses'] == original['fields']['Diagnoses']
    sheet['labs']['rows'][0]['value'] = '152 (H)'
    assert high_sodium(sheet)[0]['status'] == 'review'
    sheet['labs']['rows'][0]['value'] = '140'
    assert not high_sodium(sheet)
    assert sheet['fields']['Diagnoses'] == original['fields']['Diagnoses']
