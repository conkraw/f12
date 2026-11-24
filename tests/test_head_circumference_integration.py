"""Synthetic HC measurement-age imports, rendering, edits and persistence."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

import head_circumference as hc_module
from anthropometrics import extract_age_sex, extract_anthropometrics
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from growth_assessment import growth_measurements_text
from head_circumference import assess_head_circumference
from importing import import_replacement, import_sections
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_growth_integration import NOW, block, imported as growth_imported, source, text_from_output
from test_ui_smoke import equip


ANCHOR = '2026-11-22'
BOYS_DAY_183_MEDIAN = '43.3393'


def hc_sheet(*, age='190 days', hc_age=None, sex='Male', head=BOYS_DAY_183_MEDIAN,
             recorded='11/15/26'):
    entry = 'Head Circumference: ' + head + ' cm'
    if recorded:
        entry += ' (' + recorded + ' 0400)'
    if hc_age is not None:
        entry += '\nHC Age: ' + hc_age
    sheet = growth_imported(age=age, sex=sex, circumferences=entry)
    sheet['age_as_of'] = ANCHOR
    validate_sheet(sheet)
    return sheet


@pytest.mark.parametrize('label', ['HC Age', 'Head Circumference Age', 'Age at HC measurement'])
@pytest.mark.parametrize('letter', ['a', 'i', 'n'])
def test_explicit_hc_age_imports_in_a_i_and_n_without_replacing_general_age(label, letter):
    prefix = {'a': 'Diagnoses:\n1. Synthetic condition\n',
              'i': 'NUTRITION:\n', 'n': 'Date of Admission: 11/22/2026\n'}[letter]
    text = prefix + 'Age: 190 days\nSex: male\n' + label + ': 183 days'
    result = import_sections(new_sheet('P4102'), block(letter, text), new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    attrs = result.sheet['anthropometrics']
    assert attrs['age'] == '190 days'
    assert attrs['hc_age'] == '183 days'
    assert attrs['sex'] == 'Male'
    assert 'bmi_age' not in attrs
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', result.sheet['age_as_of'])


@pytest.mark.parametrize('text', ['HC Age:\n183 days', 'HC Age in months: 6',
                                  'Age: 190 days HC Age: 183 days Sex: male'])
def test_hc_age_metadata_is_removed_from_prose(text):
    for parse in (extract_age_sex, extract_anthropometrics):
        result = parse(text)
        assert not result.error
        assert result.values['hc_age'] in ('183 days', '6 months')
        assert not result.remainder.strip()


def test_historical_hc_uses_age_on_measurement_date_and_official_day_183_median():
    sheet = hc_sheet()
    original = deepcopy(sheet)
    result = assess_head_circumference(sheet)
    assert result.percentile == pytest.approx(50)
    assert result.inputs['age_days'] == 183
    assert result.inputs['age_as_of'] == ANCHOR
    assert result.display_text == '[50th %tile]'
    assert 'adjusted back to the HC date 2026-11-15' in result.reason
    assert sheet == original


@pytest.mark.parametrize('age', ['183 days', '26 weeks 1 day', '6 months'])
def test_explicit_measurement_age_overrides_source_date_and_does_not_use_bmi_age(age):
    sheet = hc_sheet(hc_age=age, recorded='01/01/26')
    sheet['anthropometrics']['bmi_age'] = '12 months'
    sheet.pop('age_as_of')
    result = assess_head_circumference(sheet)
    assert result.percentile == pytest.approx(50)
    assert result.display_text == '[50th %tile]'
    assert result.inputs['age_source'] == 'HC Age'
    assert result.inputs['age_as_of'] == ''


def test_rounded_general_month_age_is_marked_as_an_estimate():
    sheet = hc_sheet(age='6 months', recorded='11/22/26')
    result = assess_head_circumference(sheet)
    assert result.percentile == pytest.approx(50)
    assert result.inputs['age_days'] == 182.625
    assert result.display_text == '[~50th %tile]'
    assert 'estimate' in result.reason
    assert '[~50th %tile]' in growth_measurements_text(sheet)


def test_print_time_and_unrelated_timestamp_changes_cannot_age_historical_hc():
    sheet = hc_sheet()
    first = assess_head_circumference(sheet)
    before = handoff_text(sheet, NOW)
    later = datetime(2027, 3, 1, 18, 0, tzinfo=timezone.utc)
    sheet['updated_at'] = later.isoformat()
    sheet['created_at'] = later.isoformat()
    after = handoff_text(sheet, later)
    assert assess_head_circumference(sheet) == first
    assert 'Head circumference: 43.3393 cm [11/15/26] [50th %tile]' in before
    assert 'Head circumference: 43.3393 cm [11/15/26] [50th %tile]' in after


@pytest.mark.parametrize('change', ['sex', 'coarse_age', 'legacy_date', 'missing_date'])
def test_unusable_percentile_inputs_preserve_raw_hc_when_current_age_is_under_two(change):
    sheet = hc_sheet()
    if change == 'sex':
        sheet['anthropometrics']['sex'] = ''
    elif change == 'coarse_age':
        sheet['anthropometrics']['age'] = '1 year'
    elif change == 'legacy_date':
        sheet.pop('age_as_of')
    elif change == 'missing_date':
        sheet['circumferences']['head']['date'] = ''
    assert assess_head_circumference(sheet).percentile is None
    assert assess_head_circumference(sheet).reason
    output = growth_measurements_text(sheet)
    assert 'Head circumference: 43.3393 cm' in output
    assert '%tile]' not in output
    assert sheet['circumferences']['head']['value_cm'] == BOYS_DAY_183_MEDIAN


def test_blank_optional_hc_age_falls_back_to_general_age_and_dated_hc():
    sheet = hc_sheet(hc_age='')
    result = assess_head_circumference(sheet)
    assert result.percentile == pytest.approx(50)
    assert result.inputs['age_source'] == 'Age'
    assert result.inputs['age_days'] == 183
    assert '[50th %tile]' in growth_measurements_text(sheet)


@pytest.mark.parametrize('hc_age,valid', [('40 days', False), ('21 days', False), ('20 days', True)])
def test_explicit_hc_age_cannot_exceed_the_documented_week_age_window(hc_age, valid):
    sheet = hc_sheet(age='2 weeks', hc_age=hc_age, recorded='11/22/26')
    result = assess_head_circumference(sheet)
    assert (result.percentile is not None) == valid
    if not valid:
        assert 'later than the documented patient age' in result.reason
        assert '%tile]' not in growth_measurements_text(sheet)


@pytest.mark.parametrize('age', ['700 days', '100 weeks', '183.5 days', '730 days'])
def test_precise_days_and_weeks_under_two_remain_eligible_in_assessment_and_display(age):
    sheet = hc_sheet(age=age, recorded='11/22/26')
    result = assess_head_circumference(sheet)
    assert result.percentile is not None
    body = growth_measurements_text(sheet)
    assert 'Head circumference: 43.3393 cm' in body
    assert result.display_text in body


@pytest.mark.parametrize('age', ['730.5 days', '731 days', '104 weeks', '105 weeks', '24 months', '2 years'])
def test_second_birthday_and_older_remain_outside_hc_display(age):
    sheet = hc_sheet(age=age, recorded='11/22/26')
    assert assess_head_circumference(sheet).percentile is None
    assert 'Head circumference:' not in growth_measurements_text(sheet)


def test_unknown_general_age_keeps_raw_storage_but_preserves_existing_display_gate():
    sheet = hc_sheet(hc_age='183 days')
    sheet['anthropometrics']['age'] = ''
    assert assess_head_circumference(sheet).percentile is None
    assert sheet['circumferences']['head']['value_cm'] == BOYS_DAY_183_MEDIAN
    assert 'Head circumference:' not in growth_measurements_text(sheet)


@pytest.mark.parametrize('recorded,anchor', [
    ('2026-11-23', ANCHOR), ('2026-01-01', ANCHOR),
    ('2026-02-31', ANCHOR), ('2026-11-15', '2026-13-22'),
])
def test_future_prebirth_or_invalid_dates_cannot_produce_a_percentile(recorded, anchor):
    sheet = hc_sheet()
    sheet['circumferences']['head']['date'] = recorded
    sheet['age_as_of'] = anchor
    result = assess_head_circumference(sheet)
    assert result.percentile is None
    assert result.reason
    assert result.display_text == ''


@pytest.mark.parametrize('age', ['1 year', '250 days', '24 months'])
def test_unusable_or_contradictory_explicit_hc_age_does_not_fall_back_to_general_age(age):
    sheet = hc_sheet(hc_age=age)
    assert assess_head_circumference(sheet).percentile is None
    assert '%tile]' not in growth_measurements_text(sheet)


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_same_hc_percentile_reaches_all_single_patient_exports(render):
    sheet = hc_sheet()
    original = deepcopy(sheet)
    output = ' '.join(text_from_output(render(sheet, NOW)).split())
    assert 'Head circumference: 43.3393 cm [11/15/26] [50th %tile]' in output
    assert sheet == original


def test_print_all_keeps_hc_percentiles_on_their_patient_pages():
    first = hc_sheet()
    # Boys day183 M=43.3393 and S=.02817, so this is exactly +1 SD.
    second = hc_sheet(head=str(43.3393 * (1 + .02817)))
    second['room'] = 'P4104'
    pages = PdfReader(BytesIO(handoffs_pdf([first, second], NOW))).pages
    assert len(pages) == 2
    texts = [' '.join(page.extract_text().split()) for page in pages]
    assert '[50th %tile]' in texts[0]
    assert '[84th %tile]' not in texts[0]
    assert '[84th %tile]' in texts[1]
    assert '[50th %tile]' not in texts[1]


def test_screen_handoff_uses_the_same_hc_percentile(app, monkeypatch):
    open_room(app)
    sheet = hc_sheet()
    app.st.session_state['drafts']['P4102'] = sheet
    equip(app, monkeypatch)
    seen = []
    app.st.markdown = lambda value, **kwargs: seen.append(value)
    app.handoff_notes(sheet)
    output = re.sub('<[^>]+>', '', '\n'.join(seen))
    assert 'Head circumference: 43.3393 cm [11/15/26] [50th %tile]' in output


@pytest.mark.parametrize('change', ['measurement', 'sex', 'hc_age', 'age', 'anchor'])
def test_edited_measurement_or_age_inputs_recalculate_instead_of_retaining_a_percentile(change):
    sheet = hc_sheet()
    first = assess_head_circumference(sheet).percentile
    if change == 'measurement':
        sheet['circumferences']['head']['value_cm'] = '44'
    elif change == 'sex':
        sheet['anthropometrics']['sex'] = 'Female'
    elif change == 'hc_age':
        sheet['anthropometrics']['hc_age'] = '150 days'
    elif change == 'age':
        sheet['anthropometrics']['age'] = '200 days'
    else:
        sheet['age_as_of'] = '2026-12-01'
    assert assess_head_circumference(sheet).percentile != first


def test_new_nutrition_import_and_whole_room_replacement_clear_old_hc_age():
    old = hc_sheet(hc_age='183 days')
    result = import_sections(old, block('i', 'NUTRITION:\nWeight: 6.3 kg\nLength: 58 cm'),
                             new_vault()['settings'])
    assert not result.errors
    assert 'hc_age' not in result.sheet['anthropometrics']
    assert result.sheet['circumferences']['head'] is None
    current = import_replacement('P4102', source(age='190 days'), new_vault()['settings'])
    assert not current.errors
    assert 'hc_age' not in current.sheet['anthropometrics']
    assert assess_head_circumference(current.sheet).display_text == ''


def test_same_paste_hc_age_in_a_survives_its_nutrition_import():
    a = block('a', 'Diagnoses:\n1. Synthetic condition\nAge: 190 days\nHC Age: 183 days\nSex: male')
    i = block('i', 'NUTRITION:\nWeight: 6.3 kg\nHead Circumference: 43.3393 cm')
    result = import_replacement('P4102', a + '\n' + i, new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet['anthropometrics']['hc_age'] == '183 days'
    assert assess_head_circumference(result.sheet).display_text == '[50th %tile]'


@pytest.mark.parametrize('invalid', ['', None, 20261122, '2026-2-3', '2026-02-30'])
def test_schema_rejects_invalid_age_reference_dates(invalid):
    sheet = hc_sheet()
    sheet['age_as_of'] = invalid
    with pytest.raises(ValueError):
        validate_sheet(sheet)


def test_age_reference_and_explicit_hc_age_round_trip_without_derived_state():
    sheet = hc_sheet(hc_age='183 days')
    saved = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    restored = open_vault(seal_vault(saved, key), key)['rooms']['P4102']
    assert restored['age_as_of'] == ANCHOR
    assert restored['anthropometrics']['hc_age'] == '183 days'
    assert assess_head_circumference(restored).display_text == '[50th %tile]'
    assert '%tile]' not in json.dumps(saved)
    assert 'percentile' not in json.dumps(saved)


def test_hc_age_callback_edit_clear_and_pending_snapshot(app):
    open_room(app)
    sheet = hc_sheet()
    ss = app.st.session_state
    ss['drafts']['P4102'] = sheet
    key = 'anthro_' + sheet['id'] + '_hc_age'
    ss[key] = '183 days'
    app.anthropometric_change('P4102', 'hc_age', key)
    assert sheet['anthropometrics']['hc_age'] == '183 days'
    assert sheet['age_as_of'] == ANCHOR
    ss[key] = '150 days'
    pending = app.editor_snapshot('P4102')
    assert pending['anthropometrics']['hc_age'] == '150 days'
    assert sheet['anthropometrics']['hc_age'] == '183 days'
    ss[key] = ''
    app.anthropometric_change('P4102', 'hc_age', key)
    assert 'hc_age' not in sheet['anthropometrics']
    assert sheet['age_as_of'] == ANCHOR


def test_general_age_edit_refreshes_anchor_but_unchanged_age_and_other_edits_do_not(app, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 24, 12, 0, tzinfo=tz)

    monkeypatch.setattr(hc_module, 'datetime', FrozenDateTime)
    open_room(app)
    sheet = hc_sheet()
    ss = app.st.session_state
    ss['drafts']['P4102'] = sheet
    key = 'anthro_' + sheet['id'] + '_age'
    ss[key] = '190 days'
    app.anthropometric_change('P4102', 'age', key)
    assert sheet['age_as_of'] == ANCHOR
    ss['weight_' + sheet['id'] + '_weight'] = '7 kg'
    unchanged = app.editor_snapshot('P4102')
    assert unchanged['age_as_of'] == ANCHOR
    assert unchanged['nutrition']['weight'] == '7 kg'
    ss[key] = '192 days'
    pending = app.editor_snapshot('P4102')
    assert pending['age_as_of'] == '2026-11-24'
    assert sheet['age_as_of'] == ANCHOR
    app.anthropometric_change('P4102', 'age', key)
    assert sheet['age_as_of'] == '2026-11-24'
    assert sheet['anthropometrics']['age'] == '192 days'
    ss[key] = ''
    app.anthropometric_change('P4102', 'age', key)
    assert 'age_as_of' not in sheet
