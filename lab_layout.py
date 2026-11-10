"""Compact dated CBC/BMP fishbones and horizontal lab summaries for PDF/HTML.

All values are escaped for HTML and drawn as text in PDFs. Long/nonstandard
values use a full-text fallback rather than clipping or shortening results.
"""
from html import escape
from io import StringIO
from textwrap import wrap
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Paragraph
from reportlab.lib.styles import ParagraphStyle
from labs import result_cards, short_date, display_component, printable_source_notes

NOTE = ('Latest/preceding PER COMPONENT, not confirmed same-draw panels. Dates are shown beside each result. '
        'Same-date ties without collection times follow source order. -- = unavailable or omitted.')


def note_for(cbc: dict | None) -> str:
    if cbc is None:
        return NOTE + ' ANC/ALC are the latest absolute counts, with independent dates.'
    return ('CBC: two latest documented source columns; ANC/ALC are independent latest absolute counts. '
            'BMP: latest/preceding per component, not confirmed same-draw panels. -- = unavailable or omitted.')


def ascii_text(s: str) -> str:
    for a, b in {'₂':'2', '−':'-', '–':'-', '—':'-', '≤':'<=', '≥':'>=', 'μ':'u', 'µ':'u'}.items():
        s = s.replace(a, b)
    return s


def card_plan(card: dict, width: float) -> tuple[float, list]:
    """Return a small vector display list in bottom-origin coordinates."""
    scale = width / 180
    kind, rows = card['kind'], card['rows']
    plan = []
    def text(x,y,value,size=8,font='Times-Roman',align='left'):
        plan.append(('text', x*scale, y, ascii_text(value), size, font, align))
    def line(x1,y1,x2,y2):
        plan.append(('line', x1*scale,y1,x2*scale,y2))
    def node(key,x,y,maxw=48):
        row = rows.get(key)
        label = {'CREATININE':'Cr', 'GLUCOSE':'Glucose', 'NA':'Na', 'CL':'Cl', 'HGB':'Hgb', 'HCT':'Hct', 'PLT':'Plt'}.get(key,key)
        if key == 'HGB' and row and row.get('component') == 'Hgb (ISTAT)':
            label = 'Hgb (ISTAT)'
        text(x,y+8,label,6.1,'Times-Bold','center')
        text(x,y,row['value'] if row else '--',7.2,'Times-Roman','center')
        if row:
            stamp = short_date(row['date']).split(' ')
            text(x,y-8,stamp[0],6.1,'Times-Roman','center')
            if len(stamp) > 1:
                text(x,y-15,stamp[1],6.1,'Times-Roman','center')
    # If a cell cannot fit faithfully, use labelled branches below instead.
    if kind in ('cbc','bmp'):
        main = ('WBC','HGB','HCT','PLT') if kind == 'cbc' else ('NA','K','CL','CO2','BUN','CREATININE','GLUCOSE')
        for key in main:
            if key in rows and (stringWidth(ascii_text(rows[key]['value']),'Times-Roman',7.2) > 40*scale
                              or max(stringWidth(part,'Times-Roman',6.1) for part in short_date(rows[key]['date']).split(' '))>42*scale):
                kind = 'branch'
                break
    if kind == 'cbc':
        extras = [rows[k] for k in ('MCV','ANC','ALC','NEUTROABS','LYMPHSABS') if k in rows]
        height = 84 + len(extras)*8
        offset = len(extras)*8
        node('WBC',25,48+offset); node('HGB',90,66+offset,65)
        node('HCT',90,28+offset,65); node('PLT',155,48+offset)
        line(53,64+offset,66,48+offset); line(66,48+offset,53,32+offset)
        line(127,64+offset,114,48+offset); line(114,48+offset,127,32+offset)
        line(66,48+offset,114,48+offset)
        for i, row in enumerate(extras):
            short = row['component']
            value = short + ': ' + row['value'] + (' [' + short_date(row['date']) + ']' if row['date'] else '')
            text(6,6+8*(len(extras)-i-1),value,6.5)
    elif kind == 'bmp':
        extras = [rows[key] for key in ('CALCIUM', 'MG', 'PHOS') if key in rows]
        height = 84 + len(extras)*8
        offset = len(extras)*8
        for key,x,y in (('NA',22,66),('K',22,28),('CL',65,66),('CO2',65,28),('BUN',108,66),('CREATININE',108,28),('GLUCOSE',158,48)):
            node(key,x,y+offset)
        line(3,48+offset,137,48+offset)
        for x in (44,87):
            line(x,17+offset,x,77+offset)
        line(130,77+offset,140,48+offset);line(140,48+offset,130,17+offset)
        for index, row in enumerate(extras):
            from labs import canonical
            label = {'CALCIUM': 'Ca', 'MG': 'Mg', 'PHOS': 'Phos'}[canonical(row['component'])]
            text(6, 6+8*(len(extras)-index-1), label+': '+row['value']+' ['+short_date(row['date'])+']', 6.5)
    else:
        # Labelled branches for hepatic, coagulation, gases and other results.
        lines = []
        for row in rows.values():
            value = display_component(row['component']) + ': ' + row['value']
            chunks = wrap(ascii_text(value), max(18, int(width/4.2)), break_long_words=True, break_on_hyphens=False) or ['']
            lines.append((chunks, short_date(row['date']) if row['date'] else ''))
        height = 28 + sum(9*len(chunks)+11 for chunks,_ in lines)
        y = height-30
        line(5, y+4, 5, 11)
        for chunks, date in lines:
            line(5,y+2,10,y+2)
            for chunk in chunks:
                text(13,y,chunk,7.7); y-=9
            text(13,y,date,6.5); y-=11
    title, _, subtitle = card['title'].partition(' | ')
    if card['kind'] not in ('cbc', 'bmp'):
        text(6,height-10,title,8,'Times-Bold')
        text(6,height-19,subtitle,6.1)
    return height, plan


