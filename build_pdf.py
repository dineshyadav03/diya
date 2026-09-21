# Rendering helpers and styles for the dossier PDF. The content lives in render_pdf.py, which imports this.
import re
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, Preformatted, KeepTogether, HRFlowable
)
from reportlab.platypus.tableofcontents import TableOfContents

# ---------- palette (mirrors the artifact's light theme) ----------
INK = colors.HexColor('#211d16')
DIM = colors.HexColor('#6c6353')
FAINT = colors.HexColor('#9a927e')
BORDER = colors.HexColor('#ddd7c8')
SURFACE2 = colors.HexColor('#eae6db')
ACCENT = colors.HexColor('#6e4318')
ACCENT_SOFT = colors.HexColor('#f1e3cd')
LED = colors.HexColor('#127a68')
LED_SOFT = colors.HexColor('#dcf0ec')
CODE_BG = colors.HexColor('#1c1810')
CODE_TEXT = colors.HexColor('#ecdfc6')
WHITE = colors.white

PAGE_W, PAGE_H = LETTER
MARGIN = 0.82 * inch

# ---------- text helpers ----------
def esc_amp(s):
    return re.sub(r'&(?!amp;|lt;|gt;|#)', '&amp;', s)

def md(s):
    s = esc_amp(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'`([^`]+)`', r'<font face="Courier" size="8.6" color="#6e4318">\1</font>', s)
    s = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<i>\1</i>', s)
    return s

# ---------- styles ----------
ss = getSampleStyleSheet()
styles = {
    'Title': ParagraphStyle('TitleX', fontName='Helvetica-Bold', fontSize=27, leading=32,
                             textColor=INK, spaceAfter=10),
    'Subtitle': ParagraphStyle('SubtitleX', fontName='Helvetica', fontSize=12.5, leading=18,
                                textColor=DIM, spaceAfter=14),
    'Eyebrow': ParagraphStyle('EyebrowX', fontName='Helvetica-Bold', fontSize=9.5, leading=12,
                               textColor=LED, spaceAfter=10, tracking=0),
    'H1': ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=17, leading=21,
                          textColor=INK, spaceBefore=4, spaceAfter=4),
    'H1sub': ParagraphStyle('H1sub', fontName='Helvetica', fontSize=9.5, leading=13,
                             textColor=DIM, spaceAfter=14),
    'H2': ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=12.5, leading=16,
                          textColor=ACCENT, spaceBefore=14, spaceAfter=6),
    'H3': ParagraphStyle('H3', fontName='Helvetica-Bold', fontSize=10, leading=13,
                          textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    'Body': ParagraphStyle('Body', fontName='Helvetica', fontSize=9.6, leading=14.5,
                            textColor=INK, spaceAfter=8, alignment=TA_LEFT),
    'BodyDim': ParagraphStyle('BodyDim', fontName='Helvetica-Oblique', fontSize=9.3, leading=13.5,
                               textColor=DIM, spaceAfter=10),
    'Bullet': ParagraphStyle('Bullet', fontName='Helvetica', fontSize=9.4, leading=13.8,
                              textColor=INK, spaceAfter=3),
    'Cell': ParagraphStyle('Cell', fontName='Helvetica', fontSize=8.3, leading=11.6, textColor=INK),
    'CellHead': ParagraphStyle('CellHead', fontName='Helvetica-Bold', fontSize=7.6, leading=10,
                                textColor=DIM),
    'CellMono': ParagraphStyle('CellMono', fontName='Courier', fontSize=8, leading=11, textColor=INK),
    'CalloutTitle': ParagraphStyle('CalloutTitle', fontName='Helvetica-Bold', fontSize=9.6,
                                    leading=12, textColor=ACCENT, spaceAfter=3),
    'CalloutTitleLed': ParagraphStyle('CalloutTitleLed', fontName='Helvetica-Bold', fontSize=9.6,
                                       leading=12, textColor=LED, spaceAfter=3),
    'CalloutBody': ParagraphStyle('CalloutBody', fontName='Helvetica', fontSize=9.1, leading=13.2,
                                   textColor=INK),
    'CodeLabel': ParagraphStyle('CodeLabel', fontName='Helvetica-Bold', fontSize=7.6, leading=10,
                                 textColor=FAINT, spaceAfter=2, spaceBefore=6),
    'Code': ParagraphStyle('Code', fontName='Courier', fontSize=7.6, leading=10.6,
                            textColor=CODE_TEXT, backColor=CODE_BG),
    'Pill': ParagraphStyle('Pill', fontName='Courier', fontSize=7.6, leading=10, textColor=DIM),
    'TOCH1': ParagraphStyle('TOCH1', fontName='Helvetica-Bold', fontSize=10.5, leading=16,
                             textColor=INK, leftIndent=0, firstLineIndent=0, spaceBefore=6),
    'TOCH2': ParagraphStyle('TOCH2', fontName='Helvetica', fontSize=9, leading=13,
                             textColor=DIM, leftIndent=16, firstLineIndent=0),
    'Source': ParagraphStyle('Source', fontName='Helvetica', fontSize=8, leading=12,
                              textColor=DIM, spaceAfter=4),
    'Footnote': ParagraphStyle('Footnote', fontName='Helvetica-Oblique', fontSize=8, leading=11.5,
                                textColor=FAINT, spaceBefore=12),
}

