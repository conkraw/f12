"""Landscape handoff with system columns, medication band, and bottom handoff rows.

Clinical content is escaped. PDF is generated in memory, without temporary files.
Long content continues onto additional landscape pages instead of being clipped.
"""
from __future__ import annotations
from html import escape
from io import BytesIO
from copy import deepcopy
from datetime import datetime
import time
import re
from import_review import review_summary
from models import SYSTEMS, fields_with_medications, validate_sheet, automatic_vitals, section_label, respiratory_text
from infusions import (neuro_body, cardiovascular_body, hematology_body, is_infusion, infusion_entry,
                       system_body_blocks, render_body_blocks, INFUSION_SECTIONS)
from lab_windows import cardiac_labs_summary, theophylline_summary, laboratory_data, stable_window_clock, clock as window_clock
from problem_review import review_text as problem_text, TITLE as PROBLEM_TITLE
from categories import theophylline_anchor, medication_blocks
from fen_gi import fen_gi_body
from feeds import feeds_for_output
from diet import diet_for_output, diet_failed
from devices import devices_text, devices_markup
from pacemaker import pacemaker_text
from lab_layout import laboratory_flowables, laboratory_html, LabRow
from cultures import cultures_text
from viral import viral_text
from microbiology_display import culture_markup, viral_markup
from print_time import eastern_print_time, PRINT_TIME_SCRIPT
from difficult_airway import airway_summary, TITLE as AIRWAY_TITLE
from clinical_style import clinical_markup as observation_markup
from save_status import handoff_save_caption

COLUMNS = (("PATIENT", None), ("NEURO", "Neurologic"), ("RESP", "Respiratory"),
           ("CARDIAC", "Cardiovascular"), ("FEN / GI", "FEN / GI"),
           ("HEME", "Hematology"), ("ID", "Infectious Disease"))
WIDTHS = (0.13, 0.16, 0.19, 0.14, 0.16, 0.11, 0.11)
BOTTOM = ("Other Medications", "Lab Results / Trends", "Goals / Follow-up")
ACCESS_FIELDS = ("Airway", "Last Intubation", "Access", "Drains / Tubes")



def display_fields(sheet: dict, include_lab_text: bool = True) -> dict:
    fields = fields_with_medications(sheet, include_lab_text=include_lab_text)
    # Do not lose a medication just because its old mapping used the removed column.
    extra_meds = render_body_blocks(medication_blocks("Labs", "", sheet["medications"]))
    if extra_meds:
        fields["Other Medications"] = "\n".join(v for v in (fields["Other Medications"], extra_meds) if v)
    fields["FEN / GI"] = fen_gi_body(sheet["fields"]["FEN / GI"], sheet["medications"], sheet["intake_output"],
        feeds=feeds_for_output(sheet), feeds_failed=False, diet=diet_for_output(sheet), diet_failed=False,
        dosing_weight=sheet["dosing_weight"] if "i" not in sheet["import_warnings"] else "", sheet=sheet)
    return fields

def patient_header(sheet: dict) -> str:
    attributes = sheet.get("anthropometrics", {})
    return "\n".join(("Room: " + sheet["room"],
                      "Age: " + (attributes.get("age") or "--"),
                      "Sex: " + (attributes.get("sex") or "--")))


@stable_window_clock
def handoff_text(sheet: dict, printed_at: datetime | None = None, *, save_statuses: dict | None = None) -> str:
    fields = display_fields(sheet)
    parts = ["Print prepared: " + eastern_print_time(printed_at), "PICU HANDOFF", patient_header(sheet), "Handoff reference: " + sheet["id"][:8],
             handoff_save_caption(sheet, (save_statuses or {}).get(sheet["room"])),
             "Confirm patient identity in Epic. A room is not a patient identifier."]
    if problem_text(sheet):
        parts.extend(["", PROBLEM_TITLE + ": " + problem_text(sheet)])
    for section in SYSTEMS:
        if section == "Labs":
            continue
        content = fields[section].strip()
        if content:
            parts.extend(["", section_label(section).upper(), content])
    if devices_text(sheet):
        parts.extend(["", "DEVICES", devices_text(sheet)])
    if airway_summary(sheet):
        parts.extend(["", AIRWAY_TITLE + ": " + airway_summary(sheet)])
    return "\n".join(parts) + "\n"


def patient_column(sheet: dict, fields: dict) -> str:
    lines = [patient_header(sheet)]
    if fields["Demographics / Weight"].strip():
        lines.append(fields["Demographics / Weight"].strip())
    if fields["Diagnoses"].strip():
        heading = "Diagnoses:\n" if sheet["fields"]["Diagnoses"].strip() else ""
        lines.append(heading + fields["Diagnoses"].strip())
    return "\n\n".join(lines)