def tree_text_fits(card: dict, width: float) -> bool:
    """Reject a vector tree if any text would spill outside its allotted cell."""
    scale = width / 180
    keys = ('WBC','HGB','HCT','PLT') if card['kind']=='cbc' else ('NA','K','CL','CO2','BUN','CREATININE','GLUCOSE')
    extras = ('MCV','ANC','ALC','NEUTROABS','LYMPHSABS') if card['kind']=='cbc' else ('CALCIUM', 'MG', 'PHOS')
    for key in keys:
        row = card['rows'].get(key)
        if row and (stringWidth(ascii_text(row['value']), 'Times-Roman', 7.2) > 40*scale
                    or max(stringWidth(part, 'Times-Roman', 6.1) for part in short_date(row['date']).split(' ')) > 42*scale):
            return False
    for key in extras:
        row = card['rows'].get(key)
        if row:
            text = row['component'] + ': ' + row['value'] + (' [' + short_date(row['date']) + ']' if row['date'] else '')
            if stringWidth(ascii_text(text), 'Times-Roman', 6.5) > width-12:
                return False
    return True


class LabRow(Flowable):
    """Up to four dated cards in a single indivisible row."""
    def __init__(self, cards: list[dict], width: float):
        super().__init__()
        self.width=width
        self.cell_width=width/4
        self.cards=cards
        self.plans=[card_plan(card,self.cell_width-6) for card in cards]
        self.height=max((h for h,_ in self.plans),default=0)+6
    def wrap(self, availWidth, availHeight):
        return self.width,self.height
    def split(self, availWidth, availHeight):
        return []
    def draw(self):
        c=self.canv
        c.saveState(); c.setLineWidth(.45)
        for i,(height,plan) in enumerate(self.plans):
            x0=i*self.cell_width+3
            y0=self.height-height-3
            c.setStrokeGray(.55); c.rect(x0-1,3,self.cell_width-5,self.height-6)
            c.setStrokeGray(0)
            for item in plan:
                if item[0]=='line':
                    _,x1,y1,x2,y2=item;c.line(x0+x1,y0+y1,x0+x2,y0+y2)
                else:
                    _,x,y,value,size,font,align=item
                    c.setFont(font,size)
                    if align=='center':c.drawCentredString(x0+x,y0+y,value)
                    else:c.drawString(x0+x,y0+y,value)
        c.restoreState()


