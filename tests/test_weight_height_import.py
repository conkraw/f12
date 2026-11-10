from style_assert_helpers import without_style_tags
"""v6.35 nutrition-import regression tests. Synthetic fixtures only."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from anthropometrics import clean_field, empty_anthropometrics, validate_anthropometrics
from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_sections
from import_review import diagnostic, review_summary
from models import new_sheet, new_vault, fields_with_medications, validate_sheet
from security import generate_key, seal_vault, open_vault


def block(letter, body):
    return letter * 24 + '\n' + body + '\n' + letter * 24


def nutrition(height='120 cm (3\' 11.24")'):
    return ('NUTRITION:\nWt Readings from Last 1 Encounters:\n'
            '01/02/26\t20 kg (25%, Z= -0.70)*\n'
            '* Growth percentiles are based on CDC (Girls, 2-20 Years) data.\n'
            '\nDosing Weight:\nDosing Weight\n Dosing\n 18 kg\n Yesterday\n'
            '\nBMI:\nBody mass index is 13.89 kg/m².\n'
            '\nHeight:\nHeight: ' + height + '\n'
            '\nBSA:\nBody surface area is 0.80 meters squared.\n')


def import_i(sheet=None, height='120 cm (3\' 11.24")'):
    return import_sections(sheet or new_sheet('P4102'), block('i', nutrition(height)), new_vault()['settings'])


@pytest.mark.parametrize('source,expected', [
    ('120 cm (3\' 11.24")', '120 cm'),
    ('120 CM (3\'11.24")', '120 cm'),
    ('120 cm (3′ 11.24″)', '120 cm'),
    ('120 cm (3’ 11.24”)', '120 cm'),
    ('120 cm (3 ft 11.24 in)', '120 cm'),
    ('120 cm (3 ft. 11.24 in.)', '120 cm'),
    ('120 cm (3 feet 11.24 inches)', '120 cm'),
    ('120 cm ( 3 \' 11.24 " )', '120 cm'),
    ('120\u00a0cm\u00a0(3\' 11.24")', '120 cm'),
    ('1.20 m (3\' 11.24")', '1.20 m'),
    ('152.4 cm (5\' 0")', '152.4 cm'),
    ('47.24 in (3\' 11.24")', '47.24 in'),
    ('100 cm (3\' 3")', '100 cm'),  # Compatible with whole-inch rounding.
    ('60 cm (1\' 11.62")', '60 cm'),
    ('120 cm', '120 cm'), ('1.20 m', '1.20 m'),
    ('47 inches', '47 inches'), ('None', ''), ('', ''),
])
def test_recorded_primary_height_and_equivalent(source, expected):
    assert clean_field('height', source) == expected
    data = empty_anthropometrics()
    data['height'] = expected
    validate_anthropometrics(data)


@pytest.mark.parametrize('source', [
    '120 cm (6\' 11.24")', '120 cm (3\' 15.24")',
    '120 cm (unknown)', '120 cm (measured at bedside)',
    '120 cm (3\' 11.24)', '120 cm (3\' -11.24")',
    '120 cm (3\' 11.24") extra text', '0 cm (0\' 0")',
    '-120 cm', '120', 'NaN cm', '120 cm (3\' 11.24") (unknown)',
    '120 cm (3\' 11.24"', '120 cm (3\' 11.24"\nPRIVATE_SENTINEL)',
])
def test_unknown_or_conflicting_annotations_are_not_silently_discarded(source):
    with pytest.raises(ValueError):
        clean_field('height', source)


def test_repeated_height_heading_does_not_block_measured_or_dosing_weight():
    result = import_i()
    assert not result.errors, result.errors
    assert not result.skipped
    assert result.sheet['nutrition'] == {'weight': '20 kg', 'z_score': '-0.70', 'include': True}
    assert result.sheet['dosing_weight'] == '18 kg'
    assert result.sheet['anthropometrics']['height'] == '120 cm'
    assert result.sheet['anthropometrics']['bmi'] == '13.89 kg/m²'
    assert result.sheet['anthropometrics']['bsa'] == '0.80 m²'
    validate_sheet(result.sheet)


def test_valid_reimport_replaces_old_values_and_clears_only_its_warning():
    old = new_sheet('P4102')
    old['nutrition'] = {'weight': '19 kg', 'z_score': '-0.9', 'include': True}
    old['dosing_weight'] = '17 kg'
    old.setdefault('anthropometrics', empty_anthropometrics()).update(age='6 years', sex='Female', height='118 cm')
    old['import_warnings']['i'] = [diagnostic('i', 'section_parse_failed')]
    old['import_warnings']['r'] = [diagnostic('r', 'orders_count', action='orders_hidden')]
    before = deepcopy(old)
    result = import_i(old)
    assert old == before
    assert not result.errors
    assert 'i' not in result.sheet['import_warnings']
    assert result.sheet['import_warnings']['r'] == before['import_warnings']['r']
    assert result.sheet['nutrition']['weight'] == '20 kg'
    assert result.sheet['dosing_weight'] == '18 kg'
    assert result.sheet['anthropometrics']['age'] == '6 years'
    assert result.sheet['anthropometrics']['sex'] == 'Female'


def test_real_measurement_error_keeps_old_values_but_does_not_block_other_sections():
    old = import_i().sheet
    source = block('i', nutrition('120 cm (6\' 11.24")')) + '\n' + block('e', 'VITALS:\nHeart Rate: 105')
    result = import_sections(old, source, new_vault()['settings'])
    assert result.errors and result.skipped == ['i']
    for key in ['nutrition', 'dosing_weight', 'anthropometrics']:
        assert result.sheet[key] == old[key]
    assert result.sheet['vitals'][0]['value'] == '105'
    assert 'Weight / measurements: not updated' in review_summary(result.sheet)
    assert '120' not in ' '.join(result.errors)
    assert 'disagree' in ' '.join(result.errors)


def test_successful_reimport_restores_per_kg_totals():
    old = import_i().sheet
    out = import_sections(old, block('s', 'Intake 180 mL\nOutput 90 mL\nNet 90 mL'), new_vault()['settings'])
    old = out.sheet
    old['import_warnings']['i'] = [diagnostic('i', 'section_parse_failed')]
    assert 'mL/kg' not in fields_with_medications(old)['FEN / GI']
    result = import_i(old)
    text = handoff_text(result.sheet)
    assert 'In: 180 mL (10 mL/kg)' in text
    assert 'Out: 90 mL (5 mL/kg)' in text
    assert 'IMPORT REVIEW' not in text


def test_same_line_height_equivalent_in_admission_section():
    result = import_sections(new_sheet('P4102'), block('n', 'Date of Admission: 01/01/2026\nHeight: 120 cm (3\' 11.24")'), new_vault()['settings'])
    assert not result.errors
    assert result.sheet['anthropometrics']['height'] == '120 cm'
    assert result.sheet['admission_date'] == '01/01/2026'


def test_text_html_and_pdf_include_normalized_measures_without_warning():
    sheet = import_i().sheet
    sheet['anthropometrics'].update(age='6 years', sex='Female')
    for output in (handoff_text(sheet), without_style_tags(handoff_html(sheet))):
        for text in ('Weight: 20 kg', 'Dosing weight: 18 kg', 'Height: 120 cm', 'BSA: 0.80'):
            assert text in output
        assert 'IMPORT REVIEW' not in output
        assert '11.24' not in output
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert '120 cm' in text and '20 kg' in text and '18 kg' in text
    assert 'IMPORT REVIEW' not in text


def test_encrypted_roundtrip_preserves_normalized_values():
    vault = new_vault()
    vault['rooms']['P4102'] = import_i().sheet
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault
