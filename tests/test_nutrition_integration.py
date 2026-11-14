"""Synthetic compact nutrition import, UI, recall and export checks."""
from copy import deepcopy
from datetime import datetime, timezone
import re

import fitz
import pytest

from batching import available_handoffs
from diet import diet_for_output
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from feeds import feeds_for_output
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, validate_sheet
from nutrition_display import nutrition_text
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip


DIET = """Dietary Orders:
Dietary Orders (From admission, onward)
Start Ordered
01/05/26 0800
Infant tube feeding Pediatric Tube Feeding; Synthetic Formula 1.0; Continuous Feeds; Gastrostomy tube; 20 hours; 30; 600; No Additives; 24 Diet effective now
Comments: Pause feeds for the recorded four-hour daily break.
Question\tAnswer\tComment
Diet:\tPediatric Tube Feeding
Formula:\tSynthetic Formula 1.0
Type:\tContinuous Feeds
Route:\tGastrostomy tube
Infusion time (hours)\t20 hours
Tube feeding continuous rate (mL/hr):\t30
Total Volume (mL/day):\t600
Additives?\tNo Additives
Caloric density (kcal per ounce):\t24
01/05/26 0801
Diet Orders
Infant tube feeding Pediatric Tube Feeding; Synthetic Formula 1.0; Continuous Feeds; Gastrostomy tube; 20 hours; 30; 600; No Additives; 24: Tube Feeding starting at 01/05 0800"""
ORAL = "\nPediatric diet Regular: General starting at 01/05 0800"
PN = "\nPediatric 2-in-1 PN (Continuous) at 9 mL/hr starting at 01/05 2100"
T = """Gastric Tube Gastrostomy-Tube Feeding: Synthetic Formula 1.0
Gastric Tube Gastrostomy-Continuous Tube Feeding Ordered Rate mL/hr (not calculated): 30 mL"""
POST = DIET.replace('Gastrostomy tube', 'Nasoenteric (post-pyloric) tube')
NJ = T.replace('Gastric Tube Gastrostomy', 'Gastric Tube Nasojejunal')
MEDICATION = """Medications:
Medication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin
• Pediatric 2-in-1 PN (Continuous)\t9 mL/hr\tIntravenous\tContinuous\tSynthetic Provider\t9 mL/hr at 01/05/26 2100\t9 mL/hr at 01/05/26 2100"""


def block(key, body):
    marker = key * 15 + ('a' if key == 'ab' else '')
    return marker + '\n' + body + '\n' + marker


def imported(diet=DIET, *, extra='', old=None, key='ab', weight='10 kg'):
    sheet = deepcopy(old) if old is not None else new_sheet('P4102')
    sheet['dosing_weight'] = weight
    result = import_sections(sheet, block(key, diet) + '\n' + extra, new_vault()['settings'])
    assert result.sheet is not None and not result.errors and not result.skipped, result.errors
    return result.sheet


def output(sheet):
    return fields_with_medications(sheet)['FEN / GI']


def scheduled_source(hours='', daily_volume=''):
    """Keep all repeated representations consistent for a synthetic schedule."""
    return (DIET.replace('20 hours', hours + ' hours' if hours else '')
            .replace('; 600;', '; ' + daily_volume + ';')
            .replace('\t600', '\t' + daily_volume)
            .replace('Pause feeds for the recorded four-hour daily break.',
                     'Synthetic instructions retained for editing.'))


def test_detailed_table_and_summary_are_one_order_with_twenty_hour_calculation():
    sheet = imported()
    assert len(sheet['diet']['enteral']) == 1
    text = output(sheet)
    assert 'Tube feed:\nGT: Synthetic Formula 1.0 (24 kcal/oz) @ 30 mL/hr (20 hr/day) | 480 kcal/day | 60 mL/kg/day' in text
    assert text.count('Synthetic Formula 1.0') == 1
    assert 'four-hour daily break' not in text and 'Using dosing weight' not in text
    assert '600 mL/day' not in text and ' = ' not in text
    assert 'four-hour daily break' in sheet['diet']['enteral'][0]['comments']


def test_ab_together_with_x_uses_detailed_order_without_second_summary():
    sheet = imported(extra=block('x', 'Diet:\nNPO diet NPO except: No Exceptions'))
    text = output(sheet)
    assert '480 kcal/day' in text and '60 mL/kg/day' in text and 'NPO' not in text
    assert len(sheet['diet']['enteral']) == 1


def test_explicit_oral_tube_and_pn_can_coexist_and_matching_medication_pn_prints_once():
    sheet = imported(DIET + ORAL + PN, extra=block('b', MEDICATION))
    text = output(sheet)
    assert 'Diet:' in text and 'Regular' in text and 'Tube feed:' in text
    assert 'Oral:' not in text
    assert text.count('Pediatric 2-in-1 PN') == 1
    assert 'TPN (diet order)' not in text
    validate_sheet(sheet)


def test_pn_only_and_enteral_only_are_available_for_print_all():
    for source in ('Dietary Orders:\nDiet Orders\n' + PN, DIET):
        sheet = imported(source, weight='')
        assert 'P4102' in available_handoffs(new_vault(), {'P4102': sheet})


def test_current_matching_t_and_dietary_order_are_not_duplicated():
    sheet = imported(extra=block('t', T))
    assert sheet['diet']['recorded_feed_ids'] == [sheet['feeds']['rows'][0]['id']]
    assert output(sheet).count('Synthetic Formula 1.0') == 1


def test_different_formula_current_nj_and_postpyloric_order_use_one_ordered_primary_entry():
    ordered = POST.replace('Synthetic Formula 1.0', 'Synthetic Milk')
    recorded = NJ.replace('Synthetic Formula 1.0', 'Recorded Formula B')
    sheet = imported(ordered, extra=block('t', recorded))
    assert sheet['diet']['enteral'][0]['method'] == 'NJ'
    assert sheet['feeds']['rows'][0]['formula'] == 'Recorded Formula B'
    text = output(sheet)
    assert text.count('Tube feed:') == 1 and text.count('Synthetic Milk') == 1
    assert 'NJ: Synthetic Milk (24 kcal/oz) @ 30 mL/hr (20 hr/day) | 480 kcal/day | 60 mL/kg/day' in text
    assert 'Recorded Formula B' not in text and 'Post-pyloric:' not in text


def test_distinct_gt_and_nj_feeds_keep_their_own_routes_and_formulas():
    recorded = NJ.replace('Synthetic Formula 1.0', 'Recorded Formula B').replace('30 mL', '12 mL')
    sheet = imported(extra=block('t', recorded))
    text = output(sheet)
    assert text.count('Tube feed:') == 1
    assert 'GT: Synthetic Formula 1.0' in text
    nj_line = next(line for line in text.splitlines() if line.startswith('NJ:'))
    assert 'Recorded Formula B @ 12 mL/hr' in nj_line and '28.8 mL/kg/day' in nj_line
    assert 'kcal/day' not in nj_line and '24 hr/day' not in nj_line


def test_ambiguous_two_nj_devices_are_not_collapsed_into_one_order():
    first = (NJ.replace('Nasojejunal', 'Nasojejunal 6 Fr Right nostril')
             .replace('Synthetic Formula 1.0', 'Recorded Formula B'))
    second = (NJ.replace('Nasojejunal', 'Nasojejunal 8 Fr Left nostril')
              .replace('Synthetic Formula 1.0', 'Recorded Formula C').replace('30 mL', '12 mL'))
    sheet = imported(POST, extra=block('t', first + '\n' + second))
    assert sheet['diet']['enteral'][0]['method'] == 'Post-pyloric'
    text = output(sheet)
    assert text.count('Tube feed:') == 1 and text.count('\nNJ:') == 2
    assert '\nPost-pyloric:' in text
    assert text.count('Recorded Formula B') == text.count('Recorded Formula C') == 1


def test_precise_nj_requires_unambiguous_same_import_source():
    fresh = imported(POST, extra=block('t', NJ))
    assert fresh['diet']['enteral'][0]['method'] == 'NJ'
    old = imported(POST, extra=block('t', NJ))
    updated = imported(POST, old=old)
    assert updated['diet']['enteral'][0]['method'] == 'Post-pyloric'
    assert updated['diet']['recorded_feed_ids'] == []
    assert '\nNJ:' not in output(updated) and '\nPost-pyloric:' in output(updated)


def test_multiple_postpyloric_devices_do_not_supply_a_guessed_subtype():
    dual = NJ + '\n' + NJ.replace('Nasojejunal', 'Nasoduodenal')
    sheet = imported(POST, extra=block('t', dual))
    assert sheet['diet']['enteral'][0]['method'] == 'Post-pyloric'
    text = output(sheet)
    assert text.count('Tube feed:') == 1
    assert '\nPost-pyloric:' in text and '\nNJ:' in text and '\nND:' in text


def test_fresh_none_does_not_resurrect_old_recorded_t_feed():
    old = imported(extra=block('t', T))
    sheet = imported('Dietary Orders:\nDiet Orders\nNone', old=old, weight='')
    assert sheet['feeds'] == old['feeds']
    assert sheet['diet']['recorded_feed_ids'] == []
    assert 'Synthetic Formula' not in output(sheet)
    assert 'P4102' not in available_handoffs(new_vault(), {'P4102': sheet})


def test_later_explicit_t_update_is_available_without_changing_saved_order_route():
    old = imported(POST)
    result = import_sections(old, block('t', NJ.replace('30 mL', '15 mL')), new_vault()['settings'])
    assert not result.errors
    sheet = result.sheet
    assert sheet['diet']['enteral'][0]['method'] == 'Post-pyloric'
    assert sheet['diet']['recorded_feed_ids'] == [sheet['feeds']['rows'][0]['id']]
    text = output(sheet)
    assert 'Recorded rate:' not in text and '15 mL/hr' not in text
    assert '30 mL/hr (20 hr/day) | 480 kcal/day | 60 mL/kg/day' in text


def test_failed_ab_keeps_values_for_review_and_cannot_restore_old_t_display():
    old = imported(extra=block('t', T))
    before = deepcopy(old)
    bad = 'ab' * 12 + '\nDietary Orders:\nInfant tube feeding broken\n'
    result = import_sections(old, bad + block('a', 'Diagnoses:\n1. Synthetic updated diagnosis'), new_vault()['settings'])
    assert result.errors and result.skipped == ['ab']
    assert result.sheet['diet'] == before['diet'] and old == before
    assert diet_for_output(result.sheet) is None and feeds_for_output(result.sheet) is None
    assert 'Synthetic Formula' not in output(result.sheet)
    assert 'Synthetic updated diagnosis' in result.sheet['fields']['Diagnoses']
    recovered = imported(old=result.sheet)
    assert 'ab' not in recovered['import_warnings'] and '60 mL/kg/day' in output(recovered)


def test_current_weight_only_is_not_used_in_place_of_dosing_weight():
    sheet = imported(weight='')
    sheet['nutrition'] = {'weight': '10 kg', 'z_score': '', 'include': True}
    assert '480 kcal/day' in output(sheet) and 'mL/kg/day' not in output(sheet)
    sheet['dosing_weight'] = '5 kg'
    assert '120 mL/kg/day' in output(sheet)


@pytest.mark.parametrize('hours,daily', [('', ''), ('24', '720')])
def test_missing_or_explicit_twenty_four_hour_schedule_is_compact(hours, daily):
    sheet = imported(scheduled_source(hours, daily))
    text = output(sheet)
    assert '30 mL/hr | 576 kcal/day | 72 mL/kg/day' in text
    assert '24 hr/day' not in text and 'Assum' not in text and '720 mL/day' not in text
    assert sheet['diet']['enteral'][0]['hours'] == hours


@pytest.mark.parametrize('hours', ['48', '20-24', 'Unknown'])
def test_explicit_unusable_hours_do_not_become_a_twenty_four_hour_calculation(hours):
    sheet = imported(scheduled_source(hours, ''))
    assert sheet['diet']['enteral'][0]['hours'] == ''
    assert any(item['field'] == 'hours' for item in sheet['import_warnings']['ab'])
    text = output(sheet)
    assert '30 mL/hr' in text
    assert 'mL/kg/day' not in text and 'kcal/day' not in text and '24 hr/day' not in text


def test_conflicting_hour_sources_stay_uncalculated_after_duplicate_summary():
    source = DIET.replace('Infusion time (hours)\t20 hours', 'Infusion time (hours)\t18 hours')
    sheet = imported(source)
    assert len(sheet['diet']['enteral']) == 1 and sheet['diet']['enteral'][0]['hours'] == ''
    assert any(item['field'] == 'hours' for item in sheet['import_warnings']['ab'])
    text = output(sheet)
    assert '30 mL/hr' in text and 'mL/kg/day' not in text and 'kcal/day' not in text


@pytest.mark.parametrize('kind', ['invalid', 'conflicting'])
def test_acknowledging_hours_warning_cannot_create_default_totals_before_manual_correction(app, kind):
    source = (scheduled_source('48', '') if kind == 'invalid' else
              scheduled_source('20', '').replace('Infusion time (hours)\t20 hours',
                                                 'Infusion time (hours)\t18 hours'))
    sheet = imported(source)
    assert sheet['diet']['enteral'][0]['hours'] == ''
    open_room(app)
    app.set_editor('P4102', sheet)
    ss = app.st.session_state
    app.acknowledge_import_warning('P4102', 'ab')
    acknowledged = ss['drafts']['P4102']
    assert 'ab' not in acknowledged['import_warnings']
    assert 'mL/kg/day' not in output(acknowledged) and 'kcal/day' not in output(acknowledged)
    app.save_room(None)
    key = generate_key()
    recalled = open_vault(seal_vault(ss['vault'], key), key)['rooms']['P4102']
    assert recalled['diet']['enteral'][0]['hours'] == ''
    assert 'mL/kg/day' not in output(recalled) and 'kcal/day' not in output(recalled)
    app.set_editor('P4102', recalled)
    row = ss['drafts']['P4102']['diet']['enteral'][0]
    widget = 'diet_enteral_' + row['id'] + '_hours'
    ss[widget] = '24'
    app.dietary_order_change('P4102', 'enteral', row['id'], 'hours', widget)
    assert row['hours'] == '24'
    corrected = output(ss['drafts']['P4102'])
    assert '576 kcal/day' in corrected and '72 mL/kg/day' in corrected


@pytest.mark.parametrize('qa_unit,value,stored_density,calories', [
    ('kcal per ounce', '24', '24 kcal/oz', '480'),
    ('kcal/mL', '1.5', '1.5 kcal/mL', '900'),
    ('kcal/L', '1000', '1000 kcal/L', '600'),
])
def test_explicit_density_units_produce_the_corresponding_daily_calories(qa_unit, value, stored_density, calories):
    source = (DIET.replace('; No Additives; 24', '; No Additives; ' + stored_density)
              .replace('Caloric density (kcal per ounce):\t24',
                       'Caloric density (' + qa_unit + '):\t' + value))
    sheet = imported(source)
    assert sheet['diet']['enteral'][0]['caloric_density'] == stored_density
    text = output(sheet)
    assert calories + ' kcal/day' in text and '60 mL/kg/day' in text


