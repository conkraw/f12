"""Synthetic v6.31 layout, age restriction, sex parsing and storage tests."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from unittest.mock import patch

import pytest
from pypdf import PdfReader
from anthropometrics import (empty_anthropometrics, measurements_text,
                             bmi_output_allowed, extract_anthropometrics)
from bmi_reference import bmi_percentile_summary
from exports import (handoff_text, handoff_html, handoff_pdf, handoffs_pdf,
                     _make_pdf_plan, _plan_heights, print_fit_report)
from importing import import_sections
from models import new_sheet, new_vault, validate_sheet, save_sheet_in, upgrade_vault
from problem_review import suggestions, set_decision, review_text, TITLE
from security import seal_vault, open_vault, generate_key
from lab_windows import display_clock
from test_windows_problem_review import sheet as lab_sheet, med

NOW = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)


def imported(letter, content, s=None):
    if letter == 'i' and not content.startswith('NUTRITION:'):
        content = 'NUTRITION:\n' + content
    block = letter*20 + '\n' + content + '\n' + letter*20
    result = import_sections(s or new_sheet('P4102'), block, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize('age', ['0 days', '10 days', '8 weeks', '52 weeks', '12 months',
    '23 months', '23.99 months', '1 year', '1 year 11 months', '1y 11m',
    '13 months 2 days', '6 weeks 4 days', '0 years', '0.5 years'])
def test_bmi_and_percentile_not_on_handoff_under_two(age):
    s = imported('i', f'Age: {age}\nSex: Male\nBMI: 17.25\nHeight: 65 cm\nBSA: 0.35 m²')
    original = deepcopy(s)
    assert not bmi_output_allowed(s['anthropometrics'])
    for fn in [handoff_text, handoff_html, handoff_pdf]:
        data = fn(s, printed_at=NOW)
        if isinstance(data, bytes):
            data = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
        assert 'BMI:' not in data and 'BMI percentile:' not in data
        assert '17.25' not in data
        assert 'Height: 65 cm' in data and 'BSA: 0.35' in data
    assert s == original
    assert s['anthropometrics']['bmi'] == '17.25 kg/m²'


@pytest.mark.parametrize('age', ['24 months', '2 years', '2 years 0 months', '25 months 2 days', '62 months', '19 years', '35 years'])
def test_bmi_value_visible_at_or_above_two(age):
    s = imported('i', f'Age: {age}\nSex: Female\nBMI: 18.37')
    with patch('bmi_reference.load_reference', side_effect=OSError):
        text = handoff_text(s, printed_at=NOW)
        assert 'BMI: 18.37 kg/m²' in text
        assert 'reference needed' not in text and 'age/sex needed' not in text
        assert 'BMI percentile:' not in text


def test_unknown_age_not_assumed_from_growth_footnote():
    s = imported('i', 'NUTRITION:\n11/08/2026 12 kg (40%, Z= 0.2)*\n'
        '* Growth percentiles are based on WHO (Boys, 0-2 years) data.\nSex: Male\nBMI: 17.25')
    assert s['anthropometrics']['age'] == ''
    assert 'BMI:' not in handoff_text(s, printed_at=NOW)
    assert s['nutrition']['z_score'] == '0.2'


@pytest.mark.parametrize('letter', ['i','n'])
@pytest.mark.parametrize('source,expected', [('Sex: Male', 'Male'), ('Sex: Female', 'Female'),
    ('Sex: M','Male'), ('Sex: f','Female'), ('SEX:\t male','Male'),
    ('Sex:\nFemale','Female'), ('Sex:\nSex: Male','Male')])
def test_explicit_sex_formats_survive_import_and_save(letter,source,expected):
    content = ('Date of Admission: 11/01/2026\n' if letter == 'n' else 'NUTRITION:\n')
    content += 'Age: 62 months\nBMI: 17.25\n' + source
    s = imported(letter,content)
    assert s['anthropometrics']['sex'] == expected
    v = save_sheet_in(new_vault(), s)
    key = generate_key()
    assert open_vault(seal_vault(v,key),key) == v


def test_under_two_does_not_load_reference_or_calculate_on_export():
    s = imported('i', 'Age: 23 months\nSex: Male\nBMI: 17.25')
    with patch('bmi_reference.bmi_percentile', side_effect=AssertionError('must not calculate')):
        assert 'BMI' not in handoff_text(s,printed_at=NOW)
        assert bmi_percentile_summary(s['anthropometrics'])[0].startswith('not calculated')


def test_percentile_uses_explicit_sex_without_changing_formula():
    s = imported('i', 'Age: 62 months\nSex: F\nBMI: 17.25')
    with patch('bmi_reference.bmi_percentile', return_value=73.4) as call:
        text = measurements_text(s['anthropometrics'])
        call.assert_called_once_with(17.25, 62.0, 'Female')
        assert 'BMI percentile: 73.4 (CDC)' in text


def test_blank_sex_clears_and_conflicting_sex_cannot_silently_replace():
    s = imported('i', 'Age: 62 months\nSex: Female\nBMI: 17.25')
    before = deepcopy(s)
    result = import_sections(s, 'n'*20+'\nSex: Male\nSex: Female\n'+'n'*20,new_vault()['settings'])
    assert result.errors and result.sheet['anthropometrics'] == before['anthropometrics']
    cleared = imported('n', 'Date of Admission: 11/01/2026\nSex:', s)
    assert cleared['anthropometrics']['sex'] == ''


def test_problem_names_are_inline_no_evidence_or_review_copy():
    s = lab_sheet('NA\t132 (L)\t11/08/2026\nK\t2.8 (L)\t11/08/2026\nMG\t1.4 (L)\t11/08/2026')
    original = deepcopy(s)
    assert TITLE == 'Problems'
    text = review_text(s, NOW)
    assert text == 'Hyponatremia, Hypokalemia, Hypomagnesemia'
    assert '\n' not in text and '132' not in text and '2.8' not in text
    for fn in [handoff_text, handoff_html, handoff_pdf]:
        data = fn(s, printed_at=NOW)
        if isinstance(data, bytes):
            data = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
        assert 'Problems:' in data
        assert 'Hyponatremia, Hypokalemia, Hypomagnesemia' in data
        assert all(t not in data for t in ['Review Required', 'Review for:', 'Reviewed by user:', 'Review prompts only'])
    assert s == original


def test_problem_band_has_no_separate_heading_height():
    s = lab_sheet('NA\t132 (L)\t11/08/2026\nK\t2.8 (L)\t11/08/2026')
    with display_clock(NOW):
        plan = _make_pdf_plan(s,792,7.2)
    labels = [label for label,_ in plan['bands']]
    i = labels.index('Problems')
    _, heights, _ = _plan_heights(plan)
    assert heights[i] <= 15
    assert len(plan['bands'][i][1]) == 1


def test_unconfirmed_proxy_triggers_use_names_but_keep_editor_evidence():
    s = lab_sheet('CO2\t16 (L)\t11/08/2026')
    med(s)
    assert 'Sepsis' in review_text(s,NOW) and 'Possible' not in review_text(s,NOW)
    assert 'Metabolic acidosis' in review_text(s,NOW)
    assert 'organ dysfunction' not in review_text(s,NOW)
    item = next(x for x in suggestions(s,NOW) if x['key']=='sepsis')
    assert 'organ dysfunction' in item['caution']
    s = set_decision(s,'sepsis',item['fingerprint'],'confirmed','Sepsis')
    assert review_text(s,NOW).startswith('Sepsis, ')


def test_confirm_hide_and_changed_evidence_choices_remain_intact():
    s = lab_sheet('NA\t132 (L)\t11/08/2026\nK\t2.8 (L)\t11/08/2026')
    for item in suggestions(s,NOW):
        status = 'dismissed' if item['key']=='NA' else 'confirmed'
        s = set_decision(s,item['key'],item['fingerprint'],status,item['label'])
    assert review_text(s,NOW)=='Hypokalemia'
    s['labs']['rows'][0]['value']='130 (L)'
    assert review_text(s,NOW)=='Hyponatremia, Hypokalemia'
    assert suggestions(s,NOW)[0]['status']=='review'
    s['problem_review']['enabled']=False
    assert review_text(s,NOW)==''


def test_duplicate_custom_problem_names_print_once_and_are_escaped():
    s=lab_sheet('NA\t132 (L)\t11/08/2026\nK\t2.8 (L)\t11/08/2026')
    for item in suggestions(s,NOW):
        s=set_decision(s,item['key'],item['fingerprint'],'confirmed','Electrolytes <check>')
    assert review_text(s,NOW)=='Electrolytes <check>'
    assert review_text(s,NOW,rich=True)=='Electrolytes &lt;check&gt;'


def test_no_auto_problems_no_empty_print_band():
    s=new_sheet('P4102')
    assert review_text(s,NOW)==''
    assert 'Problems:' not in handoff_text(s,printed_at=NOW)
    with display_clock(NOW):
        assert all(label!='Problems' for label,_ in _make_pdf_plan(s,792,7.2)['bands'])


def test_bmi_under_two_and_compact_problems_in_print_all():
    a=imported('i','Age: 9 months\nSex: Male\nBMI: 17.25')
    b=lab_sheet('K\t2.8 (L)\t11/08/2026');b['room']='P4104'
    result=PdfReader(BytesIO(handoffs_pdf([a,b],printed_at=NOW)))
    assert len(result.pages)==2
    assert '17.25' not in result.pages[0].extract_text()
    assert 'Problems: Hypokalemia' in result.pages[1].extract_text()


def test_existing_records_settings_timestamps_unmodified():
    s=lab_sheet('NA\t132 (L)\t11/08/2026')
    s['anthropometrics']=dict(age='13 months',sex='Male',bmi='17.25 kg/m²',height='70 cm',bsa='0.4 m²')
    item=suggestions(s,NOW)[0];s=set_decision(s,item['key'],item['fingerprint'],'confirmed',item['label'])
    vault=save_sheet_in(new_vault(),s)
    before=deepcopy(vault)
    key=generate_key()
    after=upgrade_vault(open_vault(seal_vault(vault,key),key))
    assert after==before
    handoff_pdf(after['rooms']['P4102'],printed_at=NOW)
    assert after==before
