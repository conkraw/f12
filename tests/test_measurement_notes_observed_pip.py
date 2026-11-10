"""v6.41 import/render regressions using synthetic data and generic charting notes."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import pytest
from pypdf import PdfReader

from anthropometrics import clean_field, extract_anthropometrics
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from importing import import_sections
from import_review import diagnostic
from models import new_sheet, new_vault, validate_sheet, fields_with_medications
from security import generate_key, seal_vault, open_vault
from ventilation import parse_ventilation, format_ventilation

NOTE = 'Fullfiled in cerner - pt admitted prior to EPIC go live which is why recharted'
HEIGHT = '120 cm (3\' 11.24")'
NOW = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)


def paired(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24


def nutrition(height=HEIGHT + ' (' + NOTE + ')'):
    return ('NUTRITION:\nWt Readings from Last 1 Encounters:\n'
            '11/08/26\t20 kg (25%, Z= -0.70)*\n'
            '\nDosing Weight:\nDosing Weight\nDosing\n18 kg\n6 days ago\n'
            '\nBMI:\nBody mass index is 13.89 kg/m².\n'
            '\nHeight:\nHeight: ' + height + '\n'
            '\nBSA:\nBody surface area is 0.80 meters squared.\n')


def ventilator(mode='Volume Targeted Pressure Control - Intermittent Mandatory Ventilation', observed='Avg: 22.4 cm H2O Min: 18.2 cm H2O Max: 28 cm H2O'):
    return ('Invasive Ventilation:\nMode: Vent Mode: ' + mode + '\n'
            'Respiratory Rate: Resp Rate (Set): 16\n'
            'Set PIP: PIP Set (cm H2O): 24 cm H2O\n'
            'Observed PIP: PIP Observed (cm H2O): ' + observed + '\n'
            'Set TV: Vt (Set, mL): 160 mL\n'
            'Observed TV: Vt Insp ml Avg: 158 Min: 152 Max: 164\n'
            'Set PEEP: PEEP (cm H2O): 6 cm H2O\n'
            'Inspiratory Time: Insp Time (sec): 0.8 sec\n'
            'Pressure Support: Pressure Support (cm H2O): 8 cm H20\n')


def imported(room='P4102', source=None):
    if source is None:
        source = (paired('a', 'Diagnoses:\n1. Synthetic example\nAge: 5 y.o. Sex: Male')
                  + '\n' + paired('c', ventilator())
                  + '\n' + paired('d', 'Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube')
                  + '\n' + paired('i', nutrition())
                  + '\n' + paired('s', 'Intake 360 mL\nOutput 270 mL\nNet 90 mL'))
    result = import_sections(new_sheet(room), source, new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    return result.sheet


@pytest.mark.parametrize('value,expected', [
    (HEIGHT + ' (' + NOTE + ')', '120 cm'),
    ('100 cm (3\' 3.37") (' + NOTE + ')', '100 cm'),
    (HEIGHT + ' (Recharted in Epic)', '120 cm'),
    (HEIGHT + ' (Copied from Cerner)', '120 cm'),
    ('120 cm (Transcribed from the prior chart)', '120 cm'),
    ('120 cm (Imported from Cerner during go-live)', '120 cm'),
    (HEIGHT + ' (Documented in Epic on 11/08/2026 at 12:20)', '120 cm'),
    (HEIGHT + ' (Imported from Cerner during 2026 go-live)', '120 cm'),
    (HEIGHT + ' (Copied from Cerner) (Recharted in Epic)', '120 cm'),
    (HEIGHT + ' (Recharted in Epic (imported from Cerner))', '120 cm'),
    ('120 cm (Recharted in Epic) (3\' 11.24")', '120 cm'),
    ('1.20 m (3′ 11.24″) (recharted in Epic)', '1.20 m'),
    ('47.24 in (3\' 11.24") (imported from Cerner)', '47.24 in'),
    ('120\u00a0cm (3’ 11.24”) (' + NOTE + ')', '120 cm'),
    (HEIGHT + ' (Copied from Cerner. ' + 'Recharted in Epic. ' * 10 + ')', '120 cm'),
])
def test_charting_annotations_keep_primary_recorded_height(value, expected):
    assert clean_field('height', value) == expected
    assert clean_field('height', expected) == expected


@pytest.mark.parametrize('suffix', [
    ' (Unknown)', ' (measured at bedside)', ' (Incorrect entry in Cerner)',
    ' (Corrected in Epic)', ' (Entered in error in Epic)',
    ' (120 cm copied from Cerner)', ' (3 ft 11 in copied from Cerner)',
    ' (2026 cm copied from Cerner)', ' (Wrong entry in Epic)',
    ' (Epic value 125)', ' (Do not use imported Epic value)',
    ' (Estimated height from Cerner)', ' (Recheck in Epic)',
    ' (Recharted in Epic', ' recharted in Epic',
    ' (Recharted in Epic))', ' (Copied from Cerner) trailing text',
    ' (Copied from Cerner) (unknown)', ' ()',
    ' (3\' 11.24") (3\' 11.24")',
])
def test_unknown_conflicting_or_invalidating_annotations_still_fail(suffix):
    with pytest.raises(ValueError) as error:
        clean_field('height', HEIGHT + suffix)
    assert suffix not in str(error.value)


def test_imperial_disagreement_is_not_hidden_by_charting_note():
    with pytest.raises(ValueError, match='disagree'):
        clean_field('height', '120 cm (6\' 11.24") (' + NOTE + ')')


def test_annotation_length_is_bounded_and_other_fields_remain_bounded():
    with pytest.raises(ValueError, match='too long'):
        clean_field('height', HEIGHT + ' (Recharted in Epic ' + 'x' * 2000 + ')')
    with pytest.raises(ValueError, match='too long'):
        clean_field('age', '5 years' + 'x' * 101)


def test_repeated_height_headers_and_n_section_accept_documentation_note():
    for header in ['Height:', 'Length:']:
        result = extract_anthropometrics(header + '\n' + header + ' ' + HEIGHT + ' (' + NOTE + ')')
        assert not result.error
        assert result.values['height'] == '120 cm'
    s = imported(source=paired('n', 'Date of Admission: 11/01/2026\nHeight: ' + HEIGHT + ' (' + NOTE + ')'))
    assert s['anthropometrics']['height'] == '120 cm'


def test_complete_nutrition_import_and_fluid_calculations_are_restored():
    old = imported()
    old['nutrition']['weight'] = '19 kg'
    old['dosing_weight'] = '17 kg'
    old['anthropometrics']['height'] = '118 cm'
    old['import_warnings']['i'] = [diagnostic('i', 'section_parse_failed')]
    old['import_warnings']['r'] = [diagnostic('r', 'orders_count', action='orders_hidden')]
    before = deepcopy(old)
    result = import_sections(old, paired('i', nutrition()), new_vault()['settings'])
    assert not result.errors
    assert old == before
    assert result.sheet['nutrition'] == {'weight': '20 kg', 'z_score': '-0.70', 'include': True}
    assert result.sheet['dosing_weight'] == '18 kg'
    assert result.sheet['anthropometrics']['height'] == '120 cm'
    assert result.sheet['anthropometrics']['bmi'] == '13.89 kg/m²'
    assert result.sheet['anthropometrics']['bsa'] == '0.80 m²'
    assert 'i' not in result.sheet['import_warnings']
    assert result.sheet['import_warnings']['r'] == before['import_warnings']['r']
    text = fields_with_medications(result.sheet)['FEN / GI']
    assert 'In: 360 mL (20 mL/kg)' in text
    assert 'Out: 270 mL (15 mL/kg)' in text
    assert result.sheet['updated_at'] == old['updated_at']


def test_bad_height_still_retains_measurements_without_blocking_other_sections():
    old = imported()
    result = import_sections(old, paired('e', 'VITALS:\nHeart Rate: 104')
                             + '\n' + paired('i', nutrition('120 cm (6\' 11.24") (' + NOTE + ')')), new_vault()['settings'])
    assert result.errors and result.skipped == ['i']
    assert result.sheet['nutrition'] == old['nutrition']
    assert result.sheet['dosing_weight'] == old['dosing_weight']
    assert result.sheet['anthropometrics'] == old['anthropometrics']
    assert 'i' in result.sheet['import_warnings']
    assert result.sheet['vitals'][0]['value'] == '104'
    assert 'mL/kg' not in fields_with_medications(result.sheet)['FEN / GI']


@pytest.mark.parametrize('mode', [
    'Volume Targeted Pressure Control - Intermittent Mandatory Ventilation',
    'Volume Targeted Pressure Control - Continuous Mandatory Ventilation',
    'Volume Targeted Pressure Control - PS',
    'Pressure Control - Intermittent Mandatory Ventilation',
    'Pressure Control - Continuous Mandatory Ventilation',
    'Volume Control - Intermittent Mandatory Ventilation',
    'Volume Control - Continuous Mandatory Ventilation',
    'Pressure Support - Continuous Positive Airway Pressure',
    'Average Volume-Assured Pressure Support',
    'Neurally Adjusted Ventilatory Assist',
    'Volume Support Ventilation',
])
def test_observed_pip_prints_for_supported_invasive_modes(mode):
    result = parse_ventilation(ventilator(mode))
    assert not result.error
    before = deepcopy(result.data)
    output = format_ventilation(result.data)
    assert 'Observed PIP: Avg: 22.4 Min: 18.2 Max: 28 cm H2O' in output
    assert output.count('Observed PIP:') == 1
    assert output.index('Observed PIP:') < output.index('Set PEEP:')
    assert result.data == before


@pytest.mark.parametrize('raw,expected', [
    ('22.5 cm H2O', '22.5 cm H2O'), ('22.5', '22.5 cm H2O'),
    ('0 cm H2O', '0 cm H2O'), ('(S) 21 cmH20', '21 cm H2O'),
    ('Avg: 22.4 cm H2O Min: 18.2 cm H2O Max: 28 cm H2O', 'Avg: 22.4 Min: 18.2 Max: 28 cm H2O'),
    ('Min: 18.2 cm H2O Max: 28 cm H2O', 'Min: 18.2 Max: 28 cm H2O'),
    ('Avg: 22.4 cm H2O', 'Avg: 22.4 cm H2O'),
])
def test_scalars_ranges_and_zero_preserve_source_values(raw, expected):
    result = parse_ventilation(ventilator(observed=raw))
    assert not result.error
    assert 'Observed PIP: ' + expected in format_ventilation(result.data)


@pytest.mark.parametrize('blank', ['', '--', '-', 'None', 'N/A', 'No data recorded', 'Not documented'])
def test_no_observed_pip_when_source_has_no_value(blank):
    r = parse_ventilation(ventilator(observed=blank))
    assert not r.error
    assert 'Observed PIP:' not in format_ventilation(r.data)


def test_observed_pip_is_not_derived_from_set_pressure_or_peep():
    s = ventilator('Pressure Control - Intermittent Mandatory Ventilation', observed='21 cm H2O')
    text = format_ventilation(parse_ventilation(s).data)
    assert 'Set PIP: 24 cm H2O' in text and 'Observed PIP: 21 cm H2O' in text
    assert '30 cm H2O' not in text
    s = s.replace('Set PIP: PIP Set (cm H2O): 24 cm H2O', 'Set PIP:')
    text = format_ventilation(parse_ventilation(s).data)
    assert 'Set PIP:' not in text and 'Observed PIP: 21 cm H2O' in text


def test_home_vent_also_displays_observed_pressure_and_preserves_bounds():
    source = ventilator() + '\nPmin: Pmin: 10 cmH2O\nPmax: Pmax: 25 cmH2O\nTimin: Ti Min: 0.8\nTimax: Ti Max: 1.0'
    s = imported(source=paired('c', source))
    text = format_ventilation(s['ventilation'])
    assert 'Device: Home Vent' in text and 'Mode: PRVC\n' in text
    assert 'Observed PIP: Avg: 22.4 Min: 18.2 Max: 28 cm H2O' in text
    assert 'Pmin: 10 cm H2O' in text and 'Pmax: 25 cm H2O' in text


def test_existing_legacy_scalar_field_displays_without_reimport():
    s = new_sheet('P4102')
    s['ventilation'] = {'mode': 'Volume Targeted Pressure Control - PS', 'values': {'PIP Observed (cm H2O)': '22.5 cm H2O'}}
    assert 'Observed PIP: 22.5 cm H2O' in handoff_text(s, NOW)


def test_new_paste_with_missing_pip_does_not_reuse_previous_value():
    old = imported()
    result = import_sections(old, paired('c', ventilator(observed='No data recorded'))
                             + '\n' + paired('d', 'Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube'), new_vault()['settings'])
    assert not result.errors
    assert 'Observed PIP:' not in format_ventilation(result.sheet['ventilation'])
    assert 'PIP Observed (cm H2O)' in old['ventilation']['values']


def test_exports_include_correct_measures_and_observed_pip_without_source_comment():
    s = imported()
    before = deepcopy(s)
    pdf = handoff_pdf(s, NOW)
    doc = PdfReader(BytesIO(pdf))
    assert len(doc.pages) == 1
    for out in [handoff_html(s, NOW), handoff_text(s, NOW), '\n'.join(p.extract_text() for p in doc.pages)]:
        out = ' '.join(out.split())
        assert 'Observed PIP: Avg: 22.4 Min: 18.2 Max: 28 cm H2O' in out
        for phrase in ['Height: 120 cm', 'Dosing weight: 18 kg', 'Weight: 20 kg']:
            assert phrase in out
        assert 'Cerner' not in out and 'cerner' not in out
        assert 'IMPORT REVIEW' not in out
    assert s == before


def test_print_all_isolates_each_room_and_observed_pressure():
    a = imported('P4102')
    b = imported('P4104')
    b['ventilation']['values']['PIP Observed (cm H2O)'] = '13 cm H2O'
    doc = PdfReader(BytesIO(handoffs_pdf([a, b], NOW)))
    assert len(doc.pages) == 2
    assert 'Observed PIP: Avg: 22.4' in doc.pages[0].extract_text()
    assert 'Observed PIP: 13 cm H2O' not in doc.pages[0].extract_text()
    assert 'Observed PIP: 13 cm H2O' in doc.pages[1].extract_text()
    assert 'Observed PIP: Avg: 22.4' not in doc.pages[1].extract_text()


def test_encrypted_roundtrip_and_render_do_not_change_saved_source_values():
    vault = new_vault()
    vault['rooms']['P4102'] = imported()
    key = generate_key()
    expected = deepcopy(vault)
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == expected
    handoff_pdf(restored['rooms']['P4102'], NOW)
    assert restored == expected


def test_current_version_is_used_for_new_technical_reports():
    from error_store import new_error_event
    report = new_error_event([diagnostic('i', 'section_parse_failed')])
    assert report['app_version'] == '6.48'


def test_very_long_primary_height_is_not_accepted_as_a_charting_note():
    with pytest.raises(ValueError):
        clean_field('height', '1' * 101 + ' cm (Recharted in Epic)')