def infusion_section_prefix(sheet: dict, section: str, has_body: bool) -> str:
    """The same vitals/support/lab lead-in for HTML and grouped PDF columns."""
    parts = [automatic_vitals(sheet).get(section, "")]
    trailing_support_separator = False
    if section == "Cardiovascular":
        parts.append(cardiac_labs_summary(sheet))
    elif section == "Respiratory":
        support = respiratory_text(sheet)
        level = "" if theophylline_anchor(sheet) else theophylline_summary(sheet)
        parts.extend((support, level))
        trailing_support_separator = bool(support and not level)
    prefix = "\n-----\n".join(v for v in parts if v.strip())
    if prefix and (has_body or trailing_support_separator):
        prefix += "\n-----" + ("\n" if has_body else "")
    return prefix


def field_markup(sheet: dict, fields: dict, section: str, esc=escape) -> str:
    """Escape source text while emphasizing generated headings, names and doses."""
    text = fields[section]
    if section == "FEN / GI":
        return fen_gi_body(sheet["fields"][section], sheet["medications"], sheet["intake_output"], True, esc, feeds=feeds_for_output(sheet), feeds_failed=False, diet=diet_for_output(sheet), diet_failed=False, dosing_weight=sheet["dosing_weight"] if "i" not in sheet["import_warnings"] else "", sheet=sheet)
    if section in INFUSION_SECTIONS:
        body = render_body_blocks(system_body_blocks(section, sheet["fields"][section], sheet["medications"], sheet), True, esc)
        prefix = observation_markup(infusion_section_prefix(sheet, section, bool(body.strip())), esc)
        if section == "Respiratory":
            prefix = re.sub(r"(?m)^Vent Settings$", "<b>Vent Settings</b>", prefix)
        pacing = pacemaker_text(sheet) if section == "Cardiovascular" else ""
        if pacing:
            prefix = prefix.replace(esc(pacing), "<b>" + esc(pacing) + "</b>", 1)
        return prefix + body
    if section == "Diagnoses":
        plain = viral_text(sheet["viral_panel"])
        if plain and text.endswith(plain):
            return observation_markup(text[:-len(plain)], esc) + viral_markup(sheet["viral_panel"], esc)
        return observation_markup(text, esc)
    if section == "Demographics / Weight":
        return observation_markup(text, esc)
    if section == "Infectious Disease":
        markup = observation_markup(text, esc)
        markup = re.sub(r"(?m)^Drug Levels$", "<b>Drug Levels</b>", markup)
        plain = "" if "f" in sheet["import_warnings"] else cultures_text(sheet["cultures"], empty_none=True)
        if plain:
            markup = markup.replace(esc(plain), culture_markup(sheet["cultures"], esc, empty_none=True), 1)
        blocks = medication_blocks(section, sheet["fields"][section], sheet["medications"], sheet)
        body = render_body_blocks(blocks)
        if body:
            markup = markup.replace(esc(body), render_body_blocks(blocks, True, esc), 1)
        return markup
    return esc(text)


def patient_markup(sheet: dict, fields: dict, esc=escape) -> str:
    lines = [observation_markup(patient_header(sheet), esc)]
    if fields["Demographics / Weight"].strip():
        lines.append(field_markup(sheet, fields, "Demographics / Weight", esc).strip())
    if fields["Diagnoses"].strip():
        heading = "Diagnoses:\n" if sheet["fields"]["Diagnoses"].strip() else ""
        lines.append(observation_markup(heading, esc) + field_markup(sheet, fields, "Diagnoses", esc).strip())
    return "\n\n".join(lines)


def _save_markup(sheet: dict, save_statuses: dict | None = None) -> str:
    text = handoff_save_caption(sheet, (save_statuses or {}).get(sheet["room"]))
    label, _, value = text.partition(":")
    return "<b>" + escape(label + ":") + "</b>" + escape(value)


