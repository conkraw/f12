"""Synthetic import, persistence and export checks for an earlier CPAP trial."""
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
import re

import pytest
from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement
from models import new_vault, save_sheet_in, validate_sheet
from security import generate_key, open_vault, seal_vault
from ventilation import format_ventilation


NOW = datetime(2026, 11, 23, 1, 37, tzinfo=timezone.utc)
PRVC = 'Volume Targeted PC - IMV'
PS_CPAP = 'PS - CPAP'
RENDERERS = (handoff_text, handoff_html, handoff_pdf)

SETTINGS = '''Invasive Ventilation:
Mode: Vent Mode: Volume Targeted Pressure Control - Intermittent Mandatory Ventilation
Respiratory Rate: Resp Rate (Set): 14
Set TV: Vt (Set, mL): 180 mL
Set PEEP: PEEP (cm H2O): 6 cm H2O
Inspiratory Time: Insp Time (sec): 0.9 sec
FiO2: FiO2 set (%): 35 %
Pressure Support: Pressure Support (cm H2O): 12 cm H20
NAVA Ventilator Settings:
NAVA Level: 2.4
Set PEEP: PEEP (cm H2O): 8 cm H2O
Set FIO2: FiO2 (%): 29 %
CPAP Trial Settings:
Pressure Support: Pressure Support (cm H2O): 10 cm H20
Set PEEP: PEEP (cm H2O): 5 cm H2O
FiO2: FiO2 set (%): 30 %
Weaning Tidal Volumes: Weaning Tidal Volume Avg: 128.9 mL Min: 101 mL Max: 210 mL
Weaning Tolerance:
All Vent Modes:
'''


def block(letter, value):
    marker = letter * 24
    return marker + '\n' + value.rstrip() + '\n' + marker + '\n'


def source(*, with_trial=True, latest=PRVC):
    prior = PS_CPAP if with_trial else PRVC
    modes = (
        '\t11/22/26 0913\t11/22/26 1130\t11/22/26 1140\n'
        'Other\nVent Mode\t' + '\t'.join((PRVC, prior, PRVC)) + '\n\n'
        '\t11/22/26 1300\t11/22/26 1724\t11/22/26 2000\n'
        'Other\nVent Mode\t' + '\t'.join((PRVC, PRVC, latest)) + '\n'
    )
    return (block('a', 'Diagnoses:\nSynthetic CPAP history regression')
            + block('c', SETTINGS + modes)
            + block('d', 'Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube\nFiO2 (%): 27 %'))