def test_numeric_formula_name_does_not_supply_an_unstated_caloric_density():
    source = (DIET.replace('; No Additives; 24', '; No Additives;')
              .replace('Caloric density (kcal per ounce):\t24', 'Caloric density (kcal per ounce):\t'))
    sheet = imported(source)
    text = output(sheet)
    assert 'Synthetic Formula 1.0' in text and '60 mL/kg/day' in text
    assert not sheet['diet']['enteral'][0]['caloric_density'] and 'kcal/day' not in text


def test_conflicting_density_blocks_calories_but_keeps_volume_normalization():
    source = DIET.replace('Caloric density (kcal per ounce):\t24', 'Caloric density (kcal per ounce):\t27')
    sheet = imported(source)
    assert not sheet['diet']['enteral'][0]['caloric_density']
    assert any(item['field'] == 'caloric_density' for item in sheet['import_warnings']['ab'])
    text = output(sheet)
    assert '60 mL/kg/day' in text and 'kcal/day' not in text


def test_t_only_legacy_input_uses_the_compact_tube_feed_display():
    initial = new_sheet('P4102')
    initial['dosing_weight'] = '10 kg'
    result = import_sections(initial, block('t', T), new_vault()['settings'])
    assert not result.errors and result.sheet['diet'] is None
    text = output(result.sheet)
    assert 'Tube feed:\nGT: Synthetic Formula 1.0 @ 30 mL/hr | 72 mL/kg/day' in text
    assert 'Feeding Method:' not in text and '24 hr/day' not in text and 'kcal/day' not in text


def test_npo_medication_exception_uses_diet_without_creating_tube_feed():
    source = 'Dietary Orders:\nDiet Orders\nNPO diet NPO except: Other (specify); Explanatory comment: except for medications (NJ): NPO starting at 01/05 0800'
    text = output(imported(source))
    assert 'Diet: NPO except meds (NJ)' in text
    assert 'Oral:' not in text and 'Tube feed:' not in text


def test_updated_dietary_snapshot_survives_encrypted_recall_without_mutation():
    sheet = imported(DIET + ORAL + PN, extra=block('t', T))
    before = deepcopy(sheet)
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    loaded = open_vault(seal_vault(vault, key), key)
    assert loaded == vault and loaded['schema'] == 34
    assert output(loaded['rooms']['P4102']) == output(sheet)
    assert sheet == before
    legacy = new_vault()
    legacy['rooms']['P4104'] = new_sheet('P4104')
    assert open_vault(seal_vault(legacy, key), key) == legacy


def test_nutrition_does_not_change_qtc_avaps_nirs_or_other_saved_data():
    old = new_sheet('P4102')
    old['ecg'] = {'value': '475', 'date': '01/02/2020'}
    old['fields']['Respiratory'] = 'Synthetic respiratory note'
    before = deepcopy(old)
    sheet = imported(old=old)
    for key in old:
        if key not in ('diet', 'dosing_weight', 'empty_group_layout'):
            assert sheet[key] == before[key], key
    assert 'QTc: 475 msec [01/02/2020] (!)' in handoff_text(sheet)