def P(text, style='Body'):
    return Paragraph(md(text), styles[style])

def C(text, style='Cell'):
    return Paragraph(md(text), styles[style])

# ---------- block renderers ----------
def render_bullets(items, ordered=False):
    flow = []
    bullet = '&bull;'
    for i, it in enumerate(items, 1):
        prefix = f'{i}.' if ordered else bullet
        flow.append(Paragraph(f'<font color="#6e4318"><b>{prefix}</b></font>&nbsp;&nbsp;{md(it)}',
                               styles['Bullet']))
    return flow

def render_table(headers, rows, col_widths, header_bg=SURFACE2, zebra=False):
    data = [[C(h, 'CellHead') for h in headers]]
    for r in rows:
        data.append([C(c, 'Cell') if not str(c).startswith('MONO:') else C(c[5:], 'CellMono') for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#faf8f3')))
    t.setStyle(TableStyle(style))
    return t

def render_callout(title, text, warn=False):
    accent = ACCENT if warn else LED
    tstyle = 'CalloutTitle' if warn else 'CalloutTitleLed'
    inner = Table([[Paragraph(md(title), styles[tstyle])], [Paragraph(md(text), styles['CalloutBody'])]],
                   colWidths=[6.35 * inch])
    inner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), WHITE),
        ('BOX', (0, 0), (-1, -1), 0.6, BORDER),
        ('LINEBEFORE', (0, 0), (0, -1), 3, accent),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    return KeepTogether([inner, Spacer(1, 8)])

def render_code(label, code_text):
    lbl = Paragraph(esc_amp(label).upper(), styles['CodeLabel'])
    pre = Preformatted(code_text, styles['Code'])
    box = Table([[pre]], colWidths=[6.35 * inch])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CODE_BG),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return KeepTogether([lbl, box, Spacer(1, 8)])

def render_timeline(items):
    flow = []
    for date, title, desc in items:
        row = Table([[Paragraph(f'<font color="#127a68"><b>{esc_amp(date)}</b></font>', styles['Cell']),
                       Paragraph(f'<b>{md(title)}</b><br/><font color="#6c6353">{md(desc)}</font>',
                                 styles['Body'])]],
                     colWidths=[1.15 * inch, 5.2 * inch])
        row.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.4, BORDER),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        flow.append(row)
    return flow

def render_namegrid(rows):
    flow = []
    for mark, title, desc, is_this in rows:
        accent = LED if is_this else FAINT
        bg = LED_SOFT if is_this else WHITE
        cell = Paragraph(f'<font color="{"#127a68" if is_this else "#9a927e"}"><b>{mark}</b></font> '
                          f'<b>{md(title)}</b><br/><font size="8.6" color="#6c6353">{md(desc)}</font>',
                          styles['Body'])
        t = Table([[cell]], colWidths=[6.35 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg),
            ('BOX', (0, 0), (-1, -1), 0.6, BORDER if not is_this else LED),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 5))
    return flow

def render_pills(pills):
    row = [Paragraph(esc_amp(p), styles['Pill']) for p in pills]
    t = Table([row])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SURFACE2),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t

def render_facts(facts, cols=4):
    cellw = 6.35 * inch / cols
    rows = []
    for i in range(0, len(facts), cols):
        row = []
        for k, v in facts[i:i + cols]:
            row.append(Paragraph(f'<font size="7" color="#9a927e"><b>{esc_amp(k).upper()}</b></font>'
                                  f'<br/><font size="9.4"><b>{md(v)}</b></font>', styles['Body']))
        while len(row) < cols:
            row.append('')
        rows.append(row)
    t = Table(rows, colWidths=[cellw] * cols)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), WHITE),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t