@stable_window_clock
def handoff_html(sheet: dict, printed_at: datetime | None = None, *, save_statuses: dict | None = None) -> str:
    fields = display_fields(sheet, include_lab_text=False)
    headers = ''.join('<th>' + escape(label) + '</th>' for label, _ in COLUMNS)
    cells = ''.join('<td><div class="content">' + (patient_markup(sheet, fields) if section is None else field_markup(sheet, fields, section)) + '</div></td>' for _, section in COLUMNS)
    cols = ''.join(f'<col style="width:{w*100:.1f}%">' for w in WIDTHS)
    bands = []
    problems = problem_text(sheet, rich=True)
    if problems:
        bands.append('<div class="band problem-review"><strong>' + escape(PROBLEM_TITLE) +
                     ':</strong> <span class="content">' + problems + '</span></div>')
    for key in BOTTOM:
        lab_block = laboratory_html(laboratory_data(sheet), blood_gas=sheet['blood_gas'], cbc=sheet['cbc']) if key == 'Lab Results / Trends' else ''
        if key == 'Lab Results / Trends' and not lab_block and not fields[key].strip():
            continue
        heading = '' if key == 'Lab Results / Trends' else '<strong>' + escape(key) + ':</strong>'
        bands.append('<div class="band">' + heading + lab_block + '<span class="content">' + escape(fields[key]) + '</span></div>')
    extra = '\n'.join(k + ': ' + fields[k] for k in ('Skin / Wounds', 'Tasks', 'Other') if fields[k].strip())
    if extra:
        bands.insert(2, '<div class="band"><strong>Additional notes:</strong> <span class="content">' + escape(extra) + '</span></div>')
    device_summary = devices_markup(sheet, live_days=True)
    if device_summary:
        bands.append('<div class="band"><strong>Devices:</strong><div class="content">' + device_summary + '</div></div>')
    access = ''.join('<td><strong>' + escape(key) + ':</strong> <span class="content">' + escape(fields[key]) + '</span></td>' for key in ACCESS_FIELDS)
    access_table = ('<table class="access"><tbody><tr>' + access + '</tr></tbody></table>') if (not device_summary or any(fields[k].strip() for k in ACCESS_FIELDS)) else ''
    airway_band = ('<div class="band difficult-airway"><strong>' + AIRWAY_TITLE + ':</strong> ' + airway_summary(sheet, True) + '</div>') if airway_summary(sheet) else ''
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PICU handoff</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:18px;background:#eee;color:#111;font-family:"Times New Roman",serif}
main{width:11in;min-height:8.5in;margin:0 auto;background:white;padding:.25in}
.save-meta{font:10px Arial,sans-serif;margin-bottom:3px}
.meta{font:10px Arial,sans-serif;margin-bottom:5px;display:flex;justify-content:space-between}
table{border-collapse:collapse;width:100%;table-layout:fixed}th{font-size:8pt;text-align:center;padding:2px;border-bottom:1px solid black}
.systems td{border:1px solid black;vertical-align:top;height:auto;min-height:0;padding:3px;font-size:8pt;line-height:1.14}
.import-review{font:bold 7pt/1.15 Arial,sans-serif;border:1px solid #222;padding:3px;margin-bottom:3px;overflow-wrap:anywhere}.content{white-space:pre-wrap;overflow-wrap:anywhere}.band{border:1px solid black;border-top:0;font-size:8pt;line-height:1.14;padding:3px;min-height:15px}
.difficult-airway{background:#fff0ed;border:2px solid #8b1e16;padding:4px 6px;font-size:8pt;break-inside:avoid}.difficult-airway>strong{font-family:Arial,sans-serif;color:#8b1e16}.problem-review{background:#fff4cf;border:1px solid #80611a}.access{font-size:8pt}.access td{vertical-align:top;border:1px solid black;border-top:0;padding:3px;overflow-wrap:anywhere}
.labcards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:3px;align-items:start}.labcard{width:100%;height:auto;border:1px solid #888;break-inside:avoid}.labnote{font:6.1pt/1.15 "Times New Roman",serif;margin:1px 0}.lab-summary{font:8pt/1.14 "Times New Roman",serif;overflow-wrap:anywhere;margin:1px 0}.lab-full{grid-column:1/-1}
footer{font:6.1pt/1.2 Arial,sans-serif;margin-top:4px}
@page{size:letter landscape;margin:.25in}
@media print{body{margin:0;padding:0;background:white}main{width:100%;min-height:0;padding:0;margin:0}.systems td{height:auto}thead{display:table-header-group}footer{font-size:6.1pt}.band{break-inside:auto}}
</style></head><body><main><div class="meta"><span><span data-print-label>Print prepared: </span><span data-print-time>''' + escape(eastern_print_time(printed_at)) + '''</span> | Room ''' + escape(sheet['room']) + '''</span><span>Reference ''' + escape(sheet['id'][:8]) + ' | PICU HANDOFF' + '</span></div>' + '<div class="save-meta">' + _save_markup(sheet, save_statuses) + '</div>' + '''
<table class="systems"><colgroup>''' + cols + '</colgroup><thead><tr>' + headers + '</tr></thead><tbody><tr>' + cells + '</tr></tbody></table>' + ''.join(bands) + access_table + airway_band + '''
<footer>Confirm the current patient in Epic. Blank sections are not confirmed normal. Downloaded copies are not encrypted. Infusion rates reflect the source Last Rate, not a live feed. Lab windows evaluated: ''' + escape(eastern_print_time(window_clock())) + '''. Download again to refresh filtered results.</footer>
</main>''' + PRINT_TIME_SCRIPT + '</body></html>'


def _pdf_text(text: str) -> str:
    """Helvetica covers Latin-1. Normalize common clinical symbols explicitly."""
    for a, b in {'\u00a0':' ', '₂':'2', '₃':'3', '₄':'4', '⁺':'+', '⁻':'-', '−':'-', '–':'-', '—':'-', 'μ':'µ', '→':' -> ', '≤':'<=', '≥':'>=', '•':''}.items():
        text = text.replace(a, b)
    return text


@stable_window_clock
def handoffs_pdf(sheets: list[dict], printed_at: datetime | None = None, *, target_pages: int = 1, save_statuses: dict | None = None) -> bytes:
    """One landscape document. Each room starts on a new page, in memory only."""
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas
    if not sheets or len(sheets) > 100:
        raise ValueError("Select between 1 and 100 handoffs to print.")
    for sheet in sheets:
        validate_sheet(sheet)
    if len({s["room"] for s in sheets}) != len(sheets):
        raise ValueError("A room cannot be included twice in one print packet.")
    output = BytesIO()
    width, height = landscape(letter)
    c = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    c.setTitle("PICU handoffs")
    c.setAuthor("")
    stamp = eastern_print_time(printed_at)
    for position, sheet in enumerate(sheets, 1):
        _draw_sheet(c, sheet, width, height, position, len(sheets), stamp, target_pages=target_pages, save_status=(save_statuses or {}).get(sheet["room"]))
    c.save()
    return output.getvalue()


@stable_window_clock
def handoff_pdf(sheet: dict, printed_at: datetime | None = None, *, target_pages: int = 1, save_statuses: dict | None = None) -> bytes:
    return handoffs_pdf([sheet], printed_at, target_pages=target_pages, save_statuses=save_statuses)


# Print layout is independent of persisted handoff content or encryption schema.
# Clinical text may shrink only within this explicit, bounded range. Beyond it,
# pagination is used. Nothing is cropped or silently left out to force one page.
PRINT_FONT_SIZES = (8.0, 7.5, 7.2, 7.0, 6.8, 6.5)
PRINT_MARGIN = 18.0
BAND_LABEL_HEIGHT = 10.0
BAND_PADDING = 5.0


def _queue_height(queue, width: float) -> float:
    return sum(item.wrap(width, 100000)[1] for item in queue)


def _clinical_markup(text: str) -> str:
    value = escape(_pdf_text(text))
    # Keep short score/value pairs together at a line boundary. This changes
    # layout only, never the underlying score or stored text.
    if "Pacemaker:" in text:
        value = re.sub(r"(\d+(?:\.\d+)?)\s+bpm\b", r"\1&#160;bpm", value)
    return re.sub(r"\b(SBS|RASS)\s+([+-]?\d+(?:\.\d+)?)", r"\1&#160;\2", value)


def _make_pdf_plan(sheet: dict, page_width: float, font_size: float, *, tight: bool = False) -> dict:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer
    fields = display_fields(sheet, include_lab_text=False)
    total_width = page_width - 2 * PRINT_MARGIN
    widths = [total_width * value for value in WIDTHS]
    style = ParagraphStyle('compact-clinical', fontName='Times-Roman', fontSize=font_size,
                           leading=font_size + (0.25 if tight else 1), splitLongWords=True, spaceAfter=0,
                           allowWidows=1, allowOrphans=1)

    def paragraphs(text, rich=False):
        if not text.strip():
            return []
        return [Paragraph((line if rich else _clinical_markup(line)) if line else '&#160;', style)
                for line in text.split('\n')]

    columns = [paragraphs(patient_markup(sheet, fields, _clinical_markup) if section is None else field_markup(sheet, fields, section, _clinical_markup), rich=True)
               for _, section in COLUMNS]
    # Use the same grouping model as HTML/text. Keep each infusion's name and
    # ordered dose together, including the heading with the first infusion.
    class InfusionParagraph(Paragraph):
        def split(self, availWidth, availHeight):
            if self.height <= 200:
                return []
            return super().split(availWidth, availHeight)
    for column_index, (_, section) in enumerate(COLUMNS):
        if section not in INFUSION_SECTIONS:
            continue
        blocks = system_body_blocks(section, sheet["fields"][section], sheet["medications"], sheet)
        q = []
        prefix_text = infusion_section_prefix(sheet, section, bool(blocks)).rstrip("\n")
        if prefix_text:
            prefix_markup = observation_markup(prefix_text, _clinical_markup)
            if section == "Respiratory":
                prefix_markup = re.sub(r"(?m)^Vent Settings$", "<b>Vent Settings</b>", prefix_markup)
            pacing = pacemaker_text(sheet) if section == "Cardiovascular" else ""
            if pacing:
                prefix_markup = prefix_markup.replace(_clinical_markup(pacing), "<b>" + _clinical_markup(pacing) + "</b>", 1)
            q.extend(paragraphs(prefix_markup, rich=True))
        index = 0
        while index < len(blocks):
            kind, item = blocks[index]
            prefix = ""
            if kind in ("heading", "subheading"):
                next_index = index
                while next_index < len(blocks) and blocks[next_index][0] in ("heading", "subheading"):
                    next_index += 1
                if next_index < len(blocks) and blocks[next_index][0] == "infusion":
                    # Keep the group/subgroup labels with the first name/dose.
                    prefix = render_body_blocks(blocks[index:next_index], True, _clinical_markup) + "\n"
                    index = next_index
                    kind, item = blocks[index]
            if kind == "infusion":
                markup = prefix + infusion_entry(item, True, _clinical_markup, handoff_only=True)
                q.append(InfusionParagraph(markup.replace("\n", "<br/>"), style))
            else:
                q.extend(paragraphs(render_body_blocks([(kind, item)], True, _clinical_markup), rich=True))
            index += 1
        columns[column_index] = q
    band_items = [(name, fields[name]) for name in BOTTOM]
    extra = '\n'.join(name + ': ' + fields[name] for name in ('Skin / Wounds', 'Tasks', 'Other')
                      if fields[name].strip())
    if extra:
        band_items.insert(2, ('Additional notes', extra))
    bands = [(name, (laboratory_flowables(laboratory_data(sheet), total_width-6, font_size, blood_gas=sheet['blood_gas'], cbc=sheet['cbc'])
                    if name == 'Lab Results / Trends' else []) + paragraphs(text))
             for name, text in band_items]
    bands = [(name, items) for name, items in bands if name != 'Lab Results / Trends' or items]
    problems = problem_text(sheet, rich=True, esc=_clinical_markup)
    if problems:
        bands.insert(0, (PROBLEM_TITLE, paragraphs('<b>' + PROBLEM_TITLE + ':</b> ' + problems, rich=True)))
    device_summary = devices_markup(sheet, _clinical_markup)
    if device_summary:
        bands.append(('Devices', paragraphs(device_summary, rich=True)))
    access = [(name, paragraphs(fields[name])) for name in ACCESS_FIELDS]
    if device_summary and not any(fields[k].strip() for k in ACCESS_FIELDS):
        access = []
    # On-sheet import diagnostics are omitted. The app still displays and logs them.
    banner = None
    review_height = 0
    airway = airway_summary(sheet, True, _clinical_markup)
    if airway:
        # Put manual access notes before the final airway alert, without deleting them.
        if access:
            manual = " | ".join(name + ": " + fields[name] for name in ACCESS_FIELDS if fields[name].strip())
            if manual:
                bands.append(("Access / airway notes", paragraphs(manual)))
            access = []
        airway_style = ParagraphStyle('difficult-airway', parent=style, fontSize=max(font_size, 8),
                                      leading=max(font_size, 8) + 1)
        bands.append((AIRWAY_TITLE, [Paragraph('<b>' + AIRWAY_TITLE + ':</b> ' + airway, airway_style)]))
    return {'review_banner': banner, 'review_height': review_height,
            'font_size': font_size, 'leading': style.leading, 'width': total_width,
            'tight': tight, 'balanced': False, 'cell_padding': 2.0 if tight else 3.0,
            'band_label': 8.5 if tight else BAND_LABEL_HEIGHT,
            'band_padding': 3.5 if tight else BAND_PADDING,
            'empty_band': 10.0 if tight else 15.0,
            'access_min': 20.0 if tight else 24.0,
            'widths': widths, 'columns': columns, 'bands': bands, 'access': access}


def _plan_heights(plan: dict) -> tuple[float, list[float], float]:
    width = plan['width']
    pad = plan['cell_padding']
    main = max(20, max((_queue_height(q, w-2*pad) for q, w in zip(plan['columns'], plan['widths'])), default=0)+2*pad)
    bands = [max(plan['empty_band'], _queue_height(q, width-6) + (0 if label in (PROBLEM_TITLE, AIRWAY_TITLE, "Lab Results / Trends") else plan['band_label']) + plan['band_padding'])
             for label, q in plan['bands']]
    access = max(plan['access_min'], max((_queue_height(q, width/4-6) for _, q in plan['access']), default=0)+14) if plan['access'] else 0
    return main, bands, access


def _balanced_plan(plan: dict) -> dict:
    """Bounded column reallocation. Only widths change, never clinical content.

    Fit is measured by actual Paragraph.wrap calls. Preserve the column order,
    keep a useful minimum for headings, and never make a column wider than 25%.
    Widths are selected afresh per patient, not shared between patients.
    """
    total = plan['width']
    pad = plan['cell_padding']
    original = list(plan['widths'])
    from reportlab.pdfbase.pdfmetrics import stringWidth
    minima = [max(55.0, w * .72, stringWidth(label, 'Times-Bold', 8)+6)
              for w, (label, _) in zip(original, COLUMNS)]
    maxima = [min(total * .25, w * 1.75) for w in original]
    queues = plan['columns']
    cache = {}
    def height(i, w):
        key = (i, round(w, 3))
        if key not in cache:
            cache[key] = _queue_height(queues[i], w-2*pad)
        return cache[key]
    def required(target):
        widths = []
        for i, (low, high) in enumerate(zip(minima, maxima)):
            if height(i, high) > target + .01:
                return None
            if height(i, low) <= target + .01:
                widths.append(low)
                continue
            for _ in range(10):
                middle = (low + high) / 2
                if height(i, middle) <= target + .01:
                    high = middle
                else:
                    low = middle
            widths.append(high)
        return widths if sum(widths) <= total + .001 else None
    top = max((height(i, w) for i, w in enumerate(original)), default=0)
    lo, hi = 0., top
    best = original
    for _ in range(13):
        middle = (lo+hi)/2
        result = required(middle)
        if result is None:
            lo = middle
        else:
            best, hi = result, middle
    # Return surplus first to the original proportions, then evenly within caps.
    spare = total-sum(best)
    for bounds in (original, maxima):
        capacities = [max(0., limit-w) for limit, w in zip(bounds, best)]
        capacity = sum(capacities)
        if capacity and spare > 1e-6:
            used = min(spare, capacity)
            best = [w+used*c/capacity for w,c in zip(best, capacities)]
            spare -= used
    best[-1] += total-sum(best)
    # Never accept reallocation that increases the tallest column.
    if max((height(i, w) for i, w in enumerate(best)), default=0) < top - .01:
        plan['widths'] = best
        plan['balanced'] = True
    return plan


def _fits_one(plan: dict, height: float) -> bool:
    main, bands, access = _plan_heights(plan)
    available = height - 2*PRINT_MARGIN - 46 - plan['review_height']
    return main + sum(bands) + access <= available + .01


def _measure_pdf_plan(sheet: dict, plan: dict, width: float, height: float) -> int:
    from reportlab.pdfgen import canvas
    probe = canvas.Canvas(BytesIO(), pagesize=(width, height), pageCompression=1)
    return _draw_sheet(probe, sheet, width, height, print_stamp='01/01/2026 12:00:00 PM EST',
                       plan=deepcopy(plan))


def _select_pdf_plan(sheet: dict, width: float, height: float, target_pages: int = 1) -> tuple[dict, bool]:
    if type(target_pages) is not int or target_pages not in (1, 2):
        raise ValueError('Choose a one-page or two-page print target.')
    original = _make_pdf_plan(sheet, width, PRINT_FONT_SIZES[0])
    # Keep already-fitting sheets exactly as before. A two-page target allows
    # the largest existing print size when it already meets that target.
    baseline_pages = 1 if _fits_one(original, height) else _measure_pdf_plan(sheet, original, width, height)
    if baseline_pages <= target_pages:
        original['pages'] = baseline_pages
        original['target_pages'] = target_pages
        return original, baseline_pages == 1
    plans = [original]
    # Existing bounded font reduction is still tried first for one-page output.
    for size in PRINT_FONT_SIZES[1:]:
        plan = _make_pdf_plan(sheet, width, size)
        plans.append(plan)
        if _fits_one(plan, height):
            plan.update(pages=1, target_pages=target_pages)
            return plan, True
    # Then tighten layout, without reducing body text below 6.5 pt.
    for size in PRINT_FONT_SIZES:
        plan = _make_pdf_plan(sheet, width, size, tight=True)
        plans.append(plan)
        if _fits_one(plan, height):
            plan.update(pages=1, target_pages=target_pages)
            return plan, True
        balanced = _balanced_plan(_make_pdf_plan(sheet, width, size, tight=True))
        if balanced['balanced']:
            plans.append(balanced)
            if _fits_one(balanced, height):
                balanced.update(pages=1, target_pages=target_pages)
                return balanced, True
    # Count rendered continuation pages, not characters. If one page is not
    # possible, prefer the largest font that fits two. Never crop to the target.
    measured = []
    for plan in plans:
        pages = baseline_pages if plan is original else _measure_pdf_plan(sheet, plan, width, height)
        plan.update(pages=pages, target_pages=target_pages)
        measured.append(plan)
    best = min(measured, key=lambda p: (p['pages'], -p['font_size'], p['tight'], p['balanced']))
    return best, best['pages'] == 1


@stable_window_clock
def print_layout_info(sheet: dict) -> dict:
    """Legacy compact status. New UI uses the full render-verified report."""
    plan, fits = _select_pdf_plan(sheet, 792, 612)
    return {'font_size': plan['font_size'], 'fits_one_page': fits}


@stable_window_clock
def print_fit_report(sheet: dict, target_pages: int = 1) -> dict:
    """Private in-memory preflight using exactly the PDF renderer's layout."""
    validate_sheet(sheet)
    plan, fits = _select_pdf_plan(sheet, 792, 612, target_pages)
    pages = _measure_pdf_plan(sheet, plan, 792, 612)
    return {'page_count': pages, 'font_size': plan['font_size'],
            'fits_one_page': pages == 1, 'target_pages': target_pages,
            'target_met': pages <= target_pages,
            'tight_spacing': plan['tight'], 'balanced_columns': plan['balanced']}


def _draw_sheet(c, sheet: dict, width: float, height: float, position: int = 1, count: int = 1, print_stamp: str | None = None, *, target_pages: int = 1, plan: dict | None = None, save_status=None) -> int:
    print_stamp = print_stamp or eastern_print_time()
    if plan is None:
        plan, _ = _select_pdf_plan(sheet, width, height, target_pages)
    pad = plan["cell_padding"]
    label_height = plan["band_label"]
    band_padding = plan["band_padding"]
    margin = PRINT_MARGIN
    total_width = plan['width']
    widths = plan['widths']
    leading = plan['leading']
    queues, bands, access = plan['columns'], plan['bands'], plan['access']
    # Top of columns after the metadata and column headings.
    column_top = height-margin-28-plan['review_height']
    body_height = column_top-(margin+18)

    def draw_queue(queue, x, y, w, available):
        remaining = list(queue)
        while remaining and available > .01:
            item = remaining[0]
            _, h = item.wrap(w, available)
            if h <= available + .01:
                item.drawOn(c, x, y-h)
                y -= h
                available -= h
                remaining.pop(0)
                continue
            parts = item.split(w, available)
            if not parts:
                break
            first = parts[0]
            _, h = first.wrap(w, available)
            if h > available + .01 or h <= 0:
                break
            first.drawOn(c, x, y-h)
            y -= h
            available -= h
            remaining = parts[1:] + remaining[1:]
        return remaining

    def minimum_band(label, queue):
        if not queue:
            return plan['empty_band']
        local_label_height = 0 if label in (PROBLEM_TITLE, AIRWAY_TITLE, "Lab Results / Trends") else label_height
        minimum = local_label_height+band_padding+2*leading
        if label == AIRWAY_TITLE:
            return max(minimum, _queue_height(queue, total_width-6) + band_padding)
        # A fishbone row must fit intact. Reserve its preceding short note too,
        # so a large Other Medications band cannot starve the lab row forever.
        before = 0.0
        for item in queue:
            h = item.wrap(total_width-6, 100000)[1]
            if isinstance(item, LabRow):
                return min(195, max(minimum, before+h+local_label_height+band_padding))
            before += h
            if before > 30:
                break
        return minimum

    page = 0
    while True:
        page += 1
        if page > 150:
            raise ValueError('The handoff is too long to export safely. Shorten it or export text.')
        c.setFont('Helvetica', 7)
        c.drawString(margin, height-margin-5, 'Print prepared: ' + print_stamp + ' | Room ' + sheet['room'] + (' | Continued' if page > 1 else ''))
        c.drawRightString(width-margin, height-margin-5,
                         'Sheet ' + str(position) + '/' + str(count) + ' | Reference ' + sheet['id'][:8] + ' | Page ' + str(page))
        # The existing metadata gutter has room for this second line. Keep
        # body geometry unchanged so it does not reduce the clinical area.
        saved_label, _, saved_value = handoff_save_caption(sheet, save_status).partition(":")
        c.setFont('Helvetica-Bold', 7)
        c.drawString(margin, height-margin-15, saved_label + ':')
        label_width = c.stringWidth(saved_label + ':', 'Helvetica-Bold', 7)
        c.setFont('Helvetica', 7)
        c.drawString(margin+label_width, height-margin-15, saved_value)
        if plan['review_banner'] is not None:
            banner = plan['review_banner']
            _, bh = banner.wrap(total_width, 10000)
            banner.drawOn(c, margin, height-margin-11-bh)
        plan.update(columns=queues, bands=bands, access=access)
        main_need, band_needs, access_need = _plan_heights(plan)
        all_fit = main_need+sum(band_needs)+access_need <= body_height+.01
        if all_fit:
            access_height = access_need
            band_heights = band_needs
            # Use remaining space for the system columns, rather than imposing
            # an arbitrary minimum that would push otherwise-fitting labs out.
            main_height = body_height-sum(band_heights)-access_height
        else:
            access_height = min(54, access_need)
            minimums = [minimum_band(label, q) for label, q in bands]
            main_cap = max(24, body_height-access_height-sum(minimums))
            main_height = min(main_need, main_cap)
            remaining_height = body_height-main_height-access_height
            band_heights = []
            for index, wanted in enumerate(band_needs):
                later = sum(minimums[index+1:])
                allowed = max(minimums[index], remaining_height-later)
                actual = min(wanted, allowed)
                band_heights.append(actual)
                remaining_height -= actual

        y = column_top+12
        c.setLineWidth(.5)
        x = margin
        for (label, _), w in zip(COLUMNS, widths):
            c.setFont('Times-Bold', 8)
            c.drawCentredString(x+w/2, y-9, label)
            c.line(x, y-12, x+w, y-12)
            x += w
        y -= 12
        updated = []
        x = margin
        for w, q in zip(widths, queues):
            c.rect(x, y-main_height, w, main_height)
            updated.append(draw_queue(q, x+pad, y-pad, w-2*pad, main_height-2*pad))
            x += w
        queues = updated
        y -= main_height
        updated_bands = []
        for (label, queue), bh in zip(bands, band_heights):
            if label in (PROBLEM_TITLE, AIRWAY_TITLE):
                c.saveState()
                if label == AIRWAY_TITLE:
                    c.setFillColorRGB(1, .94, .92)
                else:
                    c.setFillColorRGB(1, .965, .86)
                c.rect(margin, y-bh, total_width, bh, fill=1, stroke=0)
                c.restoreState()
            c.rect(margin, y-bh, total_width, bh)
            local_label_height = 0 if label in (PROBLEM_TITLE, AIRWAY_TITLE, "Lab Results / Trends") else label_height
            if label not in (PROBLEM_TITLE, AIRWAY_TITLE, "Lab Results / Trends"):
                c.setFont('Times-Bold', 7.5)
                c.drawString(margin+3, y-8, label + (':' if page == 1 else ' (continued):'))
            rest = draw_queue(queue, margin+3, y-local_label_height-2,
                              total_width-6, bh-local_label_height-band_padding)
            if label not in (PROBLEM_TITLE, AIRWAY_TITLE, "Lab Results / Trends") or rest:
                updated_bands.append((label, rest))
            y -= bh
        bands = updated_bands
        aw = total_width/4
        updated_access = []
        for index, (label, queue) in enumerate(access):
            x = margin+index*aw
            c.rect(x, y-access_height, aw, access_height)
            c.setFont('Times-Bold', 7.5)
            c.drawString(x+3, y-8, label+':')
            rest = draw_queue(queue, x+3, y-11, aw-6, access_height-14)
            updated_access.append((label, rest))
        access = updated_access
        c.setFont('Helvetica', 6.1)
        c.drawString(margin, margin+6, 'Confirm the current patient in Epic. Blank sections are not confirmed normal. Downloaded copies are not encrypted.')
        c.drawRightString(width-margin, margin-2, 'Infusion rates are recorded values, not a live pump feed.')
        c.showPage()
        if not any(queues) and not any(q for _, q in bands) and not any(q for _, q in access):
            return page


@stable_window_clock
def handoffs_html(sheets: list[dict], printed_at: datetime | None = None, *, save_statuses: dict | None = None) -> str:
    if not sheets or len(sheets) > 100:
        raise ValueError("Select between 1 and 100 handoffs to print.")
    if len({s["room"] for s in sheets}) != len(sheets):
        raise ValueError("A room cannot be included twice in one print packet.")
    from datetime import timezone
    printed_at = printed_at or datetime.now(timezone.utc)
    docs = [handoff_html(sheet, printed_at, save_statuses=save_statuses) for sheet in sheets]
    head = docs[0].split("</head>", 1)[0]
    head += """<style>
main{margin-bottom:24px}.printbar{font:15px Arial,sans-serif;max-width:11in;margin:0 auto 18px}
.printbar button{padding:10px 16px;cursor:pointer}
@media print{.printbar{display:none}main{break-after:page;margin:0}main:last-child{break-after:auto}}
</style></head>"""
    pages = ["<main>" + doc.split("<main>", 1)[1].split("</main>", 1)[0] + "</main>" for doc in docs]
    return head + '<body><div class="printbar"><button onclick="window.print()">Print all handoffs</button> Landscape Letter. Each room starts on a new page.</div>' + "".join(pages) + PRINT_TIME_SCRIPT + "</body></html>"


def download_payload(sheets: list[dict], kind: str, expires_at: float | None = None, *, target_pages: int = 1, cancelled=None, save_statuses: dict | None = None):
    """Return a zero-argument generator for Streamlit >=1.52 downloads.

    A private snapshot is captured on render, not a shared cache. The timestamp
    is generated on the click, not when the UI was last opened. No Streamlit
    session data is accessed from the download worker thread.
    """
    if kind not in ("pdf", "html", "text"):
        raise ValueError("Unknown handoff download format.")
    if kind == "text" and len(sheets) != 1:
        raise ValueError("Text export expects one handoff.")
    snapshot = deepcopy(sheets)
    status_snapshot = deepcopy(save_statuses)
    for sheet in snapshot:
        validate_sheet(sheet)

    def generate():
        if cancelled is not None and cancelled.is_set():
            raise ValueError("This download was cleared. Prepare a new handoff download.")
        if expires_at is not None and time.monotonic() >= expires_at:
            raise ValueError("The session expired. Sign in and prepare a new download.")
        try:
            if kind == "pdf":
                return handoffs_pdf(snapshot, target_pages=target_pages, save_statuses=status_snapshot)
            if kind == "html":
                return handoffs_html(snapshot, save_statuses=status_snapshot).encode("utf-8")
            return handoff_text(snapshot[0], save_statuses=status_snapshot).encode("utf-8")
        except Exception:
            raise ValueError("The print file could not be generated. Refresh the app and try again.") from None
    return generate