def test_compact_text_html_single_and_batch_pdf_keep_calculations_without_verbose_fields():
    fortified = (DIET.replace('; No Additives; 24', '; Additives; Synthetic Fortifier = 24 kcal/oz')
                 .replace('Additives?\tNo Additives', 'Additives?\tAdditives\nSelect Additive\tSynthetic Fortifier = 24 kcal/oz'))
    sheet = imported(fortified + ORAL + PN)
    other = imported(DIET.replace('30;', '15;').replace('600;', '300;').replace('\t30', '\t15').replace('\t600', '\t300'))
    other['room'] = 'P4104'
    stamp = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)
    stored = sheet['diet']['enteral'][0]
    assert 'Synthetic Fortifier' in stored['additives'] and 'four-hour daily break' in stored['comments']
    forbidden = ('Instructions:', 'Additives:', 'Synthetic Fortifier', 'four-hour daily break',
                 'Using dosing weight:', '600 mL/day', ' = ', 'Oral:', 'Recorded rate:')
    # Script assignments are not visible feeding-volume equations.
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', handoff_html(sheet, stamp), flags=re.I | re.S)
    exports = [handoff_text(sheet, stamp), html]
    with fitz.open(stream=handoff_pdf(sheet, stamp), filetype='pdf') as pdf:
        exports.append(re.sub(r'\s+', ' ', ''.join(page.get_text() for page in pdf)))
    with fitz.open(stream=handoffs_pdf([sheet, other], stamp), filetype='pdf') as pdf:
        assert len(pdf) == 2
        first = re.sub(r'\s+', ' ', pdf[0].get_text())
        second = re.sub(r'\s+', ' ', pdf[1].get_text())
        exports.append(first)
        assert '30 mL/kg/day' in second and '240 kcal/day' in second
        assert '60 mL/kg/day' not in second and '480 kcal/day' not in second
    for text in exports:
        assert '60 mL/kg/day' in text and '480 kcal/day' in text
        assert 'Diet:' in text and text.count('Tube feed:') == 1
        assert all(value not in text for value in forbidden)


@pytest.mark.parametrize('group,field,value', [
    ('enteral', 'rate', '25 mL/hr'), ('enteral', 'hours', '24'),
    ('enteral', 'formula', 'Changed synthetic formula'), ('enteral', 'include', False),
    ('enteral', 'method', 'NJ'), ('enteral', 'comments', 'Synthetic instructions'),
    ('parenteral', 'rate', '7 mL/hr'), ('parenteral', 'include', False),
])
def test_ui_callbacks_pending_edits_and_save(app, group, field, value):
    open_room(app)
    app.set_editor('P4102', imported(DIET + PN))
    ss = app.st.session_state
    row = ss['drafts']['P4102']['diet'][group][0]
    key = 'diet_' + group + '_' + row['id'] + '_' + field
    ss[key] = value
    app.dietary_order_change('P4102', group, row['id'], field, key)
    assert row[field] == value
    snapshot = app.editor_snapshot('P4102')
    assert snapshot['diet'][group][0][field] == value
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['diet'][group][0][field] == value


def test_invalid_hours_edit_is_rejected_without_changing_diet(app):
    open_room(app)
    app.set_editor('P4102', imported())
    ss = app.st.session_state
    row = ss['drafts']['P4102']['diet']['enteral'][0]
    key = 'diet_enteral_' + row['id'] + '_hours'
    ss[key] = '48'
    app.dietary_order_change('P4102', 'enteral', row['id'], 'hours', key)
    assert row['hours'] == ss[key] == '20'
    assert ss['notice'][0] == 'error'


def test_multiline_feeding_instruction_edit_survives_save(app):
    open_room(app)
    app.set_editor('P4102', imported())
    ss = app.st.session_state
    row = ss['drafts']['P4102']['diet']['enteral'][0]
    key = 'diet_enteral_' + row['id'] + '_comments'
    ss[key] = 'Synthetic mixing instruction.\nPause for the prescribed break.'
    app.dietary_order_change('P4102', 'enteral', row['id'], 'comments', key)
    app.save_room(None)
    stored = ss['vault']['rooms']['P4102']['diet']['enteral'][0]['comments']
    assert stored == 'Synthetic mixing instruction. Pause for the prescribed break.'


def test_complete_editor_and_pdf_download_with_all_nutrition_modes(app, monkeypatch):
    open_room(app)
    app.set_editor('P4102', imported(DIET + ORAL + PN, extra=block('t', T)))
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data, bytes) and data.startswith(b'%PDF') for _, data in downloads)
    for group, fields in app.DIET_ORDER_FIELDS.items():
        row = app.st.session_state['drafts']['P4102']['diet'][group][0]
        assert all('diet_' + group + '_' + row['id'] + '_' + field in app.st.session_state for field, _ in fields)
