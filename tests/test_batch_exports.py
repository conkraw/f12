from copy import deepcopy
import pytest
from models import new_sheet,new_vault,save_sheet_in,apply_ventilation,apply_medications
from batching import available_handoffs
from exports import handoffs_pdf,handoffs_html
from medications import parse_medications,remap,upsert_rule
from ventilation import parse_ventilation


def filled(room, text):
    s=new_sheet(room)
    s['fields']['Diagnoses']=text
    return s


def test_batch_includes_saved_and_latest_drafts_without_duplicate_rooms():
    saved=filled('P4102','OLDTOKEN')
    v=save_sheet_in(new_vault(),saved)
    v=save_sheet_in(v,filled('4201','SAVEDTOKEN'))
    draft=deepcopy(saved)
    draft['fields']['Diagnoses']='NEWTOKEN'
    ready=available_handoffs(v,{'P4102':draft,'P4104':filled('P4104','DRAFTTOKEN')})
    assert list(ready)==['P4102','P4104','P4201']
    assert ready['P4102']['fields']['Diagnoses']=='NEWTOKEN'
    assert v['rooms']['P4102']['fields']['Diagnoses']=='OLDTOKEN'


def test_blank_draft_suppresses_old_saved_occupant_from_packet():
    v=save_sheet_in(new_vault(),filled('P4102','OLD_OCCUPANT'))
    assert not available_handoffs(v,{'P4102':new_sheet('P4102')})


def test_batch_pdf_new_page_per_room_and_exact_orientation():
    fitz=pytest.importorskip('fitz')
    sheets=[filled('P4102','FIRSTONE'),filled('P4104','SECONDONE')]
    doc=fitz.open(stream=handoffs_pdf(sheets),filetype='pdf')
    assert len(doc)==2
    for page in doc: assert page.rect.width==792 and page.rect.height==612
    assert 'FIRSTONE' in doc[0].get_text() and 'SECONDONE' not in doc[0].get_text()
    assert 'SECONDONE' in doc[1].get_text() and 'FIRSTONE' not in doc[1].get_text()


def test_long_first_room_finishes_before_next_room():
    fitz=pytest.importorskip('fitz')
    first=filled('P4102','FIRST_ROOM')
    first['fields']['Neurologic']='\n'.join(f'UNIQUE{i:04}' for i in range(120))
    second=filled('P4104','SECOND_ROOM')
    doc=fitz.open(stream=handoffs_pdf([first,second]),filetype='pdf')
    assert len(doc)>2
    text=' '.join(p.get_text() for p in doc)
    for i in range(120): assert text.count(f'UNIQUE{i:04}')==1
    assert 'SECOND_ROOM' in doc[-1].get_text()
    assert all('SECOND_ROOM' not in p.get_text() for p in list(doc)[:-1])


def test_vent_before_respiratory_meds_in_pdf():
    fitz=pytest.importorskip('fitz')
    s=filled('P4102','SYNTHETIC')
    s=apply_ventilation(s,parse_ventilation('Invasive Ventilation:\nVent Mode: Volume Targeted Pressure Control - PS\nResp Rate (Set): 16\nFiO2 (%): 35 %').data)
    rows=parse_medications('Medications:\n• albuterol\t2.5 mg\tNebulization\tq4h').rows
    s=apply_medications(s,remap(rows,upsert_rule([],'albuterol','Respiratory')))
    doc=fitz.open(stream=handoffs_pdf([s]),filetype='pdf')
    text=doc[0].get_text()
    assert text.index('Mode:')<text.index('Set RR:')<text.index('FiO2')<text.index('-----', text.index('FiO2'))<text.index('albuterol')


def test_print_html_has_two_pages_and_button_with_escaped_clinical_text():
    html=handoffs_html([filled('P4102','<script>bad()</script>'),filled('P4104','SECOND')])
    assert html.count('<main>')==2
    assert 'break-after:page' in html and 'window.print()' in html
    assert '<script>bad' not in html and '&lt;script&gt;' in html


@pytest.mark.parametrize('sheets',[[],[new_sheet('P4102'),new_sheet('P4102')]])
def test_empty_or_duplicate_packet_is_rejected(sheets):
    with pytest.raises(ValueError):handoffs_pdf(sheets)
    with pytest.raises(ValueError):handoffs_html(sheets)
