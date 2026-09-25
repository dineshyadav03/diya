"""Builds truffle-research.html from dossier_content.py, with the standard library only.

    python render_html.py            writes truffle-research.html   (GENERATED: edit dossier_content.py, never the page)
    python render_html.py --check    exits 1 if the committed page is not what the content produces

The PDF (render_pdf.py) is built from the same content, so the two cannot drift. The page is one file with its
styles inlined (dossier.css) and loads nothing from anywhere: no web fonts, no scripts, no images.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

import dossier_content

HERE = pathlib.Path(__file__).resolve().parent
OUTPUT = HERE / "truffle-research.html"
STYLE = HERE / "dossier.css"

# A few rules for parts of the page the older hand-written version did not have.
EXTRA_CSS = """
  p.dim{ color:var(--text-dim); font-size:13.5px; }
  .footnote{ margin-top:18px; color:var(--text-dim); font-size:12.5px; max-width:none; }
  h3.sub-head{ font-size:15px; margin:22px 0 6px; }
"""


def esc_amp(text):
    """Escape a bare & but leave an entity that is already written (&amp; &middot; &#9679;) alone: the
    content is written for the PDF, whose paragraph markup uses the same entities."""
    return re.sub(r"&(?!amp;|lt;|gt;|#|[A-Za-z]+;)", "&amp;", text)


def inline(text):
    """A line of content as HTML: **bold**, `code`, _italic_, with everything else escaped."""
    text = esc_amp(str(text)).replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace(" -- ", " &mdash; ")  # the content writes a dash as "--" for the PDF; the page sets it properly
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    return text


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"&\w+;|`|\*", "", text.lower())).strip("-") or "part"


def _table(headers, rows):
    head = "".join(f"<th>{inline(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for cell in row:
            cell = str(cell)
            cells.append(f'<td class="mono">{inline(cell[5:])}</td>' if cell.startswith("MONO:") else f"<td>{inline(cell)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_block(block, section_id, headings):
    """One content block as HTML. `headings` collects (id, text) of the sub-headings for the sidebar."""
    kind, *data = block
    if kind == "p":
        return f"<p>{inline(data[0])}</p>"
    if kind == "p_dim":
        return f'<p class="dim">{inline(data[0])}</p>'
    if kind == "h2":
        heading_id = f"{section_id}-{slug(data[0])}"
        headings.append((heading_id, data[0]))
        return f'<h3 class="sub-head" id="{heading_id}">{inline(data[0])}</h3>'
    if kind == "h3":
        return f"<h4>{inline(data[0])}</h4>"
    if kind in ("ul", "ol"):
        tag = "ol" if kind == "ol" and (len(data) < 2 or data[1]) else "ul"
        return f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in data[0]) + f"</{tag}>"
    if kind == "table":
        return _table(data[0], data[1])  # data[2] is the PDF's column widths: the page sizes its own
    if kind in ("callout", "callout_warn"):
        cls = "callout warn" if kind == "callout_warn" else "callout"
        return f'<div class="{cls}"><strong>{inline(data[0])}</strong><p>{inline(data[1])}</p></div>'
    if kind == "code":
        return f'<div class="code-label">{html.escape(data[0]).upper()}</div><pre><code>{html.escape(data[1])}</code></pre>'
    if kind == "timeline":
        items = "".join(
            f'<li><div class="date">{html.escape(date)}</div><div class="title">{inline(title)}</div>'
            f'<div class="desc">{inline(desc)}</div></li>'
            for date, title, desc in data[0]
        )
        return f'<ul class="timeline">{items}</ul>'
    if kind == "namegrid":
        rows = "".join(
            f'<div class="name-row{" this" if is_this else ""}"><div class="badge">{html.escape(mark)}</div>'
            f'<div><div class="t">{inline(title)}</div><div class="d">{inline(desc)}</div></div></div>'
            for mark, title, desc, is_this in data[0]
        )
        return f'<div class="name-grid">{rows}</div>'
    if kind == "facts":
        cells = "".join(f'<div class="fact"><div class="k">{html.escape(k)}</div><div class="v">{inline(v)}</div></div>' for k, v in data[0])
        return f'<div class="fact-grid">{cells}</div>'
    raise ValueError(f"unknown content block kind {kind!r}")


def render_source(title, description):
    label = f"<strong>{inline(title)}</strong>"
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[a-z]{2,}(/[^\s;]*)?", title):  # a bare address is a link
        label = f'<strong><a href="https://{html.escape(title, quote=True)}">{html.escape(title)}</a></strong>'
    return f"<li>{label}" + (f" &mdash; {inline(description)}" if description else "") + "</li>"


def build(content=dossier_content, style=None):
    """The whole page as a string. `content` is any module or object with dossier_content's names."""
    style = STYLE.read_text(encoding="utf-8") if style is None else style
    sections, nav = [], []
    for section in content.SECTIONS:
        headings: list = []
        blocks = "\n      ".join(render_block(block, section["id"], headings) for block in section["blocks"])
        intro = f'<p class="section-intro">{inline(section["intro"])}</p>\n      ' if section["intro"] else ""
        sections.append(
            f'    <section id="{section["id"]}">\n      <h2><span class="num">{section["num"]}</span> {inline(section["title"])}</h2>\n'
            f"      {intro}{blocks}\n    </section>"
        )
        nav.append(f'      <li><a href="#{section["id"]}">{section["num"]}. {inline(section["title"])}</a></li>')
        nav += [f'      <li class="sub"><a href="#{hid}">&middot; {inline(text)}</a></li>' for hid, text in headings]
    nav.append(f'      <li><a href="#sources">{content.SOURCES_HEADING.replace("&middot;", ".", 1)}</a></li>')
    pills = "".join(f'<span class="pill">{html.escape(pill)}</span>' for pill in content.PILLS)
    sources = "\n      ".join(render_source(title, desc) for title, desc in content.SOURCES)
    return f"""<!doctype html>
<!-- GENERATED by render_html.py from dossier_content.py: edit that file, never this one. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="render_html.py">
<title>Truffle Research Dossier</title>
<style>
{style}{EXTRA_CSS}</style>
</head>
<body>
<div class="layout">
  <nav class="toc" aria-label="Table of contents">
    <div class="toc-brand"><span class="dot"></span> TRUFFLE DOSSIER</div>
    <ul>
{chr(10).join(nav)}
    </ul>
  </nav>

  <main>
    <div class="hero" id="top">
      <div class="eyebrow">{content.EYEBROW}</div>
      <h1>{html.escape(content.TITLE)} &mdash; {html.escape(content.TAGLINE.lower())}</h1>
      <p class="lede">{inline(content.SUBTITLE)}</p>
      <div class="meta-row">{pills}</div>
    </div>

{chr(10).join(sections)}

    <footer id="sources">
      <h2>{content.SOURCES_HEADING}</h2>
      <ul class="src-list">
      {sources}
      </ul>
      <p class="footnote">{inline(content.FOOTNOTE)}</p>
    </footer>
  </main>
</div>
</body>
</html>
"""


def main(argv):
    page = build()
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != page:
            print(f"{OUTPUT.name} is not what dossier_content.py produces: run python render_html.py")
            return 1
        print(f"{OUTPUT.name} is up to date.")
        return 0
    OUTPUT.write_text(page, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.name} ({len(page):,} characters).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
