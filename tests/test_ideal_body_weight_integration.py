"""Synthetic IBW integration checks across import, screen, exports and cache."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import re

import pytest
from pypdf import PdfReader

import ideal_body_weight
from bmi_reference import load_reference
from exports import (handoff_html, handoff_pdf, handoff_text, handoffs_html,
                     handoffs_pdf, patient_column)
from growth_assessment import growth_measurements_text
from ideal_body_weight import assess_ideal_body_weight
from importing import import_replacement, import_sections
from models import fields_with_medications, new_vault, validate_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from test_bmi_age_and_categories import imported as import_growth, block
from test_callbacks import app, open_room
from test_iv_fluids_integration import HEADER, order
from test_ui_smoke import equip
from test_ventilation import BLOCK as VENTILATION_BLOCK


NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
EXPECTED = 'Estimated IBW: 50.8 kg (BMI 50th %tile)'


def obese_sheet(room='P4102', **kwargs):
    options = dict(age='15 y.o.', bmi_age='15 y.o. 0 m.o.', bmi='39.06',
                   weight='100 kg', height='160 cm')
    options.update(kwargs)
    value = import_growth(**options)
    value['room'] = room
    value['dosing_weight'] = '90 kg'
    validate_sheet(value)
    return value


def output_text(value):
    if isinstance(value, bytes):
        value = '\n'.join(page.extract_text() or ''
                          for page in PdfReader(BytesIO(value)).pages)
    else:
        value = re.sub(r'<[^>]+>', '', value)
    return ' '.join(value.split())


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_imported_estimate_appears_once_with_measured_and_dosing_weights(render):
    value = obese_sheet()
    before = deepcopy(value)
    rendered = output_text(render(value, NOW))
    assert EXPECTED in rendered
    assert rendered.count('Estimated IBW:') == 1
    assert 'Weight: 100 kg' in rendered
    assert 'Dosing weight: 90 kg' in rendered
    assert value == before


def test_patient_column_uses_same_shared_growth_display():
    value = obese_sheet()
    assert EXPECTED in growth_measurements_text(value)
    columns = fields_with_medications(value)
    assert EXPECTED in patient_column(value, columns)
    assert all('Estimated IBW:' not in columns[key]
               for key in ('Neurologic', 'Respiratory', 'FEN / GI'))


def test_screen_handoff_uses_shared_estimate(app, monkeypatch):
    open_room(app)
    value = obese_sheet()
    app.st.session_state['drafts']['P4102'] = value
    equip(app, monkeypatch)
    seen = []
    app.st.markdown = lambda content, **kwargs: seen.append(content)
    app.handoff_notes(value)
    rendered = output_text('\n'.join(seen))
    assert EXPECTED in rendered
    assert rendered.count('Estimated IBW:') == 1


def test_obese_patient_missing_height_gets_editor_reason_and_no_estimate(app, monkeypatch):
    open_room(app)
    value = obese_sheet()
    value['anthropometrics']['height'] = ''
    app.st.session_state['drafts']['P4102'] = value
    equip(app, monkeypatch)
    texts, captions = [], []
    app.st.text = lambda content, **kwargs: texts.append(content)
    app.st.caption = lambda content, **kwargs: captions.append(content)
    app.neuro_weight_editor(value)
    assert any('Growth category: Severe obesity' in str(content) for content in texts)
    assert not any('Estimated IBW:' in str(content) for content in texts)
    assert any('Estimated IBW needs a valid recorded height' in str(content)
               for content in captions)
    assert 'Estimated IBW:' not in handoff_text(value, NOW)


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_height_edit_recalculates_and_bmi_edit_removes_old_estimate(render):
    value = obese_sheet()
    assert EXPECTED in output_text(render(value, NOW))
    value['anthropometrics']['height'] = '170 cm'
    new = output_text(render(value, NOW))
    assert 'Estimated IBW: 57.4 kg (BMI 50th %tile)' in new
    assert EXPECTED not in new
    value['anthropometrics']['bmi'] = '20 kg/m²'
    assert 'Estimated IBW:' not in output_text(render(value, NOW))


def test_partial_nutrition_reimport_clears_old_bmi_age_and_estimate():
    value = obese_sheet()
    assert EXPECTED in handoff_text(value, NOW)
    replacement = block('i', 'NUTRITION:\nWeight: 100 kg\nDosing Weight: 90 kg\n'
                            'BMI: 39.06\nHeight: 160 cm')
    current = import_sections(value, replacement, new_vault()['settings'])
    assert not current.errors, current.errors
    assert 'bmi_age' not in current.sheet['anthropometrics']
    assert 'Estimated IBW:' not in handoff_text(current.sheet, NOW)


def test_whole_room_replacement_discards_estimate_and_old_patient_data():
    previous = obese_sheet()
    replacement = block('a', 'Diagnoses:\n1. New synthetic patient\n'
                            'Age: 10 months\nSex: Male')
    current = import_replacement('P4102', replacement, new_vault()['settings'])
    assert not current.errors, current.errors
    assert current.sheet['id'] != previous['id']
    assert assess_ideal_body_weight(current.sheet).weight_kg is None
    assert 'Estimated IBW:' not in handoff_text(current.sheet, NOW)
    assert current.sheet['nutrition'] is None
    assert current.sheet['dosing_weight'] == ''


@pytest.mark.parametrize('render', [handoffs_pdf, handoffs_html])
def test_print_all_keeps_each_estimate_in_its_patient_column(render):
    first = obese_sheet()
    second = obese_sheet('P4104', height='170 cm', bmi='34.6')
    packet = render([first, second], NOW)
    if isinstance(packet, bytes):
        pages = [output_text(page.extract_text() or '')
                 for page in PdfReader(BytesIO(packet)).pages]
    else:
        pages = [output_text(body) for body in re.findall(r'<main>(.*?)</main>', packet, re.S)]
    assert len(pages) == 2
    assert EXPECTED in pages[0]
    assert 'Estimated IBW: 57.4 kg' not in pages[0]
    assert 'Estimated IBW: 57.4 kg (BMI 50th %tile)' in pages[1]
    assert EXPECTED not in pages[1]


def test_estimate_never_changes_medication_fluids_ventilation_or_documented_weights():
    value = obese_sheet()
    med_block = block('b', 'Medications:\n' + HEADER + '\n' + '\n'.join([
        order(rate='130 mL/hr at 11/24/26 0400', admin='130 mL/hr at 11/24/26 0400'),
        order(name='midazolam (Versed) injection 2 mg', dose='0.1 mg/kg (Dosing Weight)',
              frequency='q2h PRN', rate='', admin='2 mg at 11/24/26 0400'),
    ]))
    current = import_sections(value, med_block + '\n' + block('c', VENTILATION_BLOCK),
                              new_vault()['settings'])
    assert not current.errors, current.errors
    value = current.sheet
    before = deepcopy(value)
    fields_with_ibw = fields_with_medications(value)
    assert '(maintenance)' in fields_with_ibw['FEN / GI']
    assert '130 mL/hr' in fields_with_ibw['FEN / GI']
    assert value['ventilation'] is not None
    assert len(value['medications']) == 2
    for render in (handoff_text, handoff_html, handoff_pdf):
        assert EXPECTED in output_text(render(value, NOW))
        assert value == before
    no_ibw = deepcopy(value)
    no_ibw['anthropometrics']['bmi'] = '20 kg/m²'
    fields_without_ibw = fields_with_medications(no_ibw)
    for section in ('Neurologic', 'Respiratory', 'FEN / GI', 'Other Medications'):
        assert fields_with_ibw[section] == fields_without_ibw[section]
    assert value['nutrition']['weight'] == '100 kg'
    assert value['dosing_weight'] == '90 kg'


def test_pdf_cache_rebuilds_changed_patient_and_reuses_other_patient():
    first, second = obese_sheet(), obese_sheet('P4104', height='170 cm')
    cache = SessionPdfCache()
    try:
        cached_handoffs_pdf([first, second], cache, NOW)
        assert cache.stats['builds'] == 2
        first['anthropometrics']['height'] = '180 cm'
        updated = cached_handoffs_pdf([first, second], cache, NOW)
        assert cache.stats['builds'] == 3
        assert cache.stats['hits'] == 1
        pages = PdfReader(BytesIO(updated)).pages
        assert 'Estimated IBW: 64.3 kg' in output_text(pages[0].extract_text())
        assert EXPECTED not in output_text(pages[0].extract_text())
        assert 'Estimated IBW: 57.4 kg' in output_text(pages[1].extract_text())
        first['anthropometrics']['bmi'] = '20 kg/m²'
        removed = cached_handoffs_pdf([first, second], cache, NOW)
        assert cache.stats['builds'] == 4
        assert cache.stats['hits'] == 2
        assert 'Estimated IBW:' not in PdfReader(BytesIO(removed)).pages[0].extract_text()
    finally:
        cache.close()


def test_pdf_cache_includes_ibw_reference_output_without_patient_edits(monkeypatch):
    value = obese_sheet()
    cache = SessionPdfCache()
    try:
        old = cache.prepare(value, NOW)
        changed_reference = deepcopy(load_reference())
        changed_reference[1, 180.5]['m'] = 20.0
        monkeypatch.setattr(ideal_body_weight, 'load_reference', lambda: changed_reference)
        updated = cache.prepare(value, NOW)
        assert old.signature != updated.signature
        assert cache.stats['builds'] == 2
        assert 'Estimated IBW: 51.2 kg' in output_text(updated.data)
        assert EXPECTED not in output_text(updated.data)
    finally:
        cache.close()