def imported(**kwargs):
    result = import_replacement('P4102', source(**kwargs), new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    return result.sheet


def normalized_export(renderer, sheet):
    output = renderer(sheet, NOW)
    if isinstance(output, bytes):
        reader = PdfReader(BytesIO(output))
        output = '\n'.join(page.extract_text() or '' for page in reader.pages)
    else:
        output = unescape(re.sub(r'<[^>]*>', '', output))
    return ' '.join(output.split())


def test_earlier_trial_keeps_current_mode_and_dedicated_settings_separate():
    sheet = imported()
    data = sheet['ventilation']
    assert data['mode'] == PRVC
    assert sheet['sbs_vent_mode'] == PRVC
    assert sheet['noninvasive'] == []
    assert data['mode_history']['reported_at'] == '2026-11-22T20:00'
    assert data['values']['Pressure Support (cm H2O)'] == '12 cm H20'
    assert data['values']['PEEP (cm H2O)'] == '6 cm H2O'
    assert data['values']['FiO2 set (%)'] == '35 %'
    prior = data['mode_history']['other_modes']
    assert len(prior) == 1
    assert prior[0]['mode'] == PS_CPAP
    assert prior[0]['reported_at'] == '2026-11-22T11:30'
    assert prior[0]['include'] is True
    assert prior[0]['values']['Pressure Support (cm H2O)'] == '10 cm H20'
    assert prior[0]['values']['PEEP (cm H2O)'] == '5 cm H2O'
    assert prior[0]['values']['FiO2 set (%)'] == '30 %'
    current, trial = format_ventilation(data).split('\n---\n')
    assert 'Set RR: 14' in current and 'Set TV: 180 mL' in current
    assert 'CPAP Trial Data' not in current
    assert trial.startswith('CPAP Trial Data\nMode: PS-CPAP (11/22/26 11:30)')
    assert 'Weaning TV: 101–210 mL' in trial
    assert 'Set RR:' not in trial and 'Set TV:' not in trial
    assert 'Weaning Tolerance:' not in trial
    assert 'NAVA' not in trial and '29 %' not in trial and '27 %' not in trial


@pytest.mark.parametrize('renderer', RENDERERS)
def test_every_export_prints_current_imv_then_the_dated_cpap_trial(renderer):
    text = normalized_export(renderer, imported())
    assert text.count('Mode: PRVC-IMV') == 1
    assert text.count('Mode: PS-CPAP') == 1
    assert text.count('CPAP Trial Data') == 1
    assert 'Mode: PRVC-IMV (11/22/26 20:00)' in text
    assert 'Mode: PS-CPAP (11/22/26 11:30)' in text
    assert text.index('Mode: PRVC-IMV') < text.index('CPAP Trial Data')
    assert 'Pressure Support: 10 cm H2O' in text
    assert 'Set PEEP: 5 cm H2O' in text and 'FiO2: 30 %' in text
    assert re.search(r'Weaning TV: 101[–-]210 mL', text)
    assert 'All Vent Modes:' not in text


@pytest.mark.parametrize('renderer', RENDERERS)
def test_explicitly_hidden_trial_stays_hidden_in_exports(renderer):
    sheet = imported()
    data = sheet['ventilation']
    recorded = deepcopy(data['mode_history']['other_modes'][0])
    data['mode_history']['other_modes'][0]['include'] = False
    validate_sheet(sheet)
    text = normalized_export(renderer, sheet)
    assert 'Mode: PRVC-IMV (11/22/26 20:00)' in text
    assert 'CPAP Trial Data' not in text and 'PS-CPAP' not in text
    assert data['mode_history']['other_modes'][0]['values'] == recorded['values']


def test_complete_replacement_without_cpap_history_clears_the_prior_trial():
    original = imported()
    vault = save_sheet_in(new_vault(), original)
    replacement = imported(with_trial=False)
    assert replacement['id'] != original['id']
    assert 'CPAP Trial Settings:' in source(with_trial=False)
    vault = save_sheet_in(vault, replacement)
    current = vault['rooms']['P4102']
    assert current['ventilation']['mode_history']['other_modes'] == []
    for renderer in RENDERERS:
        text = normalized_export(renderer, current)
        assert 'Mode: PRVC-IMV (11/22/26 20:00)' in text
        assert 'CPAP Trial Data' not in text and 'PS-CPAP' not in text


@pytest.mark.parametrize('renderer', RENDERERS)
def test_current_ps_cpap_has_one_trial_and_no_duplicate_historical_copy(renderer):
    sheet = imported(latest=PS_CPAP)
    assert sheet['ventilation']['mode'] == PS_CPAP
    assert sheet['sbs_vent_mode'] == PS_CPAP
    text = normalized_export(renderer, sheet)
    assert text.count('CPAP Trial Data') == 1
    assert text.count('Mode: PS-CPAP') == 1
    assert 'Mode: PS-CPAP (11/22/26 20:00)' in text
    assert '11/22/26 11:30' not in text
    assert 'Mode: PRVC-IMV' not in text


@pytest.mark.parametrize('visible', [True, False])
def test_trial_visibility_and_values_survive_encrypted_save_load(visible):
    sheet = imported()
    sheet['ventilation']['mode_history']['other_modes'][0]['include'] = visible
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    encrypted = seal_vault(vault, key)
    assert b'CPAP' not in encrypted and b'mode_history' not in encrypted
    restored = open_vault(encrypted, key)
    assert restored == vault
    saved = restored['rooms']['P4102']
    assert saved['ventilation']['mode_history']['other_modes'][0]['include'] is visible
    assert format_ventilation(saved['ventilation']) == format_ventilation(sheet['ventilation'])
