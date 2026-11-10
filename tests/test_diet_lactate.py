from style_assert_helpers import without_style_tags
"""Diet and lactate additions, using synthetic source patterns and no patient text."""
from copy import deepcopy
from io import BytesIO
import json
import re
import pytest
from pypdf import PdfReader
from diet import parse_diet, validate_diet, diet_text, diet_for_output, summarize_order
from labs import parse_labs, lactate_text, lactate_endpoints, is_numeric_lactate, result_cards
from importing import import_sections
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, save_sheet_in, upgrade_vault, SCHEMA_VERSION
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf
from batching import available_handoffs
from security import generate_key, seal_vault, open_vault
from import_review import review_summary
from error_store import new_error_event
from test_callbacks import app, open_room
from test_ui_smoke import equip


def block(text, letter='x'):
    return letter*12+'\n'+text+'\n'+letter.upper()*12


def imported(text='Diet:\nAdult diet Regular: General starting at 01/02 0853', sheet=None):
    result=import_sections(sheet or new_sheet('P4102'),block(text),new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


@pytest.mark.parametrize('source,expected',[
 ('Adult diet Regular: General starting at 01/02 0853','Adult Regular'),
 ('Pediatric diet Regular: General starting at 01/02 0853','Peds Regular'),
 ('Pediatric diet Clear Liquid: General starting at 01/02 1030','Peds Clear Liquid'),
 ('NPO diet NPO except: No Exceptions: NPO starting at 01/02 0942','NPO'),
 ('NPO diet NPO except: Other (specify); Explanatory comment: except for medications (NJ): NPO starting at 01/02 1003','NPO except meds (NJ)'),
 ('Diet, tube feeding no tray Continuous; Gastrostomy tube; 30; Synthetic formula: Tube Feeding starting at 01/02 0922','Tube Feeding (no tray)'),
 ('Infant tube feeding Infant Tube Feeding; Breast Milk; Continuous Feeds; Nasoenteric (post-pyloric) tube; 24 hours; 20; Additives: Tube Feeding starting at 01/02 0852','Infant Tube Feeding'),
 ('NPO diet NPO except: Medications: NPO starting at 01/02 1200','NPO except meds'),
 ('NPO diet NPO except: Sips with meds [2]: NPO starting at 01/02 1200','NPO except Sips with meds'),
 ('Adult diet Full Liquid: General starting at 01/02 1200','Adult Full Liquid'),
 ('Adult diet Regular; Mildly thick liquids: General starting at 01/02 1200','Adult Regular; Mildly thick liquids'),
 ('Adult diet Renal; Sodium restricted 2 g: General starting at 01/02 1200','Adult Renal; Sodium restricted 2 g'),
 ('[START ON 01/03/2026] Adult diet Regular: General','[START ON 01/03/2026] Adult Regular'),
 ('[Held by provider] Pediatric diet Clear Liquid: General','[Held by provider] Peds Clear Liquid'),
 ('Adult diet Pureed: General','Adult Pureed'),
 ('Pediatric diet Mechanical Soft: General','Peds Mechanical Soft'),
 ('Diet: Clear Liquid','Clear Liquid'),
])
def test_supported_diet_summaries(source,expected):
    r=parse_diet('Diet:\nDiet Orders\n\t'+source)
    assert not r.error and not r.diagnostics
    assert diet_text(r.data)=='Diet: '+expected
    assert r.data['rows'][0]['source']==source

@pytest.mark.parametrize('line',[
 'Pediatric 2-in-1 PN (Continuous) at 10 mL/hr starting at 01/02 2100',
 'Adult 3-in-1 PN (Continuous)', 'Total parenteral nutrition', 'TPN at 10 mL/hr',
 'PPN', 'PN', 'Breast Milk (print labels) starting at 01/02 0215',
 'Breastmilk labels', 'Breast milk labels', 'Breast Milk (Print Labels)',
 'Nutrition consult', 'Dietitian consult', 'Calorie count',
 'fat emulsion fish oil/plant based (SMOFlipid)',
 '[REMOVED] Adult diet Regular', '[DISCONTINUED] NPO diet',
 'Discontinued: Pediatric diet Regular',
])
def test_ignored_items_never_create_diet(line):
    r=parse_diet('Diet:\n'+line)
    assert not r.error and not r.diagnostics and not r.data['rows']
    assert diet_text(r.data)==''


def test_pn_and_labels_do_not_hide_valid_npo():
    r=parse_diet('Diet Orders\nPediatric 2-in-1 PN at 10 mL/hr\nNPO diet NPO except: Medications: NPO\nBreast Milk (print labels)')
    assert diet_text(r.data)=='Diet: NPO except meds'

@pytest.mark.parametrize('empty',['','Diet:','Diet:\nDiet Orders','None','No diet orders','No data recorded'])
def test_empty_diet_clears_prior_data(empty):
    r=imported(empty,imported());assert r['diet']=={'rows':[]}
    assert 'Diet:' not in fields_with_medications(r)['FEN / GI']


def test_omitted_x_preserves_diet_and_source():
    s=imported();before=deepcopy(s['diet'])
    r=import_sections(s,block('Temp: 37 C\nHeart Rate: 80','e'),new_vault()['settings'])
    assert r.sheet['diet']==before


def test_multiple_distinct_diets_are_not_silently_overruled():
    s=imported('Diet:\nAdult diet Regular: General starting at 01/03 1300\nNPO diet NPO except: No Exceptions: NPO starting at 01/02 1200')
    text=fields_with_medications(s)['FEN / GI']
    assert 'Adult Regular' in text and 'NPO' in text
    assert s['import_warnings']['x'][0]['code']=='diet_multiple'
    assert 'Diet: review diet orders' in review_summary(s)


def test_duplicate_summary_is_not_printed_twice():
    r=parse_diet('Diet:\nAdult diet Regular: General starting at 01/02 1200\nAdult diet Regular: General starting at 01/03 1400')
    assert len(r.data['rows'])==1


def test_unknown_line_keeps_other_diet_and_generic_diagnostic():
    r=parse_diet('Diet:\nNPO\nUnrecognized source line with PRIVATE content')
    assert diet_text(r.data)=='Diet: NPO'
    assert 'PRIVATE' not in json.dumps(r.diagnostics)


def test_bad_boundary_skips_only_x_hides_old_diet_and_keeps_it_editable():
    before=imported();original=deepcopy(before)
    paste=block('Diagnoses:\n1. Synthetic diagnosis','a')+'\n'+'x'*12+'\nDiet:\nNPO'
    r=import_sections(before,paste,new_vault()['settings'])
    assert r.errors and r.skipped==['x'] and before==original
    assert r.sheet['fields']['Diagnoses']=='Synthetic diagnosis'
    assert r.sheet['diet']==before['diet'] and diet_for_output(r.sheet) is None
    assert 'Adult Regular' not in handoff_text(r.sheet)
    assert 'Not updated. Review needed.' not in handoff_text(r.sheet)
    assert r.sheet['import_warnings']['x']
    assert 'Adult Regular' not in json.dumps(new_error_event(r.diagnostics))
    fixed=imported('Diet:\nNPO',r.sheet)
    assert 'x' not in fixed['import_warnings'] and 'Diet: NPO' in handoff_text(fixed)


def test_x_does_not_replace_any_prior_section():
    before=new_sheet('P4102');before['fields']['FEN / GI']='Separate note'
    before['fields']['Labs']='Separate lab notes'
    before['fields']['Cardiovascular']='Separate CV note'
    after=imported(sheet=before)
    for k in before:
        if k not in ('diet','import_warnings'):
            assert after[k]==before[k]


def test_io_diet_feeds_meds_order_in_all_exports():
    from feeds import parse_feeds
    from fluid_balance import parse_balance
    from medications import parse_medications
    s=imported()
    s['intake_output']=parse_balance('Intake\t100 ml\nOutput\t90 ml\nNet\t10 ml').data
    s['feeds']=parse_feeds('Gastric Tube Nasojejunal-Tube Feeding: Example Formula\nGastric Tube Nasojejunal-Continuous Tube Feeding Ordered Rate mL/hr (not calculated): 20 mL').data
    s['medications']=parse_medications('Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n• pantoprazole injection\t10 mg\tIntravenous\tDaily\tSynthetic\t\t',[]).rows
    validate_sheet(s)
    for text in (handoff_text(s),handoff_html(s),PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()):
        assert text.index('Intake:')<text.index('Diet:')<text.index('Feeds:')<text.index('GI prophylaxis')
        assert 'Adult Regular' in text


def test_only_diet_handoff_is_in_print_all():
    s=imported('Diet:\nNPO')
    assert available_handoffs(new_vault(),{'P4102':s})=={'P4102':s}
    assert len(PdfReader(BytesIO(handoffs_pdf([s]))).pages)==1


def test_excluded_diet_does_not_print_but_source_is_retained():
    s=imported();source=deepcopy(s['diet']['rows'][0]);s['diet']['rows'][0]['include']=False
    for text in (handoff_html(s),handoff_text(s)):
        assert 'Adult Regular' not in text
    assert s['diet']['rows'][0]['source']==source['source']


def test_diet_markup_escapes_editable_text():
    s=imported();s['diet']['rows'][0]['text']='<script>alert(1)</script>'
    text=handoff_html(s)
    assert '<script>alert(1)</script>' not in text and '&lt;script&gt;' in text

@pytest.mark.parametrize('field,value',[('text',''),('text','a\nb'),('include','yes'),('source',''),('id','bad')])
def test_diet_validation_rejects_invalid_fields(field,value):
    data=imported()['diet'];data['rows'][0][field]=value
    with pytest.raises(ValueError):validate_diet(data)


def test_new_snapshot_roundtrips_with_existing_encryption():
    v=save_sheet_in(new_vault(),imported());key=generate_key()
    encrypted=seal_vault(v,key)
    assert b'Adult Regular' not in encrypted and open_vault(encrypted,key)==v


def test_schema21_migration_preserves_every_prior_field_and_generation():
    v=save_sheet_in(new_vault(),new_sheet('P4102'));v['schema']=21;v['rooms']['P4102'].pop('diet')
    v['reset_generation']='a'*32;v['rooms']['P4102']['fields']['FEN / GI']='Original note'
    before=deepcopy(v);new=upgrade_vault(v)
    assert v==before and new['schema']==SCHEMA_VERSION==33
    assert new['rooms']['P4102']==dict(before['rooms']['P4102'],diet=None)
    assert new['settings']==before['settings'] and new['reset_generation']==before['reset_generation']


def test_future_schema_or_bad_prior_structure_is_not_overwritten():
    v=new_vault();v['schema']=99
    with pytest.raises(ValueError):upgrade_vault(v)
    v=save_sheet_in(new_vault(),new_sheet('P4102'));v['schema']=21
    # Schema21 must not silently accept schema22 payloads.
    with pytest.raises(ValueError):upgrade_vault(v)


def test_diet_editor_and_callback(app,monkeypatch):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported();row=ss['drafts']['P4102']['diet']['rows'][0]
    equip(app,monkeypatch);app.diet_editor(ss['drafts']['P4102'])
    key='diet_'+row['id']+'_text';ss[key]='Peds Clear Liquid'
    app.diet_row_change('P4102',row['id'],'text',key)
    assert row['text']=='Peds Clear Liquid'
    ss[key]='';app.diet_row_change('P4102',row['id'],'text',key)
    assert row['text']=='Peds Clear Liquid' and ss[key]=='Peds Clear Liquid'


def test_diet_snapshot_captures_blurred_edit_before_save(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported();row=ss['drafts']['P4102']['diet']['rows'][0]
    key='diet_'+row['id']+'_text';ss[key]='NPO except meds'
    result=app.editor_snapshot('P4102')
    assert result['diet']['rows'][0]['text']=='NPO except meds'
    ss['room_choice']='P4104'
    app.open_room(None)
    assert ss['vault']['rooms']['P4102']['diet']['rows'][0]['text']=='NPO except meds'
    app.discard_editor_widget_values();assert key not in ss


def test_full_ui_render_with_diet(app,monkeypatch):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported();downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(b,bytes) and b.startswith(b'%PDF') for _,b in downloads)


def labs(text):return parse_labs('LABS:\nLab Results\nComponent\tValue\tDate\n'+text).data

@pytest.mark.parametrize('code',['LACWB','LAC','LACTATE','LACTATEVEN','LACTATEART','lacwb','Lactic Acid','LACT'])
def test_every_lactate_alias_routes_to_cv_only(code):
    s=new_sheet('P4102');s['labs']=labs(code+'\t2.3 (H)\t01/02/2026')
    original=deepcopy(s)
    f=fields_with_medications(s)
    assert 'Lactate 2.3 (H)' in f['Cardiovascular']
    assert '; '+code+']' not in f['Cardiovascular'] and code+':' not in f['Lab Results / Trends']
    assert not any(code.upper() in c['rows'] for c in result_cards(s['labs']))
    assert s==original


def test_lactate_endpoints_compete_across_codes_and_dates():
    d=labs('LACWB\t2\t01/02/2026\nLACTATE\t1\t01/03/2026\nLAC\t5 (H)\t01/01/2026\nLACTATEVEN\t0.9\t01/04/2026')
    earliest,latest,uncertain=lactate_endpoints(d)
    assert earliest['component']=='LAC' and latest['component']=='LACTATEVEN' and not uncertain
    text=lactate_text(d);assert 'Lactate earliest: 5 (H)' in text and 'Lactate latest: 0.9' in text
    assert 'LACWB' not in text


def test_lactate_uses_time_when_available_not_input_order():
    d=labs('LAC\t9\t01/03/2026 0900\nLACWB\t2\t01/03/2026 22:00\nLACTATE\t4\t01/03/2026 0500')
    first,last,ambiguous=lactate_endpoints(d)
    assert first['value']=='4' and last['value']=='2' and not ambiguous


def test_lactate_date_only_ties_are_explicitly_unverified():
    d=labs('LACWB\t1.2\t01/03/2026\nLACWB\t1.8\t01/03/2026')
    first,last,ambiguous=lactate_endpoints(d)
    assert first['value']=='1.8' and last['value']=='1.2' and ambiguous
    assert 'timing unverified' in lactate_text(d)

@pytest.mark.parametrize('value',['0','0.0','<0.5','>15','1.2 (H)','1.2 mmol/L (H)','12 mg/dL','2.3*','0.9 (L)'])
def test_numeric_values_and_supplied_units_retained(value):
    assert is_numeric_lactate(value)
    assert value in lactate_text(labs('LACWB\t'+value+'\t01/01/2026'))

@pytest.mark.parametrize('value',['IMPROPERLY COLLECTED (WRONG PRESERVATIVE)','Pending','Canceled','Hemolyzed','--','< >','2.3 | 4.5','Not done','6 samples'])
def test_invalid_lactate_is_not_used_as_a_level(value):
    d=labs('LACTATE\t'+value+'\t01/03/2026\nLACWB\t1.2\t01/02/2026')
    assert not is_numeric_lactate(value)
    assert value not in lactate_text(d) and '1.2' in lactate_text(d)
    assert d['rows'][0]['value']==value and d['rows'][0]['include']


def test_excluded_results_do_not_affect_endpoints():
    d=labs('LACTATEART\t9\t01/03/2026\nLACTATEVEN\t2\t01/02/2026\nLACWB\t4\t01/01/2026')
    d['rows'][0]['include']=False
    first,last,_=lactate_endpoints(d);assert first['value']=='4' and last['value']=='2'


def test_unknown_or_no_lactate_does_not_invent_result():
    for text in ['GLUCOSE\t90\t01/01/2026','LACTATE\tPending\t01/01/2026','']:
        assert lactate_text(labs(text))==''


def test_lactate_date_and_units_never_inferred():
    text=lactate_text(labs('LACWB\t1.2\t01/02/2026\nLAC\t2.4\t01/01/2026'))
    assert '01/01/2026' in text and '01/02/2026' in text
    assert 'mmol' not in text and '00:00' not in text


def test_lactate_exports_do_not_duplicate_lower_lab_panel():
    s=imported();s['labs']=labs('LACWB\t1.2\t01/03/2026\nLACTATEVEN\t5.6 (H)\t01/02/2026')
    before=deepcopy(s)
    for text in [handoff_text(s),without_style_tags(handoff_html(s)),PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()]:
        normalized = ' '.join(text.split())
        assert 'Lactate 5.6 (H)' in normalized and '1.2 [1/3/2026]' in normalized
        assert text.count('Lactate ')==1
    assert s==before


# v6.30: make time-window routing tests independent of the machine's clock.
from datetime import datetime, timezone
from lab_windows import display_clock
@pytest.fixture(autouse=True)
def fixed_routing_clock():
    with display_clock(datetime(2026,1,3,20,0,tzinfo=timezone.utc)):
        yield