def horizontal_card_markup(card: dict) -> str:
    """A dated horizontal group. Dates may be shared only when ALL match.

    Always preserve exact values, flags, component/specimen labels and dates.
    An ordinary Paragraph wraps naturally, so long edits are not truncated.
    """
    rows = list(card['rows'].values())
    dates = {short_date(row['date']) for row in rows if row['date']}
    title = escape(card['title'].split(' | ', 1)[0]) if card['kind'] not in ('cbc', 'bmp') else ''
    same_date = len(dates) == 1 and all(row['date'] for row in rows)
    if same_date:
        title += (' ' if title else '') + '[' + escape(next(iter(dates))) + ']'
    values = []
    for row in rows:
        value = escape(display_component(row['component'])) + ': ' + escape(row['value'])
        if not same_date and row['date']:
            value += ' [' + escape(short_date(row['date'])) + ']'
        values.append(value)
    return ('<b>' + title + ':</b> ' if title else '') + ' | '.join(values)


def laboratory_flowables(data: dict, width: float, font_size: float = 7.2, include_id_panels: bool = False, blood_gas: dict | None = None, cbc: dict | None = None) -> list:
    style = ParagraphStyle('labline', fontName='Times-Roman', fontSize=font_size,
                           leading=font_size + 1, splitLongWords=True,
                           allowWidows=1, allowOrphans=1)
    note_style = ParagraphStyle('labnote', parent=style, fontSize=6.1, leading=7)
    cards = result_cards(data, include_id_panels=include_id_panels, blood_gas=blood_gas, cbc=cbc)
    out = []
    trees = [card for card in cards if card['kind'] in ('cbc', 'bmp')]
    for i in range(0, len(trees), 4):
        row = LabRow(trees[i:i+4], width)
        if row.height <= 155 and all(tree_text_fits(card, width/4-6) for card in trees[i:i+4]):
            out.append(row)
        else:
            # Overlong result text keeps every character in a wrapping line.
            for card in trees[i:i+4]:
                out.append(Paragraph(horizontal_card_markup(card), style))
    for card in cards:
        if card['kind'] not in ('cbc', 'bmp'):
            out.append(Paragraph(horizontal_card_markup(card), style))
    for text in printable_source_notes(data['notes']):
        out.append(Paragraph(escape('Source: ' + text), note_style))
    return out


def laboratory_html(data: dict, include_id_panels: bool = False, blood_gas: dict | None = None, cbc: dict | None = None) -> str:
    cards = result_cards(data, include_id_panels=include_id_panels, blood_gas=blood_gas, cbc=cbc)
    if not cards and not printable_source_notes(data['notes']):
        return ''
    pieces = []
    pieces.append('<div class="labcards">')
    for card in cards:
        if card['kind'] not in ('cbc', 'bmp'):
            continue
        height, plan = card_plan(card, 180)
        if height > 155 or not tree_text_fits(card, 180):
            pieces.append('<div class="lab-summary lab-full">' + horizontal_card_markup(card) + '</div>')
            continue
        body = []
        for item in plan:
            if item[0] == 'line':
                _, x1, y1, x2, y2 = item
                body.append(f'<line x1="{x1}" y1="{height-y1}" x2="{x2}" y2="{height-y2}" stroke="black" stroke-width="0.5"/>')
            else:
                _, x, y, value, size, font, align = item
                weight = 'bold' if font == 'Times-Bold' else 'normal'
                anchor = 'middle' if align == 'center' else 'start'
                body.append(f'<text x="{x}" y="{height-y}" font-family="Times New Roman,serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>')
        pieces.append(f'<svg class="labcard" role="img" aria-label="{escape("Dated laboratory values" if card["kind"] in ("cbc", "bmp") else card["title"], quote=True)}" viewBox="0 0 180 {height}" xmlns="http://www.w3.org/2000/svg">' + ''.join(body) + '</svg>')
    pieces.append('</div>')
    for card in cards:
        if card['kind'] not in ('cbc', 'bmp'):
            pieces.append('<div class="lab-summary">' + horizontal_card_markup(card) + '</div>')
    for text in printable_source_notes(data['notes']):
        pieces.append('<div class="labnote">Source: ' + escape(text) + '</div>')
    return ''.join(pieces)
