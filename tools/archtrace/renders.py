"""Render the model into build outputs.

Nothing here is a source of truth. Every function is a pure, deterministic
function of the engagement: no clock, no network, no randomness, no locale
dependence. That is what lets the render-freshness gate mean something.

Standard library only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from xml.sax.saxutils import escape, quoteattr

from . import canon, docx_shapes
from .config import DEFAULT as CONFIG
from .model import (
    NFR_CATEGORIES,
    RENDER_MANIFEST,
    RENDERER_VERSION,
    Element,
    Engagement,
)

BOX_W, BOX_H = CONFIG.render.box_width, CONFIG.render.box_height
MARGIN = CONFIG.render.margin
CHARS_PER_LINE = CONFIG.render.chars_per_line
LEGEND_H = CONFIG.render.legend_height
TITLE_CHARS = CONFIG.render.title_chars

# Deliberately literal fills: an SVG committed to a repository is viewed on both
# light and dark backgrounds, and a filled box with dark text reads on both.
FILL = {
    "person": "#dbe4f0", "system": "#c7d7ee", "system_ext": "#e4e4e4",
    "container": "#cfe3d8", "component": "#efe3c9",
}
STROKE = "#33415c"
TEXT = "#16202e"


def _wrap(text: str, width: int = CHARS_PER_LINE) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _kind(element: Element) -> str:
    if element.level == "system" and element.data.get("external"):
        return "system_ext"
    return element.level


# --- SVG -------------------------------------------------------------------

def _boundary(cx: int, cy: int, tx: int, ty: int, pad: int = 6) -> tuple[int, int]:
    """Where a line from a box centre toward (tx, ty) leaves the box.

    Centre-to-centre lines run straight through intervening boxes and make the
    diagram unreadable the moment it has more than four elements.
    """
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    half_w, half_h = BOX_W / 2 + pad, BOX_H / 2 + pad
    scale = min(half_w / abs(dx) if dx else float("inf"),
                half_h / abs(dy) if dy else float("inf"))
    return round(cx + dx * scale), round(cy + dy * scale)


# One letter per grounding kind, drawn on the element. The point of the whole
# tool is that you can see which boxes nobody asked for; a diagram that hides
# that is just a diagram.
GROUNDING_BADGE = {
    "satisfies": ("S", "#2f6b4f"), "derived": ("D", "#3b5a7a"),
    "standard": ("T", "#6b5a2f"), "existing": ("E", "#5a5a5a"),
    "assumption": ("A", "#9a4b2f"),
}


def _svg(title: str, nodes: list[tuple[Element, str]], edges: list[dict]) -> bytes:
    legend_h = LEGEND_H
    if nodes:
        width = max(n.layout.get("x", 0) for n, _ in nodes) + BOX_W + MARGIN
        height = (max(n.layout.get("y", 0) for n, _ in nodes)
                  + BOX_H + MARGIN + 30 + legend_h)
    else:
        width, height = 420, 120 + legend_h
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="Helvetica, Arial, sans-serif">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{STROKE}"/></marker></defs>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{MARGIN}" y="26" font-size="15" font-weight="bold" '
        f'fill="{TEXT}">{escape(title)}</text>',
    ]
    centres = {}
    for element, _kind in nodes:
        centres[element.id] = (element.layout.get("x", 0) + BOX_W // 2,
                               element.layout.get("y", 0) + 30 + BOX_H // 2)

    # Edges first so boxes paint over their tails rather than the reverse.
    labels = []
    for edge in edges:
        if edge["source"] not in centres or edge["destination"] not in centres:
            continue
        cx1, cy1 = centres[edge["source"]]
        cx2, cy2 = centres[edge["destination"]]
        x1, y1 = _boundary(cx1, cy1, cx2, cy2)
        x2, y2 = _boundary(cx2, cy2, cx1, cy1)
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                   f'stroke="{STROKE}" stroke-width="1.2" '
                   f'stroke-dasharray="4 3" marker-end="url(#arrow)"/>')
        labels.append(((x1 + x2) // 2, (y1 + y2) // 2,
                       edge.get("description", "")))

    for element, kind in nodes:
        x = element.layout.get("x", 0)
        y = element.layout.get("y", 0) + 30
        out.append(
            f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" '
            f'fill="{FILL[kind]}" stroke="{STROKE}" stroke-width="1.5"/>')
        seen = []
        for entry in element.grounding:
            badge = GROUNDING_BADGE.get(entry.get("kind", ""))
            if badge and badge not in seen:
                seen.append(badge)
        for index, (letter, colour) in enumerate(seen[:3]):
            bx = x + BOX_W - 14 - index * 17
            out.append(f'<circle cx="{bx}" cy="{y + 14}" r="7.5" '
                       f'fill="{colour}"/>')
            out.append(f'<text x="{bx}" y="{y + 18}" font-size="9" '
                       f'font-weight="bold" text-anchor="middle" '
                       f'fill="#ffffff">{letter}</text>')
        line_y = y + 28
        for line in _wrap(element.name, TITLE_CHARS)[:2]:
            out.append(f'<text x="{x + BOX_W // 2}" y="{line_y}" font-size="13" '
                       f'font-weight="bold" text-anchor="middle" '
                       f'fill="{TEXT}">{escape(line)}</text>')
            line_y += 16
        technology = element.data.get("technology")
        if technology:
            out.append(f'<text x="{x + BOX_W // 2}" y="{line_y}" font-size="10" '
                       f'font-style="italic" text-anchor="middle" '
                       f'fill="{TEXT}">[{escape(technology)}]</text>')
            line_y += 14
        for line in _wrap(element.data.get("description", ""))[:3]:
            out.append(f'<text x="{x + BOX_W // 2}" y="{line_y}" font-size="10" '
                       f'text-anchor="middle" fill="{TEXT}">{escape(line)}</text>')
            line_y += 12

    # Labels last, each on an opaque plate: an edge label sitting under box text
    # is worse than no label.
    for lx, ly, text in labels:
        if not text:
            continue
        plate = max(1, len(text) * 6 + 8)
        out.append(f'<rect x="{lx - plate // 2}" y="{ly - 9}" width="{plate}" '
                   f'height="14" rx="3" fill="#ffffff" stroke="#ffffff" '
                   f'stroke-width="2"/>')
        out.append(f'<text x="{lx}" y="{ly + 2}" font-size="10" '
                   f'text-anchor="middle" fill="{TEXT}">{escape(text)}</text>')

    ly = height - 12
    out.append(f'<text x="{MARGIN}" y="{ly}" font-size="9" fill="{TEXT}">'
               'grounding:</text>')
    lx = MARGIN + 58
    for kind in ("satisfies", "derived", "standard", "existing", "assumption"):
        letter, colour = GROUNDING_BADGE[kind]
        out.append(f'<circle cx="{lx}" cy="{ly - 3}" r="6.5" fill="{colour}"/>')
        out.append(f'<text x="{lx}" y="{ly}" font-size="8" font-weight="bold" '
                   f'text-anchor="middle" fill="#ffffff">{letter}</text>')
        out.append(f'<text x="{lx + 11}" y="{ly}" font-size="9" '
                   f'fill="{TEXT}">{kind}</text>')
        lx += 18 + len(kind) * 5 + 14
    out.append("</svg>")
    return ("\n".join(out) + "\n").encode("utf-8")


# --- PlantUML / Mermaid ----------------------------------------------------

def _emission_order(nodes: Iterable[tuple[Element, str]]) -> list[tuple[Element, str]]:
    """Mermaid and PlantUML accept no coordinates; statement order is the only
    layout lever they offer. Sorting by (y, x) makes the text renders roughly
    agree with the SVG and the .drawio instead of drifting arbitrarily."""
    return sorted(nodes, key=lambda n: (n[0].layout.get("y", 0),
                                        n[0].layout.get("x", 0), n[0].id))


# One table, not two. `_PUML_MACRO` and `_MMD_MACRO` were separate dicts with
# identical contents, which is a drift waiting to happen: adding a C4 element
# kind to one and not the other produces a KeyError in exactly one renderer.
C4_MACRO = {"person": "Person", "system": "System", "system_ext": "System_Ext",
            "container": "Container", "component": "Component"}


def _puml_arg(value) -> str:
    """Escape a value for a quoted C4 macro argument in PlantUML.

    The argument is delimited by double quotes and the preprocessor offers no
    backslash escape inside one, so a quote in an element name terminated the
    argument early and produced a diagram that does not parse at all. PlantUML
    resolves HTML entities in labels, so `&quot;` renders as a quote. A newline
    would end the statement, so it is folded to a space.
    """
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("\n", " ").replace("\r", " "))


def _mmd_arg(value) -> str:
    """The same problem in Mermaid, which spells the entity differently.

    Mermaid's documented escape inside a label is `#quot;`; it does not share
    PlantUML's `&`-entity syntax, which is why these are two functions rather
    than one shared helper with a parameter.
    """
    return (str(value).replace('"', "#quot;")
            .replace("\n", " ").replace("\r", " "))


def _md_cell(value) -> str:
    """Escape a value for a GitHub-flavoured Markdown table cell.

    An unescaped pipe starts a new column, so an element named `A | B` turned a
    five-column row into six and silently shifted every cell after it. One call
    site already escaped pipes by hand, on `quote_cached` only.
    """
    return (str(value).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\n", " ").replace("\r", " "))


def _puml(title: str, level: str, nodes, edges) -> bytes:
    include = ("https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/"
               f"master/C4_{'Context' if level == 'context' else 'Container'}.puml")
    out = ["@startuml", f"!include {include}", "", f"title {_puml_arg(title)}", ""]
    for element, kind in _emission_order(nodes):
        macro = C4_MACRO[kind]
        args = [element.id, f'"{_puml_arg(element.name)}"']
        if kind in ("container", "component"):
            args.append(f'"{_puml_arg(element.data.get("technology", ""))}"')
        args.append(f'"{_puml_arg(element.data.get("description", ""))}"')
        out.append(f"{macro}({', '.join(args)})")
    out.append("")
    for edge in edges:
        out.append(f'Rel({edge["source"]}, {edge["destination"]}, '
                   f'"{_puml_arg(edge.get("description", ""))}", '
                   f'"{_puml_arg(edge.get("technology", ""))}")')
    out += ["", "@enduml"]
    return ("\n".join(out) + "\n").encode("utf-8")


def _mermaid(title: str, level: str, nodes, edges) -> bytes:
    header = "C4Context" if level == "context" else "C4Container"
    out = [header, f"    title {_mmd_arg(title)}"]
    for element, kind in _emission_order(nodes):
        macro = C4_MACRO[kind]
        args = [element.id, f'"{_mmd_arg(element.name)}"']
        if kind in ("container", "component"):
            args.append(f'"{_mmd_arg(element.data.get("technology", ""))}"')
        args.append(f'"{_mmd_arg(element.data.get("description", ""))}"')
        out.append(f"    {macro}({', '.join(args)})")
    for edge in edges:
        out.append(f'    Rel({edge["source"]}, {edge["destination"]}, '
                   f'"{_mmd_arg(edge.get("description", ""))}")')
    return ("\n".join(out) + "\n").encode("utf-8")


# --- draw.io ---------------------------------------------------------------

_DRAWIO_STYLE = {
    "person": "rounded=1;fillColor=#dbe4f0;strokeColor=#33415c;",
    "system": "rounded=1;fillColor=#c7d7ee;strokeColor=#33415c;",
    "system_ext": "rounded=1;fillColor=#e4e4e4;strokeColor=#33415c;dashed=1;",
    "container": "rounded=1;fillColor=#cfe3d8;strokeColor=#33415c;",
    "component": "rounded=1;fillColor=#efe3c9;strokeColor=#33415c;",
}


def _drawio(pages: list[tuple[str, list, list]]) -> bytes:
    # No `modified` attribute: it is conventional but non-deterministic, and it
    # would fail the render-freshness gate on every run.
    out = ['<mxfile host="archtrace" type="device">']
    for name, nodes, edges in pages:
        out.append(f'  <diagram id={quoteattr(name)} name={quoteattr(name)}>')
        out.append('    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" '
                   'page="1" pageWidth="1169" pageHeight="826">')
        out.append('      <root>')
        out.append('        <mxCell id="0"/>')
        out.append('        <mxCell id="1" parent="0"/>')
        for element, kind in nodes:
            label = element.name
            if element.data.get("technology"):
                label += f"\n[{element.data['technology']}]"
            out.append(
                f'        <mxCell id={quoteattr(element.id)} '
                f'value={quoteattr(label)} style={quoteattr(_DRAWIO_STYLE[kind])} '
                f'vertex="1" parent="1">')
            out.append(
                f'          <mxGeometry x="{element.layout.get("x", 0)}" '
                f'y="{element.layout.get("y", 0)}" width="{BOX_W}" '
                f'height="{BOX_H}" as="geometry"/>')
            out.append('        </mxCell>')
        present = {e.id for e, _ in nodes}
        for idx, edge in enumerate(edges):
            if edge["source"] not in present or edge["destination"] not in present:
                continue
            out.append(
                f'        <mxCell id={quoteattr(f"{name}-e{idx}")} '
                f'value={quoteattr(edge.get("description", ""))} '
                'style="edgeStyle=orthogonalEdgeStyle;dashed=1;" edge="1" '
                f'parent="1" source={quoteattr(edge["source"])} '
                f'target={quoteattr(edge["destination"])}>')
            out.append('          <mxGeometry relative="1" as="geometry"/>')
            out.append('        </mxCell>')
        out += ['      </root>', '    </mxGraphModel>', '  </diagram>']
    out.append('</mxfile>')
    return ("\n".join(out) + "\n").encode("utf-8")


# --- traceability ----------------------------------------------------------

def _grounding_text(entry: dict) -> str:
    kind = entry.get("kind")
    ref = (entry.get("req") or entry.get("from") or entry.get("standard")
           or entry.get("evidence_id") or entry.get("open_question") or "")
    adr = f" via {entry['adr']}" if entry.get("adr") else ""
    symbol = f" @{entry['symbol']}" if entry.get("symbol") else ""
    return f"{kind}:{ref}{adr}{symbol}"


def _source_locator(eng: Engagement, entry: dict) -> str:
    """Where in the code a symbol-grounded element actually lives.

    A symbol id is verifiable but unreadable. A reviewer needs `path:line`, and
    resolving it here rather than storing it keeps the model free of derived
    data that could drift from the facts file.
    """
    symbol = entry.get("symbol")
    if not symbol:
        return ""
    facts = eng.evidence_facts(entry.get("evidence_id", ""))
    if facts is None:
        return symbol
    return facts.locator(symbol)


def _element_locators(eng: Engagement, grounding: list) -> str:
    found = [_source_locator(eng, entry) for entry in grounding]
    return "; ".join(item for item in found if item)


def _traceability_md(eng: Engagement) -> bytes:
    mix = eng.grounding_mix()
    out = [f"# Traceability — {eng.model.get('workspace', {}).get('name', '')}",
           "", "_Generated by archtrace. Do not edit._", "",
           "## Grounding mix", "",
           "A model that is 100% `satisfies` is the suspicious one: real",
           "architectures contain elements nobody asked for.", "",
           "| kind | count | share |", "|---|---|---|"]
    total = mix["total"] or 1
    for kind in sorted(mix["by_kind"]):
        count = mix["by_kind"][kind]
        out.append(f"| {kind} | {count} | {100 * count // total}% |")
    out += ["", "## Requirements to elements", "",
            "| REQ | status | priority | statement | grounded by |",
            "|---|---|---|---|---|"]
    for req in eng.requirements:
        grounded = sorted(e.id for e in eng.elements() for g in e.grounding
                          if g.get("kind") == "satisfies" and g.get("req") == req["id"])
        excluded = next((o for o in eng.out_of_scope if o["req"] == req["id"]), None)
        # Renderers stay total over malformed input: a missing field is the
        # gate's finding to report, not a traceback that hides every other one.
        cell = ", ".join(f"`{g}`" for g in grounded) or (
            f"_out of scope — {excluded.get('rationale', '?')} "
            f"({excluded.get('decided_by', '?')}, {excluded.get('date', '?')})_"
            if excluded else "**none**")
        out.append(f"| {req['id']} | {req.get('status')} | {req.get('priority')} "
                   f"| {_md_cell(req.get('statement'))} | {cell} |")
    out += ["", "## Elements to grounding", "",
            "`source` resolves a cited symbol to where it lives in the mined",
            "codebase. Blank means the element is not grounded in code.", "",
            "| element | level | name | grounding | source |",
            "|---|---|---|---|---|"]
    for element in eng.elements():
        cell = ", ".join(_grounding_text(g) for g in element.grounding)
        locator = _element_locators(eng, element.grounding)
        out.append(f"| `{element.id}` | {element.level} "
                   f"| {_md_cell(element.name)} | {cell} | {locator} |")
    out += ["", "## Non-functional coverage", "",
            "Three honest positions, not two. `open` is a tracked gap; it is not",
            "the same claim as `not_applicable`.", "",
            "| category | status | basis |", "|---|---|---|"]
    coverage = eng.nfr_coverage
    by_req: dict = {}
    for req in eng.confirmed_requirements:
        for category in req.get("nfr_categories", []):
            by_req.setdefault(category, []).append(req["id"])
    for category in NFR_CATEGORIES:
        entry = coverage.get(category)
        if category in by_req:
            basis = ", ".join(by_req[category])
            status = entry.get("status", "covered") if entry else "covered"
        elif entry is None:
            status, basis = "**undeclared**", ""
        elif entry.get("status") == "open":
            status, basis = "open", entry.get("open_question", "")
        elif entry.get("status") == "not_applicable":
            status = "not applicable"
            basis = (f"{entry.get('rationale', '')} "
                     f"({entry.get('decided_by', '')}, {entry.get('date', '')})")
        else:
            status, basis = entry.get("status", "?"), ""
        out.append(f"| {category} | {status} | {_md_cell(basis)} |")
    if eng.open_questions:
        out += ["", "## Open questions", "", "| id | question | owner |",
                "|---|---|---|"]
        for question in eng.open_questions:
            out.append(f"| {question['id']} | {_md_cell(question['question'])} "
                       f"| {_md_cell(question.get('owner', ''))} |")
    code_records = [r for r in eng.evidence
                    if r.get("content_kind") == "structured"]
    if code_records:
        out += ["", "## Code evidence", "",
                "Observed implementation. Grounds elements as `existing` or",
                "`derived`; never carries a requirement.", "",
                "| id | repository | commit | symbols | relations |",
                "|---|---|---|---|---|"]
        for record in code_records:
            facts = eng.evidence_facts(record["id"])
            symbols = len(facts.symbols) if facts else "?"
            relations = len(facts.relations) if facts else "?"
            commit = (record.get("commit") or (facts.commit if facts else "") or "")
            out.append(f"| {record['id']} "
                       f"| {_md_cell(record.get('source_uri', ''))} "
                       f"| `{commit[:12]}` | {symbols} | {relations} |")
    out += ["", "## Citations", "",
            "`authority` is what the record proves. Observed implementation is",
            "evidence of what exists, never of what is required.", "",
            "| REQ | evidence | authority | speaker | quote |",
            "|---|---|---|---|---|"]
    for req in eng.requirements:
        for prov in req.get("provenance", []):
            # Was a hand-rolled pipe escape here, and the only one in the file.
            # Routed through the shared helper so every cell is escaped the
            # same way rather than wherever somebody remembered to.
            quote = _md_cell(prov.get("quote_cached", ""))
            record = eng.evidence_by_id(prov["evidence_id"]) or {}
            out.append(f"| {req['id']} | {prov['evidence_id']} "
                       f"| {record.get('authority', '?')} "
                       f"| {_md_cell(prov.get('speaker', ''))} "
                       f"| \"{quote}\" |")
    return ("\n".join(out) + "\n").encode("utf-8")


def _traceability_csv(eng: Engagement) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["element_id", "element_uid", "level", "name",
                     "grounding_kind", "grounding_ref", "adr", "symbol",
                     "source_locator"])
    for element in eng.elements():
        for entry in element.grounding:
            ref = (entry.get("req") or entry.get("from") or entry.get("standard")
                   or entry.get("evidence_id") or entry.get("open_question") or "")
            writer.writerow([element.id, element.uid, element.level, element.name,
                             entry.get("kind", ""), ref, entry.get("adr", ""),
                             entry.get("symbol", ""),
                             _source_locator(eng, entry)])
    return buf.getvalue().encode("utf-8")


# --- docx ------------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = " ".join([
    f'xmlns:w="{_W}"',
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships"',
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
    'wordprocessingDrawing"',
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"',
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"',
    'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/'
    'wordprocessingGroup"',
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/'
    'wordprocessingShape"',
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"',
    'mc:Ignorable="wpg wps"',
])


# Each view gets a contiguous block of shape ids. Word reports a document as
# corrupt when two shapes share an id, and a stride large enough that no
# realistic view can overrun it is cheaper than a global counter that would make
# one view's id depend on another view's contents.
MAX_DOCX_ID_STRIDE = 1000


def _diagram(nodes, edges, first_id: int, name: str) -> str:
    """Bridge the model-shaped arguments onto the DrawingML emitter.

    The emitter takes geometry as parameters rather than importing this module,
    so the two cannot disagree about box size or wrapping while staying free of
    a circular import.
    """
    return docx_shapes.diagram(
        nodes, edges, box_w=BOX_W, box_h=BOX_H, margin=MARGIN,
        fill_by_kind=FILL, stroke=STROKE, badge_by_kind=GROUNDING_BADGE,
        wrap=_wrap, title_chars=TITLE_CHARS, chars_per_line=CHARS_PER_LINE,
        boundary=_boundary, first_id=first_id, name=name)


def _p(text: str, style: str | None = None) -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return (f'<w:p>{props}<w:r><w:t xml:space="preserve">'
            f'{escape(text)}</w:t></w:r></w:p>')


def _docx(eng: Engagement, views: list | None = None) -> bytes:
    """Minimal, valid OOXML assembled with zipfile.

    Diagrams are native DrawingML shapes emitted straight into document.xml from
    the same layout coordinates the SVG uses — no rasteriser, so no Node and no
    drawio CLI, and the zero-dependency invariant survives. A reader can select
    and recolour a box in Word; a reader who *moves* one is editing a build
    output, which G6 will notice at the next gate.

    `views` defaults to empty so the narrative document still renders for a
    caller that has no layout to draw.
    """
    workspace = eng.model.get("workspace", {})
    body = [_p(f"Architecture — {workspace.get('name', '')}", "Heading1"),
            _p(f"Client: {workspace.get('client', '')}"),
            _p("Generated by archtrace from model/model.json. "
               "This document is a build output; edit the model, not this file.")]
    # Diagram ids start well clear of any hand-authored part and advance by a
    # fixed stride per view, so the same model always produces the same ids.
    for index, (view_title, nodes, edges) in enumerate(views or []):
        drawing = _diagram(nodes, edges,
                           MAX_DOCX_ID_STRIDE * (index + 1), view_title)
        if not drawing:
            continue
        body.append(_p(view_title, "Heading1"))
        body.append(drawing)
        body.append(_p(
            "Grounding: S satisfies a confirmed requirement · D derived "
            "· T standard · E existing · A assumption. A view that is all S "
            "is the suspicious one."))
    body.append(_p("Requirements", "Heading1"))
    for req in eng.requirements:
        body.append(_p(f"{req['id']} [{req.get('status')}/{req.get('priority')}] "
                       f"{req.get('statement', '')}"))
        for prov in req.get("provenance", []):
            body.append(_p(f"    {prov['evidence_id']} — "
                           f"{prov.get('speaker', '')}: "
                           f"\"{prov.get('quote_cached', '')}\""))
    body.append(_p("Architecture elements", "Heading1"))
    for element in eng.elements():
        grounding = ", ".join(_grounding_text(g) for g in element.grounding)
        body.append(_p(f"{element.id} ({element.level}) — {element.name}: "
                       f"{element.data.get('description', '')}  [{grounding}]"))
    if eng.decisions:
        body.append(_p("Decisions", "Heading1"))
        for decision in eng.decisions:
            body.append(_p(f"{decision['id']} {decision.get('title', '')} "
                           f"[{decision.get('status', '')}] — drivers: "
                           f"{', '.join(decision.get('drivers', []))}"))
            body.append(_p(f"    {decision.get('decision', '')}"))
    if eng.out_of_scope:
        body.append(_p("Out of scope", "Heading1"))
        for entry in eng.out_of_scope:
            body.append(_p(f"{entry['req']} — {entry['rationale']} "
                           f"({entry['decided_by']}, {entry['date']})"))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document {_NS}><w:body>{"".join(body)}'
                f'</w:body></w:document>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>')
    styles = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{_W}">'
        f'<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
        f'<w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        f'<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        f'</w:styles>')
    return canon.deterministic_zip([
        ("[Content_Types].xml", content_types.encode("utf-8")),
        ("_rels/.rels", rels.encode("utf-8")),
        ("word/_rels/document.xml.rels", doc_rels.encode("utf-8")),
        ("word/document.xml", document.encode("utf-8")),
        ("word/styles.xml", styles.encode("utf-8")),
    ])


# --- Jira ------------------------------------------------------------------

def _jira(eng: Engagement) -> bytes:
    """Idempotent upsert payloads keyed by the element's immutable uid.

    Not a delta: the desired ticket state is a pure function of the model, and
    the target system reconciles by external_id. Hashing the uid rather than the
    renameable id is what stops a rename from orphaning a ticket and silently
    creating a duplicate.
    """
    tickets = []
    for element in eng.elements():
        reqs = [g["req"] for g in element.grounding if g.get("kind") == "satisfies"]
        quotes = []
        for rid in reqs:
            req = eng.requirement_by_id(rid)
            if req:
                quotes += [f'{rid}: "{p.get("quote_cached", "")}" '
                           f'({p.get("speaker", "")}, {p["evidence_id"]})'
                           for p in req.get("provenance", [])]
        tickets.append({
            "external_id": hashlib.sha256(element.uid.encode()).hexdigest()[:24],
            "summary": f"[{element.level}] {element.name}",
            "description": element.data.get("description", ""),
            "grounding": [_grounding_text(g) for g in element.grounding],
            "requirements": reqs,
            "evidence": quotes,
        })
    return canon.canonical_json(
        {"schema_version": eng.model.get("schema_version"),
         "tickets": sorted(tickets, key=lambda t: t["external_id"])}).encode("utf-8")


# --- orchestration ---------------------------------------------------------

def render_all(eng: Engagement) -> dict:
    people = [(e, "person") for e in eng.elements() if e.level == "person"]
    systems = [(e, _kind(e)) for e in eng.elements() if e.level == "system"]
    containers = [(e, "container") for e in eng.elements() if e.level == "container"]
    external = [(e, k) for e, k in systems if k == "system_ext"]

    context_nodes = people + systems
    container_nodes = people + external + containers
    context_ids = {e.id for e, _ in context_nodes}
    container_ids = {e.id for e, _ in container_nodes}
    context_edges = [r for r in eng.relationships
                     if r["source"] in context_ids and r["destination"] in context_ids]
    container_edges = [r for r in eng.relationships
                       if r["source"] in container_ids
                       and r["destination"] in container_ids]

    title = eng.model.get("workspace", {}).get("name", "")
    docx_views = [("System Context", context_nodes, context_edges),
                  ("Containers", container_nodes, container_edges)]
    outputs = {
        "c4-context.svg": _svg(f"{title} — System Context", context_nodes, context_edges),
        "c4-container.svg": _svg(f"{title} — Containers", container_nodes, container_edges),
        "c4-context.puml": _puml(f"{title} — System Context", "context", context_nodes, context_edges),
        "c4-container.puml": _puml(f"{title} — Containers", "container", container_nodes, container_edges),
        "c4-context.mmd": _mermaid(f"{title} — System Context", "context", context_nodes, context_edges),
        "c4-container.mmd": _mermaid(f"{title} — Containers", "container", container_nodes, container_edges),
        "model.drawio": _drawio([("System Context", context_nodes, context_edges),
                                 ("Containers", container_nodes, container_edges)]),
        "traceability.md": _traceability_md(eng),
        "traceability.csv": _traceability_csv(eng),
        "architecture.docx": _docx(eng, docx_views),
        "jira-tickets.json": _jira(eng),
    }
    manifest = {
        "renderer_version": RENDERER_VERSION,
        "schema_version": eng.model.get("schema_version"),
        "outputs": {name: hashlib.sha256(data).hexdigest()[:16]
                    for name, data in sorted(outputs.items())},
    }
    outputs[RENDER_MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True)
                                 + "\n").encode("utf-8")
    return outputs
