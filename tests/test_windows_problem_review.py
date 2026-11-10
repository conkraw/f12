"""v6.30 regressions. All values here are synthetic, never copied patient records."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from decimal import Decimal
import pytest
from pypdf import PdfReader

from labs import parse_labs, empty_labs
from cbc import parse_cbc
from models import new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault, save_sheet_in
from medications import parse_medications, upsert_rule
from importing import import_sections
from security import generate_key, seal_vault, open_vault
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from lab_windows import (display_clock, clock, analyte, rows_for, laboratory_data,
                        lactate_summary, theophylline_summary, cardiac_labs_summary,
                        id_summary, eligible_time, uncertain_24h)
from problem_review import (suggestions, empty_review, validate_review, set_decision,
                            review_text, limitation_notes, LOW_RULES)
from anthropometrics import clean_field

NOW = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)  # 15:00 EST


def sheet(rows=''):
    s = new_sheet('P4102')
    result = parse_labs('LABS:\nComponent\tValue\tDate\n' + rows)
    assert not result.error, result.error
    s['labs'] = result.data
    s['admission_date'] = '11/01/2026'
    return s


def med(s, name='ceftriaxone', destination='Infectious Disease', dose='100 mg', frequency='q24h'):
    rules = upsert_rule([], name, destination)
    result = parse_medications('Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n' +
        '\u2022\t' + name + '\t' + dose + '\tIntravenous\t' + frequency + '\tTest provider\t \t ', rules, [])
    assert not result.error
    s['medications'] += result.rows
    return result.rows[0]


def keys(s):
    return {r['key'] for r in suggestions(s, NOW)}


@pytest.mark.parametrize('code', ['LACWB','LACTATE','LAC','LACTATEVEN','LACTATEART','lac','Lactic Acid'])
def test_all_lactate_aliases_recent_and_code_free(code):
    s = sheet(f'{code}\t1.2 mmol/L\t11/08/2026 13:00\n{code}\t9.7\t11/06/2026 13:00')
    before = deepcopy(s)
    text = lactate_summary(s, NOW)
    assert '1.2 mmol/L' in text and '9.7' not in text
    assert code not in text if code != 'Lactic Acid' else 'Lactic Acid' not in text
    assert s == before


@pytest.mark.parametrize('key', ['LACTATE','THEOPH','CK'])
@pytest.mark.parametrize('date,included', [('11/07/2026 14:59',False),('11/07/2026 15:00',True),
    ('11/08/2026 14:59',True),('11/08/2026 15:00',True),('11/08/2026 15:01',False),
    ('11/06/2026',False),('11/07/2026',True),('11/08/2026',True),('11/09/2026',False)])
def test_24_hour_inclusive_boundary_and_future(key,date,included):
    assert bool(rows_for(sheet(f'{key}\t1.2\t{date}'),key,NOW)) == included


def test_previous_day_overlap_keeps_date_without_extra_printed_annotation():
    s = sheet('LACTATE\t1.2\t11/07/2026\nTHEOPH\t10.7\t11/07/2026\nCK\t135\t11/07/2026')
    assert '24h unverified' not in lactate_summary(s,NOW)
    assert '24h unverified' not in theophylline_summary(s,NOW)
    assert '24h timing unverified' not in laboratory_data(s,NOW)['rows'][-1]['value']
    assert 'unverified' not in str(s['labs'])


def test_exact_earliest_latest_across_codes_without_mutating_units():
    s = sheet('LACTATEART\t1.1 mmol/L\t11/08/2026 14:00\nLAC\t2.2 mmol/L\t11/07/2026 15:01\nLACWB\t3.3\t11/01/2026')
    output = lactate_summary(s,NOW)
    assert output == 'Lactate 2.2 mmol/L -> 1.1 mmol/L [11/8/2026]'
    assert all(x not in output for x in ['LACTATEART','LACWB','3.3'])


@pytest.mark.parametrize('value',['Pending','Canceled','IMPROPERLY COLLECTED','Not done','--','12 <script>x()</script>'])
@pytest.mark.parametrize('key',['LACTATE','THEOPH','CK','NTPROBNP','CRP','PROCAL'])
def test_unmeasured_rows_remain_in_editor_not_selected(value,key):
    s = sheet(f'{key}\t{value}\t11/08/2026')
    assert rows_for(s,key,NOW) == []
    assert s['labs']['rows'][0]['value'] == value


@pytest.mark.parametrize('key',['CRP','PROCAL'])
@pytest.mark.parametrize('date,include',[('10/31/2026',False),('11/01/2026',True),('11/08/2026',True),('11/09/2026',False)])
def test_admission_window(key,date,include):
    assert bool(rows_for(sheet(f'{key}\t2.4 (H)\t{date}'),key,NOW)) == include


def test_missing_admission_is_not_assumed_for_id_results():
    s=sheet('CRP\t2.4\t11/08/2026\nPROCAL\t3.4\t11/08/2026');s['admission_date']=''
    text=id_summary(s,NOW)
    assert 'admission date needed' in text and '2.4' not in text and '3.4' not in text


def test_natriuretic_latest_all_supplied_dates_is_only_in_cv():
    s=sheet('NTPROBNP\t401 (H)\t07/02/2026\nNT-PROBNP\t503 (H)\t08/02/2026\nCK\t206\t11/08/2026')
    assert 'NT-proBNP: 503 (H)' in cardiac_labs_summary(s,NOW)
    assert all(analyte(r['component']) != 'NTPROBNP' for r in laboratory_data(s,NOW)['rows'])
    with display_clock(NOW):
        from models import fields_with_medications
        f=fields_with_medications(s)
        assert '503' in f['Cardiovascular'] and '503' not in f['Lab Results / Trends']
        assert 'CK' in f['Lab Results / Trends'] and '206' in f['Lab Results / Trends']


def test_no_ck_mb_conflation():
    s=sheet('CK-MB\t5.5\t10/01/2026\nCK\t206\t10/01/2026')
    data=laboratory_data(s,NOW)
    assert [r['component'] for r in data['rows']] == ['CK-MB']


def test_failed_g_and_n_do_not_reinterpret_stale_levels():
    from import_review import diagnostic
    s=sheet('LACTATE\t1.2\t11/08/2026\nCRP\t2.4\t11/08/2026')
    s['import_warnings']['g']=[diagnostic('g','section_parse_failed')]
    assert not lactate_summary(s,NOW) and not id_summary(s,NOW)
    s['import_warnings']={'n':[diagnostic('n','section_parse_failed')]}
    assert 'admission date needed' in id_summary(s,NOW)


def test_zero_retained_and_outdated_levels_expire_without_deleting():
    s=sheet('LACTATE\t0\t11/08/2026 14:00')
    assert 'Lactate 0 [' in lactate_summary(s,NOW)
    assert not lactate_summary(s,datetime(2026,11,10,20,tzinfo=timezone.utc))
    assert len(s['labs']['rows'])==1


def test_clock_context_reset_and_timezone_requirement():
    with pytest.raises(ValueError): clock(datetime(2026,11,8))
    with display_clock(NOW):
        assert clock().hour==15
        with display_clock(datetime(2026,11,9,20,tzinfo=timezone.utc)):
            assert clock().day==9
        assert clock().day==8


def test_dst_window_uses_elapsed_time_not_calendar_days():
    # Fall-back day is 25 hours long. Cutoff at 15:00 EST is 16:00 EDT yesterday.
    now=datetime(2026,11,1,20,tzinfo=timezone.utc)
    s=sheet('CK\t101\t10/31/2026 15:30\nCK\t102\t10/31/2026 16:01')
    assert [r['value'] for r in rows_for(s,'CK',now)]==['102']


def test_source_diagnoses_never_changed_by_suggestions():
    s=sheet('K\t2.9 (L)\t11/08/2026')
    s['fields']['Diagnoses']='Synthetic baseline condition'
    med(s)
    before=deepcopy(s)
    assert {'K','sepsis'} <= keys(s)
    text=review_text(s,NOW)
    assert 'Sepsis' in text and 'Possible' not in text and 'Review for:' not in text
    assert s==before


@pytest.mark.parametrize('code',['NA','K','ALBUMIN','CO2','MG','PHOS','HGB','PLT'])
@pytest.mark.parametrize('flag',['(L)','(LL)','(LOW)'])
def test_each_requested_low_rule_from_explicit_source_flag(code,flag):
    s=sheet(f'{code}\t1.8 {flag}\t11/08/2026')
    assert code in keys(s)


@pytest.mark.parametrize('code',['NA','K','ALBUMIN','CO2','MG','PHOS','HGB','PLT'])
@pytest.mark.parametrize('suffix',['',' (H)','*',' (A)'])
def test_no_low_inference_from_undirected_abnormal_or_high(code,suffix):
    assert code not in keys(sheet(f'{code}\t1.8{suffix}\t11/08/2026'))


def test_latest_normal_suppresses_previous_low():
    s=sheet('K\t4.2\t11/08/2026\nK\t2.8 (L)\t11/07/2026')
    assert 'K' not in keys(s)


def test_latest_unusable_not_backfilled_into_low_diagnosis():
    s=sheet('K\tHemolyzed\t11/08/2026\nK\t2.8 (L)\t11/07/2026')
    assert 'K' not in keys(s)


def test_preadmission_or_future_or_excluded_lows_do_not_trigger():
    s=sheet('K\t2.8 (L)\t10/31/2026\nNA\t120 (L)\t11/09/2026\nMG\t1.1 (L)\t11/08/2026')
    s['labs']['rows'][2]['include']=False
    assert not keys(s)


@pytest.mark.parametrize('new,old,dates,expected', [
 ('0.31','0.20',('11/08/2026','11/07/2026'),True),
 ('0.30','0.20',('11/08/2026','11/07/2026'),False),
 ('0.18 (L)','0.28',('11/08/2026','11/07/2026'),False),
 ('0.4','0.2',('11/08/2026','10/30/2026'),False),
 ('0.4','0.2',('11/08/2026','11/08/2026'),False),
 ('0.4','0.2',('11/08/2026 13:00','11/08/2026 12:00'),True),
 ('0.4','0',('11/08/2026','11/07/2026'),False),
 ('0.4','<0.2',('11/08/2026','11/07/2026'),False),
 ('0.4 mg/dL','0.2 mg/dL',('11/08/2026','11/07/2026'),True),
 ('0.4 mg/dL','0.2 umol/L',('11/08/2026','11/07/2026'),False)])
def test_renal_rise_direction_interval_units_and_qualifiers(new,old,dates,expected):
    s=sheet(f'CREATININE\t{new}\t{dates[0]}\nCREATININE\t{old}\t{dates[1]}')
    assert ('aki' in keys(s)) == expected


@pytest.mark.parametrize('attribute,value',[('hidden',True),('include',False),('name','[Held by provider] ceftriaxone'),
 ('name','[START ON 11/10/2026] ceftriaxone'),('name','ceftriaxone - ADS Override Pull')])
def test_inactive_or_excluded_medications_do_not_prompt(attribute,value):
    s=sheet();row=med(s);row[attribute]=value
    assert 'sepsis' not in keys(s)


def test_mapped_medication_is_only_review_prompt_not_automatic_diagnosis():
    s=sheet();med(s)
    item=suggestions(s,NOW)[0]
    assert item['status']=='review'
    assert 'does not establish' in item['caution']
    assert s['fields']['Diagnoses']==''


def test_bowel_medication_prompt_is_not_constipation_diagnosis():
    s=sheet();med(s,'polyethylene glycol','FEN / GI',dose='4 g')
    item=suggestions(s,NOW)[0]
    assert item['key']=='constipation' and 'preventive' in item['caution']


@pytest.mark.parametrize('device',['HFNC','CPAP','BiPAP','Nasal cannula'])
def test_support_is_prompt_with_limitations(device):
    s=sheet();s['noninvasive']=[{'device':device,'values':{},'flow_inferred':False,'pressure_inferred':False}]
    item=suggestions(s,NOW)[0]
    assert item['key']=='respiratory' and item['status']=='review'
    assert 'airway protection' in item['caution']


def test_review_decision_fingerprint_invalidates_when_evidence_changes():
    s=sheet('K\t2.8 (L)\t11/08/2026 14:00')
    row=suggestions(s,NOW)[0]
    s=set_decision(s,'K',row['fingerprint'],'confirmed','Hypokalemia')
    assert suggestions(s,NOW)[0]['status']=='confirmed'
    s['labs']['rows'][0]['value']='2.5 (L)'
    assert suggestions(s,NOW)[0]['status']=='review'


def test_medication_dose_change_invalidates_sepsis_review():
    s=sheet();med(s)
    row=suggestions(s,NOW)[0]
    s=set_decision(s,'sepsis',row['fingerprint'],'confirmed','Sepsis review complete')
    s['medications'][0]['dose']='200 mg'
    assert suggestions(s,NOW)[0]['status']=='review'


def test_dismiss_then_restore_and_hide_print_only():
    s=sheet('K\t2.8 (L)\t11/08/2026')
    item=suggestions(s,NOW)[0]
    s=set_decision(s,'K',item['fingerprint'],'dismissed','Hypokalemia')
    assert review_text(s,NOW)=='' and len(suggestions(s,NOW))==1
    s=set_decision(s,'K',item['fingerprint'],'review','Hypokalemia')
    assert review_text(s,NOW) == 'Hypokalemia'
    s['problem_review']['enabled']=False
    assert review_text(s,NOW)=='' and len(suggestions(s,NOW))==1


def test_user_cutoff_requires_explicit_matching_units_and_is_patient_specific():
    s=sheet('HGB\t8.5* g/dL\t11/08/2026')
    # Source parser permits arbitrary value text, use the usual unit-before-flag form.
    s['labs']['rows'][0]['value']='8.5 g/dL (A)'
    s['problem_review']=empty_review()
    s['problem_review']['low_limits']['HGB']={'value':'9','unit':'g/dL'}
    assert 'HGB' in keys(s)
    other=sheet('HGB\t8.5 g/dL (A)\t11/08/2026')
    assert 'HGB' not in keys(other)
    s['problem_review']['low_limits']['HGB']['unit']='g/L'
    assert 'HGB' not in keys(s)
    s['labs']['rows'][0]['value']='8.5*'
    assert 'HGB' not in keys(s)


@pytest.mark.parametrize('value',['','-1','0','nan','inf','7.8 (L)','9,0','9 mg/dL'])
def test_invalid_custom_cutoffs_rejected(value):
    d=empty_review();d['low_limits']['HGB']={'value':value,'unit':'g/dL'}
    with pytest.raises(ValueError): validate_review(d)


def test_review_settings_round_trip_and_schema23_migration_keep_all_old_data():
    s=sheet('K\t2.8 (L)\t11/08/2026');i=suggestions(s,NOW)[0]
    s=set_decision(s,'K',i['fingerprint'],'confirmed','Hypokalemia')
    v=save_sheet_in(new_vault(),s);key=generate_key()
    assert open_vault(seal_vault(v,key),key)==v
    old=deepcopy(v);old['schema']=23;old['rooms']['P4102'].pop('problem_review')
    before=deepcopy(old);updated=upgrade_vault(old)
    assert old==before and updated['rooms']==old['rooms'] and updated['settings']==old['settings']
    assert updated['schema']==32


def test_all_formats_keep_review_separate_and_do_not_mutate():
    s=sheet('K\t2.8 (L)\t11/08/2026 14:00\nCK\t173\t11/08/2026 14:00\nNTPROBNP\t421\t10/01/2026')
    before=deepcopy(s)
    for fn in (handoff_text,handoff_html,handoff_pdf):
        result=fn(s,printed_at=NOW)
        if isinstance(result,bytes):
            result='\n'.join(x.extract_text() for x in PdfReader(BytesIO(result)).pages)
        assert 'Problems:' in result
        assert 'Hypokalemia' in result and 'Review for:' not in result and 'Not added' not in result
        assert 'NT-proBNP' in result and '421' in result and '173' in result
    assert s==before


def test_render_uses_requested_clock_not_latest_lab_date():
    s=sheet('THEOPH\t12.4\t11/05/2026 12:00')
    assert 'Theophylline level' not in handoff_text(s,printed_at=NOW)
    early=datetime(2026,11,5,20,tzinfo=timezone.utc)
    assert 'Theophylline level' in handoff_text(s,printed_at=early)


def test_bsa_source_spelling_from_epic():
    assert clean_field('bsa','0.31 meters squared.')=='0.31 m²'
    assert clean_field('bsa','0.31 square metres')=='0.31 m²'
    with pytest.raises(ValueError): clean_field('bsa','0.31 m/kg2')

# Streamlit callback simulations use the same stub as the existing suite.
from test_callbacks import app, open_room
from test_ui_smoke import equip


def _open_review_room(app):
    open_room(app)
    s=sheet('K\t2.9 (L)\t11/08/2026 14:00')
    app.st.session_state['drafts']['P4102']=s
    return s


def test_review_editor_renders_and_visit_alone_does_not_dirty(app,monkeypatch):
    s=_open_review_room(app)
    equip(app,monkeypatch)
    with display_clock(NOW):
        app.problem_review_editor(s)
        snap=app.editor_snapshot('P4102')
    assert snap==s and 'problem_review' not in s


def test_review_callback_saves_and_room_switch_persists(app):
    s=_open_review_room(app);ss=app.st.session_state
    with display_clock(NOW):
        item=suggestions(s)[0]
        ss['choice']='confirmed';ss['wording']='Hypokalemia, reviewed'
        app.problem_decision_change('P4102','K',item['fingerprint'],'choice','wording')
        open_room(app,'P4104')
    saved=ss['vault']['rooms']['P4102']
    assert saved['problem_review']['decisions']['K']['status']=='confirmed'
    assert saved['fields']['Diagnoses']==s['fields']['Diagnoses']


def test_stale_review_callback_cannot_confirm_new_evidence(app):
    s=_open_review_room(app);ss=app.st.session_state
    with display_clock(NOW):
        item=suggestions(s)[0]
        ss['drafts']['P4102']['labs']['rows'][0]['value']='2.7 (L)'
        ss['choice']='confirmed';ss['wording']='Hypokalemia'
        app.problem_decision_change('P4102','K',item['fingerprint'],'choice','wording')
    assert 'problem_review' not in ss['drafts']['P4102']
    assert ss['notice'][0]=='warning'


def test_pending_problem_widgets_captured_by_editor_snapshot(app):
    s=_open_review_room(app);ss=app.st.session_state
    with display_clock(NOW):
        item=suggestions(s)[0]
        prefix='problem_'+s['id']+'_K_'+item['fingerprint'][:12]
        ss[prefix+'_text']='Low potassium, reviewed'
        ss[prefix+'_status']='dismissed'
        snap=app.editor_snapshot('P4102')
    assert snap['problem_review']['decisions']['K']['status']=='dismissed'
    assert 'problem_review' not in s


def test_pending_lab_change_does_not_reuse_old_confirmation_widget(app):
    s=_open_review_room(app);ss=app.st.session_state
    with display_clock(NOW):
        item=suggestions(s)[0]
        prefix='problem_'+s['id']+'_K_'+item['fingerprint'][:12]
        ss[prefix+'_text']='Hypokalemia';ss[prefix+'_status']='confirmed'
        ss['lab_'+s['labs']['rows'][0]['id']+'_value']='2.6 (L)'
        snap=app.editor_snapshot('P4102')
    assert suggestions(snap,NOW)[0]['status']=='review'


def test_invalid_review_wording_never_overwrites_draft(app):
    s=_open_review_room(app);ss=app.st.session_state
    with display_clock(NOW):
        item=suggestions(s)[0]
        ss['choice']='confirmed';ss['wording']=''
        app.problem_decision_change('P4102','K',item['fingerprint'],'choice','wording')
    assert ss['drafts']['P4102']==s and ss['notice'][0]=='error'
    assert ss['wording']=='Hypokalemia' and ss['choice']=='review'


def test_hide_band_callback_does_not_remove_clinical_data(app):
    s=_open_review_room(app);ss=app.st.session_state
    ss['show_problem']=False
    app.problem_display_change('P4102','show_problem')
    current=ss['drafts']['P4102']
    assert current['problem_review']['enabled'] is False
    assert current['labs']==s['labs'] and review_text(current,NOW)==''


def test_limits_callback_rejects_missing_units_and_does_not_cross_rooms(app):
    s=_open_review_room(app);ss=app.st.session_state
    prefix='problem_limit_'+s['id']+'_'
    ss[prefix+'HGB_value']='9'
    app.save_problem_limits('P4102',prefix)
    assert ss['notice'][0]=='error' and 'problem_review' not in ss['drafts']['P4102']
    ss[prefix+'HGB_unit']='g/dL'
    app.save_problem_limits('P4102',prefix)
    assert ss['drafts']['P4102']['problem_review']['low_limits']['HGB']=={'value':'9','unit':'g/dL'}
    with display_clock(NOW): open_room(app,'P4104')
    before=deepcopy(ss['drafts']['P4104'])
    app.save_problem_limits('P4102',prefix)
    assert ss['drafts']['P4104']==before


def test_q_asterisk_counts_use_configured_defaults_and_allow_override():
    s=sheet()
    data=parse_cbc('Results from last 7 days\nLab\tUnits\t11/08/26\n1300\nWBC AUTO\tK/uL\t5.5\nHEMOGLOBIN\tg/dL\t8.5*\nHEMATOCRIT\t%\t26*\nPLATELETS AUTO\tK/uL\t90*')
    assert not data.error
    s['cbc']=data.data
    assert {'HGB','PLT'} <= keys(s)
    s['problem_review']=empty_review()
    s['problem_review']['low_limits']={'HGB':{'value':'9','unit':'g/dL'},'PLT':{'value':'100','unit':'K/uL'}}
    assert {'HGB','PLT'} <= keys(s)


def test_custom_problem_wording_is_escaped_in_html():
    s=sheet('K\t2.9 (L)\t11/08/2026')
    item=suggestions(s,NOW)[0]
    s=set_decision(s,'K',item['fingerprint'],'confirmed','Hypokalemia <script>alert(1)</script>')
    html=handoff_html(s,printed_at=NOW)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
