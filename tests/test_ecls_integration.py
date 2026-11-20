"""ECLS import boundaries, measurements, room replacement and storage checks.

Every fixture is a synthetic training example with no patient identifiers.
"""
from copy import deepcopy

import pytest

from anthropometrics import empty_anthropometrics
from batching import available_handoffs
from ecls import ecls_text
from importing import import_replacement, import_sections
from import_review import diagnostic_text, review_summary
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from parser import parse_smartphrase
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room


def block(marker, body):
    divider = marker * 10
    return divider + '\n' + body + '\n' + divider


READINGS = '''System Readings
ECMO Mode: Veno-arterial
Day: 8
Oxygenator Day: 0
Pump Flow (L/min): 2.3 LPM
Flow Goal (L/min): 2.25 L/min
Set Speed (rev/min) : 3400 Rev/Min
Blender FiO2 (%): 50 %
Sweep Gas Flow Rate (L/min): 1.2
Sweep speed changed: Yes
New ECMO Sweep speed: 2.5 (L/min)
Witness name: SYNTHETIC_IGNORE_NAME
Heater Temp (Set): 37 C
Cardiac Index (L/min/m2): 9.9'''

MEASUREMENTS = '''NUTRITION:
Weight: 30 kg
Dosing Weight:
Dosing Weight
Dosing
27 kg
8 hours ago
BSA:
Body surface area is 1 meters squared.'''


def source(readings=READINGS, measurements=MEASUREMENTS):
    return '\n'.join((
        block('a', 'Diagnoses:\n1. SYNTHETIC_TRAINING_EXAMPLE'),
        block('i', measurements),
        block('ad', readings),
    ))


def imported(text=None):
    result = import_replacement('P4102', source() if text is None else text, new_vault()['settings'])
    assert result.sheet is not None, result.errors
    return result


def test_source_fields_and_reported_measurements_are_used():
    result = imported()
    assert not result.errors
    sheet = result.sheet
    validate_sheet(sheet)
    assert sheet['dosing_weight'] == '27 kg'
    assert sheet['anthropometrics']['bsa'] == '1 m²'
    text = ecls_text(sheet)
    for value in ('Mode: VA', 'Oxy Day: 0', '2.3 L/min', '85.2 mL/kg/min',
                  'CI: 2.3 L/min/m²', 'RPM: 3400', 'Sweep: 1.2 L/min', 'FiO₂: 50%'):
        assert value in text
    for value in ('2.25', '9.9', '76.7', '2.5 L/min', 'SYNTHETIC_IGNORE_NAME'):
        assert value not in text
    assert 'SYNTHETIC_IGNORE_NAME' not in str(sheet)
    assert 'System Readings' not in str(sheet)


@pytest.mark.parametrize('marker', ['ad' * 4, 'AD' * 8, 'ad' * 9 + 'a'])
def test_ad_dividers_accept_copy_variants(marker):
    text = block('a', 'Diagnoses:\n1. Synthetic') + '\n' + marker + '\n' + READINGS + '\n' + marker
    parsed = parse_smartphrase(text)
    assert parsed.blocks['ad'] == READINGS
    assert 'ad' not in parsed.invalid


@pytest.mark.parametrize('body', ['', 'System Readings', 'System Readings\nNo data recorded'])
def test_explicit_empty_ad_clears_old_snapshot(body):
    sheet = imported().sheet
    result = import_sections(sheet, block('ad', body), new_vault()['settings'])
    assert not result.errors
    assert not result.sheet.get('ecls')
    assert ecls_text(result.sheet) == ''
    assert sheet['ecls'] is not None


def test_new_paste_without_ad_replaces_prior_ecls_and_keeps_other_rooms(app):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = source()
    app.create_handoff(None)
    first_id = ss['drafts']['P4102']['id']
    assert ss['drafts']['P4102']['ecls']
    other = new_sheet('P4104')
    other['fields']['Diagnoses'] = 'OTHER_ROOM_SENTINEL'
    ss['vault'] = save_sheet_in(ss['vault'], other)
    other_before = deepcopy(ss['vault']['rooms']['P4104'])
    ss['paste'] = block('a', 'Diagnoses:\n1. NEW_ROOM_PATIENT')
    app.create_handoff(None)
    current = ss['drafts']['P4102']
    assert current['id'] != first_id
    assert not current.get('ecls')
    assert ecls_text(current) == ''
    assert ss['vault']['rooms']['P4104'] == other_before
    assert ss['paste'] == ''


