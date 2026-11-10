"""6.55 presentation and category regressions. All inputs are synthetic."""
from copy import deepcopy
from datetime import datetime
from html import unescape
from io import BytesIO
import re
import pytest
from pypdf import PdfReader

from capd import parse_capd, capd_display_row
from clinical_style import clinical_markup, clinical_runs, HIGH_COLOR
from categories import (catalog, default_categories, placement, apply_category_rules,
                        set_category_rule, save_category, medication_blocks)
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_sections
from lab_windows import display_clock, EASTERN, lactate_summary
from medication_groups import group_for, automatic_group
from models import (new_sheet, new_vault, validate_sheet, validate_vault,
                    upgrade_vault, automatic_vitals, SCHEMA_VERSION)
from fen_gi import effective_section
from security import generate_key, seal_vault, open_vault
from test_rooms_infusions import med

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=EASTERN)
NEW_ID = 'group:airway_vasoconstrictor'
LABELS = ['Room', 'Age', 'Sex', 'Admission', 'Diagnoses', 'Weight', 'Z-score',
          'Dosing weight', 'Height', 'BSA', 'EVD', 'Lactate']

def block(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24

def imported(source, old=None):
    with display_clock(NOW):
        result = import_sections(old or new_sheet('P4102'), source, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet

def synthetic_sheet(capd='11'):
    source = '\n'.join([
        block('a', 'Diagnoses:\n1. Synthetic example\nAge: 6 y.o. Sex: female'),
        block('b', 'Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n'
              '• racepinephrine (Asthmanefrin) 2.25 % nebulizer solution\t0.5 mL\tNebulization\tq4h PRN\tExample\t\t\n'
              '• albuterol nebulizer solution\t2.5 mg\tNebulization\tq4h\tExample\t\t\n'
              '• pantoprazole injection\t10 mg\tIntravenous\tDaily\tExample\t\t'),
        block('e', 'VITALS:\nTemp: 37 C\nHeart Rate: [80-110] 95\nResp: [18-25] 20\nBP: 98/54\nSpO2 Avg: 99 % Min: 97 % Max: 100 %\nLast SPO2: SpO2: 99 %'),
        block('f', 'CULTURES:\nNo results found for the last 90 days.'),
        block('g', 'LABS:\nComponent\tValue\tDate\n'
              'LACTATE\t1.1\t11/09/2026 1300\nLACWB\t1.0\t11/09/2026 1000\n'
              'NA\t137\t11/09/2026\nK\t3.8\t11/09/2026\nCL\t102\t11/09/2026\n'
              'CO2\t24\t11/09/2026\nBUN\t9\t11/09/2026\nCREATININE\t0.35\t11/09/2026\n'
              'GLUCOSE\t98\t11/09/2026\nHGB\t11.6\t11/09/2026\nHCT\t34.8\t11/09/2026\n'
              'WBC\t8.2\t11/09/2026\nPLT\t245\t11/09/2026'),
        block('i', 'NUTRITION:\nWt Readings from Last 1 Encounters:\n11/09/26\t18.5 kg (25%, Z= -0.50)\n'
              'Dosing Weight: 18.5 kg\nHeight: 110 cm\nBSA: 0.75 m²'),
        block('k', 'SBS Last 24 Hours: SBS 0\nLast SBS Ever: SBS -1'),
        block('l', 'WAT Score:\nWAT-1 total score (0-12): 1'),
        block('m', 'ICP Trends:\nICP Range: ICP Mean (mmHg) Avg: 7 Min: 1 Max: 12\nLast ICP: ICP Mean (mmHg): 6 mmHg\n'
              'CPP Range: CPP Avg: 65 Min: 52 Max: 78\nLast CPP: CPP: 68 mmHg'),
        block('n', 'Date of Admission: 11/08/2026'),
        block('v', 'Intracranial Pressure Monitor:\nIntracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Clamped'),
        block('y', 'CAPD: Cornell Assessment of Pediatric Delirium Score: ' + capd),
    ])
    sheet = imported(source)
    sheet['fields']['Goals / Follow-up'] = 'Synthetic preview. Not a real patient.'
    return sheet

@pytest.mark.parametrize('label', LABELS)
def test_requested_label_only_is_bold(label):
    out = clinical_markup(label + ': 12 [11/9/2026 12:30]')
    assert out == '<b>' + label + ':</b> 12 [11/9/2026 12:30]'
    runs = clinical_runs(label + ': None')
    assert runs == [(label + ':', True, ''), (' None', False, '')]

def test_case_and_escaping_without_interpreting_notes():
    assert clinical_markup('Dosing weight: <10') == '<b>Dosing weight:</b> &lt;10'
    assert clinical_markup('Other note at 12:30') == 'Other note at 12:30'
    assert clinical_markup('Diagnoses: <script>bad</script>') == '<b>Diagnoses:</b> &lt;script&gt;bad&lt;/script&gt;'

@pytest.mark.parametrize('score', range(33))
def test_capd_inclusive_threshold_and_source_not_modified(score):
    parsed = parse_capd('CAPD: ' + str(score))
    assert not parsed.error
    before = deepcopy(parsed.rows)
    display = capd_display_row(parsed.rows)
    expected = str(score) + (' (H)' if score >= 9 else '')
    assert display['value'] == expected
    markup = clinical_markup('CAPD: ' + display['value'])
    assert '<b>CAPD:</b>' in markup
    assert (HIGH_COLOR in markup) == (score >= 9)
    assert '<b>' + str(score) not in markup
    assert parsed.rows == before and parsed.rows[0]['value'] == str(score)

@pytest.mark.parametrize('text', ['', 'CAPD:', 'CAPD: None', 'CAPD: No data recorded'])
def test_absent_capd_is_not_flagged(text):
    parsed = parse_capd(text)
    assert not parsed.error
    display = capd_display_row(parsed.rows)
    assert display['value'] == 'None'
    assert HIGH_COLOR not in clinical_markup('CAPD: ' + display['value'])

def test_hidden_capd_does_not_show_high_score():
    rows = parse_capd('CAPD: 20').rows
    rows[0]['include'] = False
    assert capd_display_row(rows)['value'] == 'None'

def test_failed_y_import_does_not_color_retained_high_value():
    sheet = imported(block('y', 'CAPD: 11'))
    result = import_sections(sheet, block('y', 'CAPD: invalid'), new_vault()['settings'])
    assert result.errors
    assert result.sheet['neuro_vitals']['y'][0]['value'] == '11'
    assert 'CAPD: None' in automatic_vitals(result.sheet)['Neurologic']
    assert 'CAPD: 11' not in automatic_vitals(result.sheet)['Neurologic']

@pytest.mark.parametrize('name', [
    'racepinephrine (Asthmanefrin) 2.25 % nebulizer solution',
    'RACEPINEPHRINE hydrochloride inhalation solution',
    'racemic epinephrine 2.25 % solution',
    'epinephrine racemic inhalation solution',
    'epinephrine (racemic) 2.25 % nebulizer solution',
    'epinephrine, racemic nebulizer solution',
    'Asthmanefrin nebulizer solution',
    '[Held by provider] racepinephrine nebulizer solution',
    '[START ON 11/10/2026] racemic epinephrine nebulizer solution',
])
def test_airway_category_recognizes_explicit_racemic_products(name):
    row = med(name, dose='0.5 mL', route='Nebulization', frequency='q4h PRN', rate='', section='Other Medications')
    before = deepcopy(row)
    assert group_for(row) == 'airway_vasoconstrictor'
    assert effective_section(row) == 'Respiratory'
    assert placement(row)['id'] == NEW_ID
    assert placement(row)['name'] == 'Airway Vasoconstrictor'
    assert row == before

@pytest.mark.parametrize('name,route,frequency', [
    ('epinephrine infusion', 'Intravenous', 'Continuous'),
    ('norepinephrine infusion', 'Intravenous', 'Continuous'),
    ('epinephrine injection', 'Intramuscular', 'Once'),
    ('racepinephrine injection', 'Intravenous', 'Once'),
    ('racemic epinephrine infusion', '', 'Continuous'),
    ('racepinephrine nebulizer solution', 'Intravenous', 'Once'),
    ('racepinephrine eye drops', 'Ophthalmic', 'Daily'),
    ('epinephrine inhaler', 'Inhalation', 'PRN'),
    ('albuterol racepinephrine mixture', 'Nebulization', 'q4h'),
    ('racepinephrine-like product', 'Nebulization', 'q4h'),
])
def test_does_not_recategorize_nonmatching_or_nonairway_products(name,route,frequency):
    row = med(name, route=route, frequency=frequency)
    assert automatic_group(row) != 'airway_vasoconstrictor'


def test_explicit_override_hidden_order_and_single_destination():
    row = med('racepinephrine nebulizer solution', route='Nebulization', frequency='q4h PRN')
    settings = set_category_rule(new_vault()['settings'], 'racepinephrine', 'system:Other Medications')
    assigned = apply_category_rules([row], settings)[0]
    assert effective_section(assigned) == 'Other Medications'
    s = new_sheet('P4102')
    s['medications'] = [assigned]
    assert handoff_html(s).count('racepinephrine nebulizer solution') == 1
    row['hidden'] = True
    s['medications'] = [row]
    assert 'Airway Vasoconstrictor' not in handoff_html(s)
    assert 'racepinephrine nebulizer solution' not in handoff_html(s)


def test_custom_parent_and_category_name_are_editable():
    settings = save_category(new_vault()['settings'], 'Airway medications', 'Respiratory', ident='custom:airway')
    settings = save_category(settings, 'Airway Vasoconstrictor', 'Respiratory', ident=NEW_ID, parent='custom:airway')
    row = med('racepinephrine solution', route='Nebulization', frequency='q4h PRN')
    row = apply_category_rules([row], settings)[0]
    assert placement(row)['parent_name'] == 'Airway medications'
    blocks = medication_blocks('Respiratory', '', [row])
    assert blocks[:2] == [('heading', 'Airway medications'), ('subheading', 'Airway Vasoconstrictor')]


def test_scheduled_and_prn_orders_are_not_merged_or_duplicated():
    s = new_sheet('P4102')
    s['medications'] = [med('racepinephrine test', route='Nebulization', frequency=f) for f in ['q4h', 'q4h PRN']]
    html = handoff_html(s)
    assert html.count('racepinephrine test') == 2
    assert html.count('<b>Airway Vasoconstrictor</b>') == 1


def test_complete_handoff_requested_styles_and_source_unchanged():
    s = synthetic_sheet()
    before = deepcopy(s)
    with display_clock(NOW):
        html = handoff_html(s, NOW)
        pdf = handoff_pdf(s, NOW)
        text = handoff_text(s, NOW)
    for label in LABELS:
        assert '<b>' + label + ':</b>' in html, label
    assert '<b>CAPD:</b> <font color="' + HIGH_COLOR + '">11 (H)</font>' in html
    assert '<b>EVD:</b> Clamped' in html
    assert '<b>Lactate:</b> 1.0 -&gt; 1.1 [11/9/2026]' in html
    assert '<b>Airway Vasoconstrictor</b>' in html
    assert text.count('CAPD: 11 (H)') == 1
    assert text.count('racepinephrine') == 1
    assert 'Lactate: 1.0 -> 1.1 [11/9/2026]' in text
    assert s == before
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    pdf_text = reader.pages[0].extract_text()
    assert 'CAPD: 11 (H)' in pdf_text and 'Airway Vasoconstrictor' in pdf_text


def test_print_packet_does_not_leak_capd_flag_between_rooms():
    a, b = synthetic_sheet('9'), synthetic_sheet('8')
    b['room'] = 'P4104'
    with display_clock(NOW):
        reader = PdfReader(BytesIO(handoffs_pdf([a, b], NOW)))
    assert len(reader.pages) == 2
    assert 'CAPD: 9 (H)' in reader.pages[0].extract_text()
    assert 'CAPD: 8 (H)' not in reader.pages[1].extract_text()
    assert 'CAPD: 8' in reader.pages[1].extract_text()


def test_schema33_upgrade_preserves_records_and_existing_catalog():
    vault = new_vault()
    vault['schema'] = 33
    vault['settings']['medication_categories'] = [x for x in default_categories() if x['id'] != NEW_ID]
    vault['settings']['medication_category_rules'] = []
    vault['settings']['medication_categories'][0]['name'] = 'Preserved custom name'
    sheet = synthetic_sheet()
    sheet['updated_at'] = '2026-11-09T19:00:00+00:00'
    vault['rooms']['P4102'] = sheet
    before = deepcopy(vault)
    updated = upgrade_vault(vault)
    assert vault == before and updated['schema'] == SCHEMA_VERSION == 34
    assert updated['rooms'] == before['rooms']
    existing = {x['id']: x for x in before['settings']['medication_categories']}
    actual = {x['id']: x for x in catalog(updated['settings'])}
    assert set(actual) - set(existing) == {NEW_ID}
    for key, value in existing.items():
        assert actual[key] == value
    validate_vault(updated)
    key = generate_key()
    assert open_vault(seal_vault(updated, key), key) == updated


def test_new_capd_flag_does_not_create_problem_list_diagnosis():
    from problem_review import suggestions
    sheet = imported(block('y', 'CAPD: 24'))
    assert not any('deliri' in row['label'].lower() for row in suggestions(sheet, NOW))
    assert sheet['fields']['Diagnoses'] == ''
