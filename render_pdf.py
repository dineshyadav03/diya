"""Builds the Truffle research dossier's PDF from dossier_content.py.

    python render_pdf.py     ->  Truffle_Research_Dossier.pdf   (GENERATED: edit dossier_content.py, never the PDF)

The rendering helpers and styles are in build_pdf.py. truffle-research.html is built from the same
content by render_html.py.
"""
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak, HRFlowable
)
from reportlab.platypus.tableofcontents import TableOfContents
from build_pdf import (
    styles, md, esc_amp, P, render_bullets, render_table, render_callout,
    render_code, render_timeline, render_namegrid, render_pills, render_facts,
    PAGE_W, PAGE_H, MARGIN, INK, DIM, FAINT, BORDER, LED, ACCENT
)

from dossier_content import (
    SECTIONS, SOURCES, FOOTNOTE, CW, EYEBROW, TITLE, TAGLINE, SUBTITLE, PILLS, SOURCES_HEADING,
)

# ============================================================= DOC BUILD =====

class DossierDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 0.15 * inch,
                       id='normal')
        template = PageTemplate(id='normal', frames=[frame], onPage=self._draw_furniture)
        self.addPageTemplates([template])
        self._bookmark_seq = 0

    def build(self, flowables, **kw):
        self._bookmark_seq = 0
        return super().build(flowables, **kw)

    def _draw_furniture(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - 0.55 * inch, PAGE_W - MARGIN, PAGE_H - 0.55 * inch)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(MARGIN, PAGE_H - 0.42 * inch, 'TRUFFLE RESEARCH DOSSIER')
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.42 * inch, 'truffle.net · Deepshard, Inc.')
        canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
        canvas.drawString(MARGIN, 0.38 * inch, 'Compiled September 2026')
        canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f'Page {doc.page}')
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style_name = flowable.style.name
        text = flowable.getPlainText()
        if style_name == 'H1':
            self._bookmark_seq += 1
            key = f'bm-{self._bookmark_seq}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0, closed=False)
            self.notify('TOCEntry', (0, text, self.page, key))
        elif style_name == 'H2':
            self._bookmark_seq += 1
            key = f'bm-{self._bookmark_seq}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=1, closed=True)
            self.notify('TOCEntry', (1, text, self.page, key))


def build_story():
    story = []

    # ---- Title page ----
    story.append(Spacer(1, 0.9 * inch))
    story.append(Paragraph(f'&#9679;&nbsp;{EYEBROW}', styles['Eyebrow']))
    story.append(Paragraph(TITLE, styles['Title']))
    story.append(Paragraph(TAGLINE, ParagraphStyle('T2', parent=styles['Title'],
                                                                      fontSize=19, textColor=ACCENT,
                                                                      spaceAfter=16)))
    story.append(Paragraph(SUBTITLE, styles['Subtitle']))
    story.append(Spacer(1, 10))
    story.append(render_pills(PILLS))
    story.append(Spacer(1, 26))
    story.append(HRFlowable(width='100%', thickness=0.6, color=BORDER, spaceAfter=14))
    story.append(Paragraph('Contents', ParagraphStyle('ContentsHead', fontName='Helvetica-Bold',
                                                        fontSize=11, textColor=INK, spaceAfter=8)))
    toc = TableOfContents()
    toc.levelStyles = [styles['TOCH1'], styles['TOCH2']]
    story.append(toc)
    story.append(PageBreak())

    # ---- Sections ----
    for i, s in enumerate(SECTIONS):
        story.append(Paragraph(f'{s["num"]} &middot; {s["title"]}', styles['H1']))
        if s['intro']:
            story.append(Paragraph(md(s['intro']), styles['H1sub']))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=10))
        for block in s['blocks']:
            kind = block[0]
            if kind == 'p':
                story.append(P(block[1]))
            elif kind == 'p_dim':
                story.append(P(block[1], 'BodyDim'))
            elif kind == 'h2':
                story.append(Paragraph(block[1], styles['H2']))
            elif kind == 'h3':
                story.append(Paragraph(md(block[1]), styles['H3']))
            elif kind == 'ul':
                story += render_bullets(block[1])
                story.append(Spacer(1, 4))
            elif kind == 'ol':
                story += render_bullets(block[1], ordered=block[2] if len(block) > 2 else True)
                story.append(Spacer(1, 4))
            elif kind == 'table':
                story.append(render_table(block[1], block[2], block[3]))
                story.append(Spacer(1, 10))
            elif kind == 'callout':
                story.append(render_callout(block[1], block[2], warn=False))
            elif kind == 'callout_warn':
                story.append(render_callout(block[1], block[2], warn=True))
            elif kind == 'code':
                story.append(render_code(block[1], block[2]))
            elif kind == 'timeline':
                story += render_timeline(block[1])
                story.append(Spacer(1, 6))
            elif kind == 'namegrid':
                story += render_namegrid(block[1])
            elif kind == 'facts':
                story.append(render_facts(block[1]))
                story.append(Spacer(1, 10))
        story.append(PageBreak())

    # ---- Sources ----
    story.append(Paragraph(SOURCES_HEADING, styles['H1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=10))
    for title, desc in SOURCES:
        if desc:
            story.append(Paragraph(f'<b>{esc_amp(title)}</b> &mdash; {md(desc)}', styles['Source']))
        else:
            story.append(Paragraph(f'<b>{esc_amp(title)}</b>', styles['Source']))
    story.append(Paragraph(md(FOOTNOTE), styles['Footnote']))

    return story


if __name__ == '__main__':
    doc = DossierDoc('Truffle_Research_Dossier.pdf', pagesize=(PAGE_W, PAGE_H),
                      title='Truffle Research Dossier', author='Research compilation')
    doc.multiBuild(build_story())
    print('PDF built.')
