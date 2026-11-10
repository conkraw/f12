"""6.54 synthetic regressions: style, source flags, rule prompts and routing."""
from copy import deepcopy
from datetime import datetime
from html import unescape
from io import BytesIO
import re
import pytest
from pypdf import PdfReader

from clinical_style import HIGH_COLOR, LOW_COLOR, clinical_markup, clinical_runs, value_markup, value_runs
from exports import handoff_html, handoff_pdf, handoff_text
from models import new_sheet, new_vault, validate_sheet, upgrade_vault, SCHEMA_VERSION
from importing import import_sections
from labs import parse_labs
from lab_windows import display_clock, EASTERN
from lab_layout import laboratory_html, horizontal_card_markup, styled_runs, draw_styled_text
from medication_groups import group_for
from fen_gi import group_for as gi_group, effective_section
from categories import catalog, placement, apply_category_rules, set_category_rule
from problem_review import suggestions, set_decision, review_text
from security import generate_key, seal_vault, open_vault
from test_rooms_infusions import med

NOW = datetime(2026, 11, 9, 16, 0, tzinfo=EASTERN)

def block(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24

def imported(source):
    result = import_sections(new_sheet('P4102'), source, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet

def lab_sheet(rows):
    sheet = new_sheet('P4102')
    sheet['admission_date'] = '11/01/2026'
    parsed = parse_labs('LABS:\nComponent\tValue\tDate\n' + rows)
    assert not parsed.error, parsed.error
    sheet['labs'] = parsed.data
    return sheet

def keys(sheet):
    return {row['key'] for row in suggestions(sheet, NOW)}

def plain(html):
    return unescape(re.sub(r'<[^>]*>', '', html))

@pytest.mark.parametrize('label', [
    'SBS', 'SBS target', 'CAPD', 'WAT', 'WAT-1', 'WAT-1 total score (0-12)',
    'Target Arousal Level (SBS)', 'Resp', 'Respiratory Rate', 'RR', 'FiO2 (%)', 'FiO2',
    'SpO2', 'Pulse Ox', 'ETCO2', 'ETCO2 (mmHg)', 'VP', 'Heart Rate', 'BP', 'CVP',
    'CVP (mean)', 'Temp', 'ICP', 'CPP', 'MCV', 'ALC', 'ANC', 'Ca', 'Phos', 'Mg',
    'MAP', 'MAP (mmHg)', 'Mean arterial pressure', 'Arterial Line BP', 'Central venous pressure',
    'Pulse rate', 'Systolic', 'Diastolic', 'SBP', 'DBP', 'PAP', 'Oxygen saturation', 'Tmax',
])
def test_labels_bold_to_colon_values_regular(label):
    assert clinical_markup(label + ': 0') == '<b>' + label + ':</b> 0'
    assert clinical_markup(label + ': None') == '<b>' + label + ':</b> None'

@pytest.mark.parametrize('value,color', [
    ('13 (H)', HIGH_COLOR), ('0.7 (HH)', HIGH_COLOR), ('8.5 (L)', LOW_COLOR),
    ('2.1 (LL)', LOW_COLOR), ('<0.2 (L)', LOW_COLOR), ('>100 (H)', HIGH_COLOR),
    ('10.5*', HIGH_COLOR), ('10.5 *', HIGH_COLOR), ('-4 (L)', LOW_COLOR),
    ('0 (L)', LOW_COLOR), ('1,500 (H)', HIGH_COLOR), ('1.5 IU/mL (H)', HIGH_COLOR),
    ('7.1 mg/dL (L)', LOW_COLOR), ('13 (high)', HIGH_COLOR), ('1 (low)', LOW_COLOR),
])
def test_flagged_value_color_and_exact_text_preservation(value, color):
    out = value_markup(value)
    assert color in out
    assert plain(out) == value
    assert '<b>' not in out

@pytest.mark.parametrize('value', ['4.2', '100 %', '11/09/2026 12:30', '--', 'None', 'No results found', 'Z= 0.41)*'])
def test_unflagged_values_and_growth_footnote_not_colored(value):
    assert '<font' not in value_markup(value)
    assert plain(value_markup(value)) == value

def test_explicit_low_value_blue_asterisk_red_and_no_inference():
    runs = value_runs('3.1 (L)*')
    assert runs == [('3.1 (L)', LOW_COLOR), ('*', HIGH_COLOR)]
    assert ''.join(v for v, c in runs) == '3.1 (L)*'

def test_multiple_flags_do_not_color_neighbor_values_or_dates():
    out = clinical_markup('CRP: 1.3 (H) | PROCAL: 0.2 (L) [11/9/2026 12:30]')
    assert out.count(HIGH_COLOR) == 1 and out.count(LOW_COLOR) == 1
    assert '[11/9/2026 12:30]' in out and '<b>CRP:</b>' in out

def test_html_escape_and_multiline_labels_are_safe():
    out = clinical_markup('Temp: <script>alert(1)</script>\nSBS: -1\nA note at 12:30')
    assert '<script>' not in out and '&lt;script&gt;' in out
    assert '<b>SBS:</b> -1' in out
    assert '<b>A note' not in out

def test_inflammatory_heading_not_values_or_date_bold():
    out = clinical_markup('Inflammatory markers [11/9/2026]: CRP: 1 (H)')
    assert '<b>Inflammatory markers</b>' in out and '[11/9/2026]<b>:</b>' in out
    assert '<b>1' not in out

@pytest.mark.parametrize('name', ['micafungin IVPB', 'fluconazole in NS (Diflucan)', 'voriconazole tablet',
                                  'amphotericin B liposomal infusion', 'amphotericin B (Fungizone) irrigation'])
def test_antifungal_category(name):
    row = med(name, frequency='q24h')
    assert group_for(row) == 'antifungal'
    assert effective_section(row) == 'Infectious Disease'
    assert placement(row)['name'] == 'Antifungals'

@pytest.mark.parametrize('name', ['acyclovir IVPB', 'valacyclovir tablet', 'aciclovir injection', 'valaciclovir tablet'])
def test_antiviral_category(name):
    row = med(name, frequency='q8h')
    assert group_for(row) == 'antiviral'
    assert effective_section(row) == 'Infectious Disease'
    assert placement(row)['name'] == 'Antivirals'

@pytest.mark.parametrize('name', ['dextrose 50 % infusion', 'dextrose 50% infusion', 'DEXTROSE 50.0 % infusion',
                                  '[Held by provider] dextrose 50 % infusion'])
def test_d50_infusion_exact_group(name):
    row = med(name, dose='2.5 mL/hr', frequency='Continuous', rate='2.5 mL/hr')
    assert gi_group(row) == 'hypoglycemia'
    assert effective_section(row) == 'FEN / GI'
    assert placement(row)['name'] == 'Hypoglycemia:'

@pytest.mark.parametrize('name,frequency,route', [
    ('dextrose 5 % infusion', 'Continuous', 'Intravenous'),
    ('dextrose 10 % infusion', 'Continuous', 'Intravenous'),
    ('dextrose 5 % 50 mL infusion', 'Continuous', 'Intravenous'),
    ('milrinone in dextrose 50 % infusion', 'Continuous', 'Intravenous'),
    ('dextrose 50 % injection', 'Once', 'Intravenous'),
    ('dextrose 50 % injection', 'q1h PRN', 'Intravenous'),
    ('dextrose 50 % infusion', 'Continuous', 'Oral'),
])
def test_non_d50_or_noninfusion_not_miscategorized(name, frequency, route):
    assert gi_group(med(name, frequency=frequency, route=route)) != 'hypoglycemia'

def test_new_groups_respect_manual_overrides_and_hidden_orders():
    row = med('fluconazole tablet', frequency='Daily')
    sheet = new_sheet('P4102')
    settings = new_vault()['settings']
    settings = set_category_rule(settings, 'fluconazole', 'system:Other Medications')
    assigned = apply_category_rules([row], settings)[0]
    assert effective_section(assigned) == 'Other Medications'
    assigned['id'] = 'a'*32
    row['hidden'] = True
    sheet['medications'] = [row, assigned]
    html = handoff_html(sheet)
    assert html.count('fluconazole tablet') == 1
    assert '<b>Antifungals</b>' not in html

@pytest.mark.parametrize('component,key', [('CA','CALCIUM_HIGH'), ('CALCIUM','CALCIUM_HIGH'),
                                         ('PHOS','PHOS_HIGH'), ('INR','coagulopathy'),
                                         ('PT','coagulopathy'), ('PTT','coagulopathy'), ('APTT','coagulopathy')])
def test_latest_explicit_high_flags_trigger_requested_prompts(component,key):
    sheet=lab_sheet(component+'\t12 (H)\t11/09/2026')
    assert key in keys(sheet)
    before = deepcopy(sheet)
    with display_clock(NOW):
        handoff_html(sheet)
    assert sheet == before

@pytest.mark.parametrize('value', ['12', '12*', '12 (L)', '12 (H) (L)', '-1 (H)', 'pending', '12 pending (H)'])
@pytest.mark.parametrize('component,key', [('CA','CALCIUM_HIGH'),('PHOS','PHOS_HIGH'),('INR','coagulopathy')])
def test_colors_do_not_create_diagnoses_without_valid_high_flag(value,component,key):
    assert key not in keys(lab_sheet(component+'\t'+value+'\t11/09/2026'))

@pytest.mark.parametrize('component,key', [('CA','CALCIUM_HIGH'),('PHOS','PHOS_HIGH'),('INR','coagulopathy')])
def test_newer_normal_and_invalid_import_suppress_old_prompt(component,key):
    sheet = lab_sheet(component+'\t10\t11/09/2026\n'+component+'\t12 (H)\t11/08/2026')
    assert key not in keys(sheet)
    sheet['labs']['rows'][0]['value'] = '12 (H)'
    assert key in keys(sheet)
    sheet['import_warnings'] = {'g': 'Not updated'}
    assert key not in keys(sheet)

@pytest.mark.parametrize('component', ['FIB','HEPLMW','LABHEPA','ANTI-XA'])
def test_non_coagulation_time_high_alone_does_not_trigger_coagulopathy(component):
    assert 'coagulopathy' not in keys(lab_sheet(component+'\t12 (H)\t11/09/2026'))

def test_multiple_coags_one_prompt_and_dismissal_works():
    sheet = lab_sheet('PT\t16 (H)\t11/09/2026\nINR\t1.4 (H)\t11/09/2026\nPTT\t49 (H)\t11/09/2026')
    rows = [r for r in suggestions(sheet,NOW) if r['key']=='coagulopathy']
    assert len(rows)==1
    r = rows[0]
    sheet=set_decision(sheet,r['key'],r['fingerprint'],'dismissed',r['label'])
    assert 'Coagulopathy' not in review_text(sheet,NOW)


def test_labs_tree_and_inline_styling_keeps_values_regular():
    sheet=lab_sheet('NA\t133 (L)\t11/09/2026\nCA\t12 (H)\t11/09/2026\nMG\t1.4 (L)\t11/09/2026\nPHOS\t8 (H)\t11/09/2026\nWBC\t12\t11/09/2026\nHGB\t10.5*\t11/09/2026\nMCV\t78\t11/09/2026\nINR\t1.3 (H)\t11/09/2026')
    html=laboratory_html(sheet['labs'])
    assert 'font-weight="bold" fill="#000000">Ca:</tspan>' in html
    assert 'font-weight="bold" fill="#000000">Mg:</tspan>' in html
    assert 'font-weight="bold" fill="#000000">MCV:</tspan>' in html
    assert 'font-weight="normal" fill="'+LOW_COLOR+'">133 (L)' in html
    assert '<b>INR:</b> <font color="'+HIGH_COLOR+'">1.3 (H)</font>' in html

def test_pdf_vector_labels_bold_and_values_color_separate():
    class Canvas:
        def __init__(self): self.drawn=[]; self.font=''; self.color=None
        def setFillColor(self,c): self.color=c.hexval()
        def setFont(self,font,size): self.font=font
        def drawString(self,x,y,text): self.drawn.append((text,self.font,self.color))
    c=Canvas()
    draw_styled_text(c,0,10,'ANC: 1.0 (L) [11/9/2026]',6.5,'Times-Roman','left')
    assert c.drawn[0][:2]==('ANC:','Times-Bold')
    val=next(x for x in c.drawn if '(L)' in x[0])
    assert val[1]=='Times-Roman' and val[2].lower()=='0x125bba'

def test_complete_output_labels_intake_heading_pdf_and_source_unchanged():
    source='\n'.join([
        block('e','VITALS:\nTemp: 37 C\nHeart Rate: 99\nResp: 20\nBP: 100/60\nFiO2 (%): 30 %\nSpO2 Avg: 98 % Min: 95 % Max: 100 %\nLast SPO2: SpO2: 99 %'),
        block('k','SBS Last 24 Hours: SBS -1\nLast SBS Ever: SBS -2'),
        block('l','WAT Score:\nWAT-1 total score (0-12): 0'),block('y','CAPD: 2'),
        block('s','Intake/Output Summary (Last 24 hours) at 11/9/2026 1500\nLast data filed at 11/9/2026 1400\nGross per 24 hour\nIntake\t100 ml\nOutput\t80 ml\nNet\t20 ml')])
    s=imported(source); before=deepcopy(s)
    with display_clock(NOW):
        html=handoff_html(s,NOW)
        pdf=handoff_pdf(s,NOW)
    for label in ['CAPD','SBS','WAT-1 total score (0-12)','Resp','Temp','Heart Rate','BP','FiO2 (%)','SpO2']:
        assert '<b>'+label+':</b>' in html
    assert '<b>Intake/Output:</b>' in html
    reader=PdfReader(BytesIO(pdf))
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert 'Intake/Output:' in text and '100 ml' in text
    assert s==before


def test_schema32_catalog_migration_preserves_patient_data_custom_mapping_and_clock():
    vault=new_vault();vault['schema']=32
    old_categories=[c for c in catalog(vault['settings']) if c['id'] not in ('group:antifungal','group:antiviral','gi:hypoglycemia')]
    vault['settings']['medication_categories']=old_categories
    vault['settings']['medication_category_rules']=[]
    sheet=new_sheet('P4102');sheet['updated_at']='2026-11-09T15:00:00+00:00'
    sheet['fields']['Goals / Follow-up']='synthetic preserved note'
    vault['rooms']['P4102']=sheet
    before=deepcopy(vault)
    new=upgrade_vault(vault)
    assert vault==before and new['schema']==SCHEMA_VERSION==33
    assert new['rooms']==before['rooms']
    by_id={c['id']:c for c in new['settings']['medication_categories']}
    for c in old_categories: assert by_id[c['id']]==c
    for key in ['group:antifungal','group:antiviral','gi:hypoglycemia']: assert key in by_id
    key=generate_key()
    assert open_vault(seal_vault(new,key),key)==new
