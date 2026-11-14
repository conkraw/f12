"""6.75: fixed 7am/7pm boundaries, snapshot compatibility and compact BM label."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
import fitz
import pytest
from bowel_movements import LABEL, bowel_movement_markup
from current_shift import current_shift_text, shift_window
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from importing import import_sections
from infusions import render_body_blocks
from models import new_sheet, new_vault, save_sheet_in
from security import generate_key, seal_vault, open_vault
from test_current_shift import source
from test_bowel_movements import med, wrap


@pytest.mark.parametrize('stamp,start,hours', [
    ('2026-11-14T06:30:00', '2026-11-13T19:00:00', '11.5'),
    ('2026-11-14T07:00:01', '2026-11-14T07:00:00', str(Decimal(1)/Decimal(3600))),
    ('2026-11-14T07:30:00', '2026-11-14T07:00:00', '.5'),
    ('2026-11-14T15:00:00', '2026-11-14T07:00:00', '8'),
    ('2026-11-14T17:12:00', '2026-11-14T07:00:00', '10.2'),
    ('2026-11-14T18:30:00', '2026-11-14T07:00:00', '11.5'),
    ('2026-11-14T19:00:01', '2026-11-14T19:00:00', str(Decimal(1)/Decimal(3600))),
    ('2026-11-14T19:30:00', '2026-11-14T19:00:00', '.5'),
    ('2026-11-14T23:00:00', '2026-11-14T19:00:00', '4'),
    ('2026-11-15T00:00:00', '2026-11-14T19:00:00', '5'),
    ('2026-11-15T06:30:00', '2026-11-14T19:00:00', '11.5'),
    ('2027-01-01T06:30:00', '2026-12-31T19:00:00', '11.5'),
    ('2028-03-01T06:30:00', '2028-02-29T19:00:00', '11.5'),
])
def test_corrected_starts_across_noon_midnight_and_calendar_boundaries(stamp,start,hours):
    begin, end, elapsed = shift_window(stamp)
    assert begin.isoformat() == start and end.isoformat() == stamp
    assert elapsed == Decimal(hours)


@pytest.mark.parametrize('hour', [7,19])
def test_only_7am_and_7pm_are_zero_duration_boundaries(hour):
    with pytest.raises(ValueError, match='start of a shift'):
        shift_window(f'2026-11-14T{hour:02d}:00:00')


def test_every_minute_uses_elapsed_time_not_fixed_twelve_hours():
    # One ordinary 24-hour day, with an independent minute-based oracle.
    for minute in range(24 * 60):
        if minute in (7*60, 19*60):
            continue
        stamp = f'2026-11-14T{minute//60:02d}:{minute%60:02d}:00'
        expected_minutes = (minute - 7*60) % (12*60)
        assert shift_window(stamp)[2] == Decimal(expected_minutes)/Decimal(60)


@pytest.mark.parametrize('stamp,weight,outputs,heading,rows', [
    ('2026-11-14T17:12:00','5.3',{'urine':'55','other':'88'},
     'Current Shift (7am - 5:12pm)', ['UOP: 1.02 mL/kg/hr','Other: 1.63 mL/kg/hr']),
    ('2026-11-14T06:30:00','20.3',{'urine':'276','drains':'15'},
     'Current Shift (7pm - 6:30am)', ['UOP: 1.18 mL/kg/hr','Drains: 0.06 mL/kg/hr']),
    ('2026-11-14T17:13:00','6',{'urine':'263','other':'51'},
     'Current Shift (7am - 5:13pm)', ['UOP: 4.29 mL/kg/hr','Other: 0.83 mL/kg/hr']),
    ('2026-11-14T17:08:00','3.8',{'urine':'43','chest_tube':'59'},
     'Current Shift (7am - 5:08pm)', ['UOP: 1.12 mL/kg/hr','Chest Tube: 1.53 mL/kg/hr']),
])
def test_independent_rate_examples(stamp,weight,outputs,heading,rows):
    sheet={'current_shift':{'as_of':stamp,'weight_kg':weight,'outputs':outputs}}
    assert current_shift_text(sheet) == heading + '\n' + '\n'.join(rows)


def test_existing_saved_snapshot_recalculates_without_repaste_or_mutation():
    # This exact persisted structure was used before 6.75. No rates were stored.
    sheet = new_sheet('P4102')
    sheet['current_shift'] = {'as_of':'2026-11-14T06:30:00','weight_kg':'20',
                             'outputs':{'urine':'300','drains':'15','chest_tube':'30','other':'60'}}
    sheet['bowel_movement'] = {'documented':True}
    key=generate_key()
    restored=open_vault(seal_vault(save_sheet_in(new_vault(),sheet),key),key)['rooms']['P4102']
    before=deepcopy(restored)
    for later in [datetime(2026,11,14,20,tzinfo=timezone.utc),datetime(2026,11,16,20,tzinfo=timezone.utc)]:
        text=handoff_text(restored,later)
        assert 'Current Shift (7pm - 6:30am)' in text and 'UOP: 1.30 mL/kg/hr' in text
        assert 'Last BM (24 Hours): Yes' in text
    assert restored == before


@pytest.mark.parametrize('status', ['Yes','No'])
def test_generated_label_only_is_bold_and_no_blank_line_is_added(status):
    blocks=[('heading','Bowel Regimen'),('observation',LABEL+' '+status)]
    assert render_body_blocks(blocks) == 'Bowel Regimen\n'+LABEL+' '+status
    assert render_body_blocks(blocks,True) == '<b>Bowel Regimen</b>\n<b>'+LABEL+'</b> '+status
    blocks=[('heading','Bowel Regimen\n\n'),('observation',LABEL+' '+status)]
    assert '\n\n' not in render_body_blocks(blocks)


def test_unknown_observations_still_escaped_without_style_inference():
    text='Last BM (24 Hours): <script>Yes</script>'
    assert bowel_movement_markup(text) == escape(text)
    assert render_body_blocks([('observation',text)],True) == escape(text)


@pytest.mark.parametrize('has_medication', [False,True])
@pytest.mark.parametrize('signal,status', [('Stool Amount: Large','Yes'),('','No')])
def test_no_gap_in_text_html_single_and_all_pdf(has_medication,signal,status):
    text=wrap('h',source())+'\n'+wrap('s','')+'\n'+wrap('ac',signal)
    result=import_sections(new_sheet('P4102'),text,new_vault()['settings'])
    assert not result.errors
    sheet=result.sheet
    if has_medication:
        sheet['medications']=[med('polyethylene glycol synthetic powder','8.5 g','Oral','Daily')]
    plain=handoff_text(sheet)
    bm=LABEL+' '+status
    preceding=plain[:plain.index(bm)].splitlines()[-1]
    assert preceding.strip() and preceding != '-----'
    assert ('polyethylene glycol' in preceding) if has_medication else ('Bowel Regimen' in preceding)
    markup=handoff_html(sheet)
    assert '<b>'+LABEL+'</b> '+status in markup
    for payload in [handoff_pdf(sheet),handoffs_pdf([sheet])]:
        doc=fitz.open(stream=payload,filetype='pdf')
        lines=[line for page in doc for block in page.get_text('dict')['blocks']
               if 'lines' in block for line in block['lines']]
        bm_lines=[line for line in lines if any('Last BM' in span['text'] for span in line['spans'])]
        assert len(bm_lines)==1
        bm_line=bm_lines[0]
        label_spans=[s for s in bm_line['spans'] if 'Last BM' in s['text']]
        value_spans=[s for s in bm_line['spans'] if status in s['text']]
        assert label_spans and all(s['flags'] & 16 for s in label_spans)
        assert value_spans and all(not s['flags'] & 16 for s in value_spans)
        # The previous line in this column must be only one normal line above.
        bx,by=label_spans[0]['origin']
        above=[line for line in lines if abs(line['spans'][0]['origin'][0]-bx)<1
               and line['spans'][0]['origin'][1]<by]
        previous=max(above,key=lambda line:line['spans'][0]['origin'][1])
        gap=by-previous['spans'][0]['origin'][1]
        assert gap <= label_spans[0]['size']+1.1
