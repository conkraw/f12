from style_assert_helpers import without_style_tags
"""6.45 regression coverage with synthetic inputs, no live repository or patient data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from html import unescape
import re
import pytest
from pypdf import PdfReader
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, automatic_vitals, upgrade_vault, SCHEMA_VERSION
from importing import import_sections
from sbs import parse_sbs, latest_sbs, sbs_display_rows, validate_sbs, score
from icp_cpp import parse_icp_cpp, display_icp_cpp_rows
from categories import placement, catalog, default_categories, apply_category_rules, save_category, set_category_rule
from medication_groups import group_for
from fen_gi import effective_section
from lab_windows import display_clock, EASTERN, id_drug_levels, laboratory_data
from labs import parse_labs
from cultures import parse_cultures, cultures_text
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from batching import available_handoffs
from security import seal_vault, open_vault, generate_key
from test_rooms_infusions import med
from test_callbacks import app, open_room

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=EASTERN)
ICP = '''ICP Trends:
ICP Range: ICP Mean (mmHg)  Avg: 9.6 mmHg  Min: 1 mmHg  Max: 22 mmHg
Last ICP: ICP Mean (mmHg): 11 mmHg
CPP Range: CPP  Avg: 69.5 mmHg  Min: 31 mmHg  Max: 97 mmHg
Last CPP: CPP: 52 mmHg'''

def block(letter, content):
    return letter*24+'\n'+content+'\n'+letter*24

def imported(text, sheet=None, settings=None):
    r=import_sections(sheet or new_sheet('P4102'),text,settings or new_vault()['settings'])
    assert not r.errors,r.errors
    return r.sheet

def timestamp(delta=0):
    return (NOW+timedelta(hours=delta)).strftime('%m/%d/%Y %H:%M')

@pytest.mark.parametrize('variant', [
    ICP, ICP.replace('  ', '\t'), ICP.replace('  Avg:', '\nAvg:').replace('  Min:', '\nMin:').replace('  Max:', '\nMax:'),
    ICP.replace(':', '：'), ICP.replace('mmHg', 'mm Hg'), ICP.replace('ICP Mean (mmHg)  Avg:', 'ICP Mean (mmHg): Avg:'),
    ICP.replace('CPP  Avg:', 'CPP: Avg:'), ICP.replace('ICP Range: ', 'ICP Range:\n').replace('Last ICP: ', 'Last ICP:\n'),
])
def test_icp_exact_wrappers_and_wrapped_stats_import_to_output(variant):
    s=imported(block('m',variant));before=deepcopy(s)
    for output in [handoff_text(s,NOW),without_style_tags(handoff_html(s,NOW)),PdfReader(BytesIO(handoff_pdf(s,NOW))).pages[0].extract_text()]:
        assert 'ICP: 1-22 [11 mm Hg]' in output
        assert 'CPP: 31-97 [52 mm Hg]' in output
        assert 'Avg: 9.6' not in output
    assert s==before

@pytest.mark.parametrize('body,expect',[
 ('ICP Range: No data recorded\nLast ICP:\nCPP Range: No data recorded\nLast CPP:',''),
 ('ICP Range: ICP Mean (mmHg) Avg: 0 Min: 0 Max: 0\nLast ICP: 0','0-0 [0 mm Hg]'),
 ('CPP Range: CPP Avg: 60 Min: 40 Max: 80\nLast CPP:','40-80 mm Hg'),
 ('Last ICP: ICP Mean (mmHg): 0 mmHg','0 mm Hg'),
])
def test_icp_missing_and_zero(body,expect):
    parsed=parse_icp_cpp(body);assert not parsed.error
    out=display_icp_cpp_rows(parsed.rows)
    if expect:assert expect in '\n'.join(r['value'] for r in out)
    else:assert not out

@pytest.mark.parametrize('value',[-3,-2,-1,0,1,2])
def test_sbs_valid_scores_and_target_separation(value):
    source='Target Arousal Level:\nTarget Arousal Level (SBS): SBS -3\nLast SBS: SBS '+str(value)+' ['+timestamp(-1)+']'
    s=imported(block('k',source))
    with display_clock(NOW):
        assert automatic_vitals(s)['Neurologic'].startswith('SBS: '+str(value)+'\nCAPD: None')
    assert s['neuro_vitals']['k'][0]['value']=='SBS -3'

@pytest.mark.parametrize('source',[
 'SBS: -1 [11/09/2026 11:00]', 'Last SBS: State Behavioral Scale (SBS): SBS -1 at 11/09/26 1100',
 'Recorded SBS: -1 on 11/09/2026 11:00', '11/09/26 1100 SBS: -1',
 'SBS\n11/09/26 1100\n-1', 'SBS: -1\nRecorded at: 11/09/26 1100',
 'SBS score\t-1\t11/09/26 1100',
 'Date\tTime\tSBS\n11/09/26\t1100\t-1\n11/08/26\t1000\t1',
 'Date/Time\tSBS\n11/09/26 1100\t-1\n11/09/26 1000\t0',
 'Results from last 24 hours\nLab\tUnits\t11/09/26\n1100\t11/09/26\n1000\nSBS\t\t-1\t0',
])
def test_timestamped_sbs_formats(source):
    p=parse_sbs(source);assert not p.error
    latest=latest_sbs(p.data,NOW);assert latest and latest['value']=='-1'
    s=imported(block('k',source))
    assert sbs_display_rows(s,NOW)[0]['value']=='-1'

@pytest.mark.parametrize('hours,printed',[(-24,True),(-24.02,False),(0,True),(0.02,False),(-2,True),(-48,False)])
def test_sbs_strict_24h_and_no_future(hours,printed):
    data={'readings':[{'value':'0','recorded_at':timestamp(hours),'include':True}],'notes':[]}
    assert bool(latest_sbs(data,NOW))==printed

@pytest.mark.parametrize('source',[
 'Target Arousal Level:\nTarget Arousal Level (SBS): SBS -1',
 'Target Arousal Level:\nSBS -1',
 'SBS: -1', 'SBS: 0 [11/09/2026]',
 'Target Arousal Level:', '', 'SBS observations:\nNo data recorded',
])
def test_untimed_targets_never_become_current_sbs(source):
    p=parse_sbs(source);assert not p.error
    assert latest_sbs(p.data,NOW) is None
    s=imported(block('k',source))
    assert sbs_display_rows(s,NOW)==[]
    with display_clock(NOW): assert 'SBS:' not in fields_with_medications(s)['Neurologic']

@pytest.mark.parametrize('source',[
 'SBS: -4 [11/09/26 1100]', 'SBS: 3 [11/09/26 1100]', 'SBS: 1.5 [11/09/26 1100]',
 'SBS: -1 [11/09/26 25:00]', 'SBS: <script>-1</script> [11/09/26 1100]',
 'SBS: -1 [11/09/26 1100]\nSBS: 0 [11/09/26 1100]',
 'Lab\tUnits\t11/09/26\n1100\t11/08/26\n0800\nSBS\t\t-1',
])
def test_bad_sbs_does_not_block_other_import_or_refresh_old_reading(source):
    old=imported(block('k','SBS: -1 ['+timestamp(-2)+']'));before=deepcopy(old)
    r=import_sections(old,block('k',source)+'\n'+block('y','CAPD: 0'),new_vault()['settings'])
    assert r.errors and 'k' in r.skipped and old==before
    assert r.sheet['sbs_observations']==old['sbs_observations']
    assert sbs_display_rows(r.sheet,NOW)==[]
    assert 'CAPD: 0' in handoff_text(r.sheet,NOW)
    assert source not in str(r.diagnostics)


def test_sbs_unsorted_readings_select_latest_and_expire_after_save():
    s=imported(block('k','SBS: -1 ['+timestamp(-20)+']\nSBS: 0 ['+timestamp(-2)+']\nSBS: 2 ['+timestamp(-10)+']'))
    before=deepcopy(s)
    assert sbs_display_rows(s,NOW)[0]['value']=='0'
    assert sbs_display_rows(s,NOW+timedelta(hours=23))==[]
    assert s==before


def test_sbs_omitted_preserves_empty_k_clears_and_last_is_before_capd_wat():
    s=imported(block('k','SBS: 0 ['+timestamp(-1)+']')+'\n'+block('y','CAPD: 4')+'\n'+block('l','WAT Score:\nWAT-1 total score (0-12): 2'))
    s=imported(block('m',ICP),s)
    with display_clock(NOW):
        text=fields_with_medications(s)['Neurologic']
        assert text.index('SBS: 0')<text.index('CAPD: 4')<text.index('WAT-1')<text.index('ICP:')
    s=imported(block('k','Target Arousal Level:'),s)
    assert not sbs_display_rows(s,NOW)


def test_sbs_dst_ambiguous_time_is_not_guessed():
    data={'readings':[{'value':'0','recorded_at':'11/01/2026 01:30','include':True}],'notes':[]}
    assert latest_sbs(data,datetime(2026,11,1,4,tzinfo=EASTERN)) is None


@pytest.mark.parametrize('name',[
 'Pediatric 2-in-1 PN (Continuous)', 'Pediatric 2-in-1 PN (Continouous)',
 '[START ON 11/10/2026] Pediatric 2-in-1 PN (Continuous)',
 'fat emulsion fish oil/plant based (SMOFlipid) 20 % 10 g 50 mL bag',
 'SMOFLIPID 20 % infusion',
])
def test_tpn_defaults_single_location_and_infusion_emphasis(name):
    row=med(name,section='Other Medications',dose='200 mL',frequency='Continuous PN',rate='10 mL/hr')
    s=new_sheet('P4102');s['medications']=[row];before=deepcopy(s)
    f=fields_with_medications(s)
    assert placement(row)['name']=='TPN' and effective_section(row)=='FEN / GI'
    assert f['FEN / GI'].count(name)==1 and name not in f['Other Medications']
    assert '<b>TPN</b>' in handoff_html(s,NOW)
    assert '<b>'+name.replace('&','&amp;')+'</b>' in handoff_html(s,NOW)
    assert s==before

@pytest.mark.parametrize('name', ['aspirin chewable tablet 40.5 mg','cangrelor (Kengreal) infusion','[Held by provider] aspirin tablet 81 mg'])
def test_antiplatelets_separate_from_dvt(name):
    row=med(name,section='Other Medications')
    s=new_sheet('P4102');s['medications']=[row]
    f=fields_with_medications(s)['Hematology']
    assert placement(row)['name']=='Antiplatelet Therapy'
    assert f.count(name)==1 and 'DVT Prophylaxis: None' in f

@pytest.mark.parametrize('name', ['enoxaparin injection','heparin infusion'])
def test_dvt_stays_dvt(name):
    row=med(name,dose='10 Units/kg/hr',section='Other Medications')
    assert placement(row)['name']=='DVT Prophylaxis'

@pytest.mark.parametrize('name', ['cefepime','cefTRIAXone','amoxicillin','ampicillin-sulbactam','piperacillin-tazobactam','meropenem','vancomycin','sulfamethoxazole-trimethoprim','azithromycin','ceFAZolin'])
def test_known_antibiotics_group_once(name):
    r=med(name+' test',frequency='q8h',rate='');s=new_sheet('P4102');s['medications']=[r]
    assert placement(r)['name']=='Antibiotics' and effective_section(r)=='Infectious Disease'
    assert fields_with_medications(s)['Infectious Disease'].count(r['name'])==1

@pytest.mark.parametrize('name,route', [('erythromycin suspension','Oral'),('micafungin IVPB','Intravenous'),('fluconazole IVPB','Intravenous'),('gentamicin ophthalmic ointment','Ophthalmic'),('cefepime','Topical')])
def test_not_all_id_or_erythromycin_orders_are_auto_antibiotics(name,route):
    row=med(name,route=route,frequency='q12h')
    assert placement(row)['name']!='Antibiotics'


def test_explicit_custom_destination_hidden_orders_and_rates_preserved():
    settings=new_vault()['settings'];settings=save_category(settings,'Custom treatment','Neurologic',ident='custom:treatment')
    for name in ['aspirin','cangrelor','Pediatric 2-in-1 PN (Continuous)','cefepime']:
        row=med(name,frequency='Continuous PN');row['hidden']=True
        custom=set_category_rule(settings,name,'custom:treatment')
        mapped=apply_category_rules([row],custom)[0]
        assert placement(mapped)['name']=='Custom treatment'
        assert mapped['dose']==row['dose'] and mapped['last_rate']==row['last_rate'] and mapped['hidden']
        s=new_sheet('P4102');s['medications']=[mapped]
        assert name not in handoff_text(s,NOW)


def test_separate_pn_orders_not_silently_merged_or_filled():
    lines=['Medications:', 'Medication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin',
           '•\tPediatric 2-in-1 PN (Continuous)\t639 mL\tIntravenous\tContinuous PN\tExample clinician\t26.6 mL/hr at 11/09/26 0700\tRate Verify at 11/09/26 0700',
           '\tAnd',
           '•\tfat emulsion fish oil/plant based (SMOFlipid) 20 % bag\t2.5 g/kg\tIntravenous\tContinuous PN\tExample clinician\t4.2 mL/hr at 11/09/26 0700\tRate Verify at 11/09/26 0700',
           '•\tPediatric 2-in-1 PN (Continuous)\t639 mL\tIntravenous\tContinuous PN\tExample clinician\t \t ']
    s=imported(block('b','\n'.join(lines)))
    assert len(s['medications'])==3
    text=fields_with_medications(s)['FEN / GI']
    assert text.count('Pediatric 2-in-1 PN')==2 and '26.6 mL/hr' in text
    assert all(placement(r)['name']=='TPN' for r in s['medications'])

@pytest.mark.parametrize('component', ['VANCOTROUGH','vancotrough','Vancomycin trough','VANCOMYCIN, TROUGH'])
def test_vancomycin_latest_dated_level_only_in_id(component):
    s=new_sheet('P4102');s['labs']=parse_labs('LABS:\nComponent\tValue\tDate\n'+component+'\t8.9\t11/09/2026\n'+component+'\t10.8\t10/14/2026').data
    before=deepcopy(s)
    with display_clock(NOW):
        text=fields_with_medications(s)['Infectious Disease']
        assert 'Drug Levels\nVancomycin trough: 8.9 [11/09/2026]' in text
        assert '10.8' not in text and 'VANCOTROUGH' not in fields_with_medications(s)['Lab Results / Trends']
        assert '<b>Drug Levels</b>' in handoff_html(s,NOW)
    assert s==before


def test_old_vancomycin_date_is_stored_but_not_displayed_as_recent():
    s=new_sheet('P4102');s['labs']=parse_labs('Component\tValue\tDate\nVANCOTROUGH\t10.8\t10/14/2026').data
    assert not id_drug_levels(s,NOW)
    assert s['labs']['rows'][0]['value'] == '10.8'

@pytest.mark.parametrize('body', ['No results found for: "VANCOTROUGH"','Component\tValue\tDate\nVANCOTROUGH\tCanceled\t11/09/2026',''])
def test_missing_vancomycin_does_not_invent_drug_level(body):
    s=new_sheet('P4102');s['labs']=parse_labs(body).data
    assert not id_drug_levels(s,NOW)
    assert 'Drug Levels' not in handoff_text(s,NOW)


def test_cultures_empty_none_and_negative_not_none_with_bold_heading():
    s=imported(block('f','CULTURES:\nNo results found for the last 90 days.'))
    assert '<b>Cultures:</b> None' in handoff_html(s,NOW)
    s=imported(block('f','CULTURES:\nCollected\tSpecimen Info\tOrganism\n11/09/26\tBlood, Venous\tNo growth (Preliminary)'),s)
    html=handoff_html(s,NOW)
    assert '<b>Cultures</b>' in html and 'NGTD' in html and 'Cultures:</b> None' not in html


def test_positive_organism_bold_sensitivities_ignored_and_hidden_not_none():
    s=imported(block('f','CULTURES:\nCollected\tSpecimen Info\tOrganism\tDrug\n11/09/26\tBlood\tExample organism\tS'))
    html=handoff_html(s,NOW)
    assert '<b>Example organism</b>' in html
    s['cultures']['rows'][0]['include']=False
    assert 'Cultures: None' not in handoff_text(s,NOW)
    assert 'Example organism' not in handoff_text(s,NOW)


def test_failed_culture_import_does_not_print_none_or_retained_as_refreshed():
    old=imported(block('f','CULTURES:\nCollected\tSpecimen Info\tOrganism\n11/09/26\tBlood\tExample organism'))
    r=import_sections(old,block('f','CULTURES:\nmalformed record'),new_vault()['settings'])
    assert 'f' in r.skipped
    text=handoff_text(r.sheet,NOW)
    assert 'Cultures: None' not in text and 'Example organism' not in text
    assert r.sheet['cultures']==old['cultures']


def test_sbs_encrypted_roundtrip_batch_and_no_mutation():
    v=new_vault();s=imported(block('k','SBS: 0 ['+timestamp(-1)+']'));s['updated_at']='2026-11-09T16:01:00+00:00'
    v['rooms']['P4102']=s;key=generate_key();before=deepcopy(v)
    restored=open_vault(seal_vault(v,key),key)
    assert restored==v
    with display_clock(NOW):assert 'P4102' in available_handoffs(v,{})
    text='\n'.join(pg.extract_text() for pg in PdfReader(BytesIO(handoffs_pdf([s],NOW))).pages)
    assert 'SBS: 0' in text and v==before


def test_add_sbs_callback_and_room_guard(app):
    open_room(app);ss=app.st.session_state
    ss['test_score']='0';ss['test_time']=timestamp(-1)
    app.sbs_add_reading('P4102','test_score','test_time')
    s=ss['drafts']['P4102'];assert s['sbs_observations']['readings'][0]['value']=='0'
    before=deepcopy(s);ss['edit_sbs']='2'
    app.sbs_row_change('P4104',0,'value','edit_sbs')
    assert s==before
    app.sbs_row_change('P4102',0,'value','edit_sbs')
    assert ss['drafts']['P4102']['sbs_observations']['readings'][0]['value']=='2'


def test_new_groups_catalog_and_current_archive_validation():
    ids={r['id'] for r in default_categories()}
    assert {'group:antiplatelet','group:antibiotic','gi:tpn'}<=ids
    v=new_vault();assert upgrade_vault(v) is v and SCHEMA_VERSION==33