def test_partial_new_ecls_never_borrows_missing_prior_settings():
    original = imported().sheet
    result = import_sections(original, block('ad', 'System Readings\nECMO Mode: VV\nOxygenator Day: 2'), new_vault()['settings'])
    assert not result.errors
    assert result.sheet['ecls']['mode'] == 'VV'
    assert result.sheet['ecls']['blood_flow_l_min'] == ''
    assert '2.3 L/min' not in ecls_text(result.sheet)
    assert '3400' not in ecls_text(result.sheet)
    assert original['ecls']['blood_flow_l_min'] == '2.3'


@pytest.mark.parametrize('bad', [
    'adadadad\n' + READINGS,
    'adadadad\n' + READINGS + '\nadadadadadbdadad',
    block('ad', 'VITALS:\nFiO2: 99 %'),
])
def test_invalid_ecls_boundary_omits_settings_and_preserves_valid_diagnosis(bad):
    result = imported(block('a', 'Diagnoses:\n1. VALID_NEW_DIAGNOSIS') + '\n' + bad)
    assert result.errors
    assert result.sheet['fields']['Diagnoses'] == 'VALID_NEW_DIAGNOSIS'
    assert ecls_text(result.sheet) == ''
    assert 'ad' in result.skipped
    warning = result.sheet['import_warnings']['ad'][0]
    assert warning['action'] == 'not_imported'
    assert 'No previous patient information was carried over' in diagnostic_text(warning)


def test_failed_low_level_ecls_import_clears_old_snapshot():
    previous = imported().sheet
    result = import_sections(previous, 'adadadad\n' + READINGS, new_vault()['settings'])
    assert result.errors
    assert result.sheet.get('ecls') is None
    assert 'cleared' in review_summary(result.sheet)
    assert 'cleared' in diagnostic_text(result.sheet['import_warnings']['ad'][0])


def test_multiple_paired_ad_sections_reject_document():
    result = import_replacement('P4102', source() + '\n' + block('ad', READINGS), new_vault()['settings'])
    assert result.sheet is None
    assert result.errors


def test_unrelated_ventilator_fields_do_not_create_ecls():
    result = imported(block('a', 'Diagnoses:\n1. Synthetic') + '\n' + block('c', 'Invasive Ventilation:\nVent Mode: SIMV/PRVC\nFiO2: 90 %'))
    assert not result.sheet.get('ecls')
    assert ecls_text(result.sheet) == ''


def test_missing_denominators_keep_documented_flow_without_substitutions():
    result = imported(source(measurements='NUTRITION:\nWeight: 30 kg\nHeight: 120 cm'))
    text = ecls_text(result.sheet)
    assert '2.3 L/min' in text
    assert '85.2' not in text
    assert '76.7' not in text
    assert 'CI: 9.9' not in text
    assert 'CI: 2.3' not in text


def test_encrypted_round_trip_and_old_archive_compatibility():
    current = imported().sheet
    vault = save_sheet_in(new_vault(), current)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == vault
    assert ecls_text(restored['rooms']['P4102']) == ecls_text(current)
    old = new_sheet('P4104')
    old['fields']['Diagnoses'] = 'LEGACY_ROOM'
    assert 'ecls' not in old
    validate_sheet(old)
    old_vault = save_sheet_in(new_vault(), old)
    assert open_vault(seal_vault(old_vault, key), key) == old_vault


def test_ecls_only_room_is_available_to_print():
    result = import_replacement('P4102', block('ad', READINGS), new_vault()['settings'])
    assert result.sheet is not None
    assert 'P4102' in available_handoffs(new_vault(), {'P4102': result.sheet})

