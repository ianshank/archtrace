"""Native DrawingML diagrams for the Word deliverable. Standard library only.

Why this exists: `architecture.docx` used to be narrative and tables with the
diagram left out, which made it an appendix to the SVG rather than the artifact
stakeholders actually read. Embedding a *picture* would need a rasteriser
(Mermaid needs Node, drawio needs its CLI) and both are excluded by the
zero-dependency invariant. DrawingML shapes need neither: they are XML written
straight into `document.xml`, and they land in Word as real shapes a reader can
select, recolour and move.

Everything here is a pure function of the element layout — the same `layout.x`
and `layout.y` the SVG uses — so the Word diagram and the SVG cannot disagree,
and the render-freshness gate keeps meaning what it says.

Two deliberate limits, stated because a diagram that hides its method is worse
than no diagram:

- Text does not reflow to fit its box. Word will not measure a string for us, so
  wrapping is computed here at the same character widths the SVG uses. A very
  long element name is clipped by the box, exactly as it is in the SVG.
- Edge labels are omitted. In Word a floating label inside a shape group cannot
  be given an opaque plate without a second shape per label, and unplated labels
  land under box text. The relationship table in the document carries them.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

# A point is 12700 EMU; a pixel at the 96-dpi scale the SVG is authored in is
# 9525. Working in EMU throughout avoids a rounding drift between the two.
EMU_PER_PX = 9525

# Letter, one-inch margins: 6.5in of usable column. A group wider than this is
# scaled down as a whole rather than clipped, because a clipped C4 diagram
# silently loses elements and a small one does not.
MAX_WIDTH_EMU = 6_400_000

ARROW_LINE_EMU = 12700  # 1pt
BOX_LINE_EMU = 19050    # 1.5pt


def _px(value: float) -> int:
    return int(round(value * EMU_PER_PX))


def _rgb(colour: str) -> str:
    """'#c7d7ee' -> 'C7D7EE'. DrawingML wants bare uppercase hex."""
    return colour.lstrip("#").upper()


def _run(text: str, *, size_pt: int, bold: bool = False,
         italic: bool = False, colour: str = "16202E") -> str:
    props = [f'<w:color w:val="{colour}"/>', f'<w:sz w:val="{size_pt * 2}"/>',
             f'<w:szCs w:val="{size_pt * 2}"/>']
    if bold:
        props.insert(0, "<w:b/>")
    if italic:
        props.insert(0, "<w:i/>")
    return (f'<w:r><w:rPr>{"".join(props)}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _para(runs: str, *, align: str = "center", space_after: int = 0) -> str:
    return (f'<w:p><w:pPr><w:spacing w:before="0" w:after="{space_after}" '
            f'w:line="240" w:lineRule="auto"/>'
            f'<w:jc w:val="{align}"/></w:pPr>{runs}</w:p>')


def _textbox(paragraphs: str, *, inset: bool = True) -> str:
    """Centred text inside a shape.

    `inset=False` matters for the grounding badges: a 15px circle has no room to
    give up ~3px on each side, and with the default insets Word squeezes the
    letter into an illegible smudge — which loses the one thing on the diagram
    that says whether anybody asked for the box.
    """
    pad = ('lIns="27432" tIns="18288" rIns="27432" bIns="18288"'
           if inset else 'lIns="0" tIns="0" rIns="0" bIns="0"')
    wrap = "square" if inset else "none"
    return (f'<wps:txbx><w:txbxContent>{paragraphs}</w:txbxContent></wps:txbx>'
            f'<wps:bodyPr rot="0" vertOverflow="overflow" '
            f'horzOverflow="overflow" wrap="{wrap}" {pad} '
            f'anchor="ctr" anchorCtr="1"><a:noAutofit/></wps:bodyPr>')


def _xfrm(x: int, y: int, cx: int, cy: int, *, flip_h: bool = False,
          flip_v: bool = False) -> str:
    # An extent of zero is rejected by Word; a perfectly horizontal or vertical
    # connector is the common case that produces one.
    flips = ""
    if flip_h:
        flips += ' flipH="1"'
    if flip_v:
        flips += ' flipV="1"'
    return (f'<a:xfrm{flips}><a:off x="{x}" y="{y}"/>'
            f'<a:ext cx="{max(cx, 1)}" cy="{max(cy, 1)}"/></a:xfrm>')


def _shape(shape_id: int, name: str, geometry: str, xfrm: str, *,
           fill: str | None, line: str, line_w: int, body: str = "",
           arrow: bool = False, dashed: bool = False) -> str:
    fill_xml = (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>'
                if fill else "<a:noFill/>")
    dash_xml = '<a:prstDash val="dash"/>' if dashed else ""
    head_tail = '<a:tailEnd type="triangle" w="med" len="med"/>' if arrow else ""
    # quoteattr, not escape: an element called 'the "golden" path' puts a bare
    # double quote inside an attribute and Word reports the whole document as
    # corrupt. escape() leaves quotes alone, so this is not interchangeable.
    return (
        f'<wps:wsp><wps:cNvPr id="{shape_id}" name={quoteattr(name)}/>'
        f'<wps:cNvSpPr/><wps:spPr>{xfrm}'
        f'<a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>'
        f'{fill_xml}'
        f'<a:ln w="{line_w}" cap="flat"><a:solidFill>'
        f'<a:srgbClr val="{line}"/></a:solidFill>{dash_xml}{head_tail}</a:ln>'
        f'</wps:spPr>{body}</wps:wsp>')


def _connector(shape_id: int, name: str, x1: int, y1: int, x2: int, y2: int,
               stroke: str) -> str:
    """A straight connector is positioned by its bounding box plus flips.

    DrawingML has no 'from here to there' primitive: the shape occupies the
    rectangle spanned by its endpoints and `flipH`/`flipV` choose which diagonal
    of that rectangle the line runs along.
    """
    xfrm = _xfrm(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1),
                 flip_h=x2 < x1, flip_v=y2 < y1)
    return _shape(shape_id, name, "straightConnector1", xfrm, fill=None,
                  line=stroke, line_w=ARROW_LINE_EMU, arrow=True, dashed=True)


def _badge(shape_id: int, cx: int, cy: int, letter: str, colour: str) -> str:
    """The grounding letter, as an ellipse with centred white text.

    This is the one thing in the document that must survive the trip into Word:
    the whole point of the tool is that a reader can see which boxes nobody
    asked for, and a diagram that drops the badges is just a diagram.
    """
    # Slightly larger than the SVG's 7.5px: Word's line box for a 7pt bold
    # capital is taller than the glyph, and at the SVG radius it clips the
    # letter top and bottom. Legibility beats pixel parity here.
    radius = _px(9)
    xfrm = _xfrm(cx - radius, cy - radius, radius * 2, radius * 2)
    body = _textbox(_para(_run(letter, size_pt=7, bold=True, colour="FFFFFF")),
                    inset=False)
    return _shape(shape_id, f"grounding-{letter}", "ellipse", xfrm,
                  fill=_rgb(colour), line=colour.lstrip("#").upper(),
                  line_w=ARROW_LINE_EMU, body=body)


def diagram(nodes, edges, *, box_w: int, box_h: int, margin: int,
            fill_by_kind: dict, stroke: str, badge_by_kind: dict,
            wrap, title_chars: int, chars_per_line: int,
            boundary, first_id: int = 1000, name: str = "diagram") -> str:
    """One `<w:p>` containing the whole view as a group of native shapes.

    `nodes` is the `[(Element, kind)]` shape the SVG renderer already builds, and
    the geometry helpers are passed in rather than imported so this module stays
    a leaf: it knows how to draw DrawingML, not what a C4 model is.
    """
    if not nodes:
        return ""

    width_px = max(n.layout.get("x", 0) for n, _ in nodes) + box_w + margin
    height_px = max(n.layout.get("y", 0) for n, _ in nodes) + box_h + margin
    canvas_w, canvas_h = _px(width_px), _px(height_px)

    # Scale the group, not the coordinates: children keep their authored values
    # in the child extent, and Word maps that space onto the outer extent. A
    # reader who moves a box in Word therefore moves it in the same units the
    # model uses.
    scale = min(1.0, MAX_WIDTH_EMU / canvas_w) if canvas_w else 1.0
    outer_w, outer_h = int(canvas_w * scale), int(canvas_h * scale)

    shape_id = first_id
    shapes = []

    centres = {}
    for element, _kind in nodes:
        centres[element.id] = (element.layout.get("x", 0) + box_w // 2,
                               element.layout.get("y", 0) + box_h // 2)

    # Edges first: in a DrawingML group, document order is z-order, so boxes
    # painted afterwards cover the connector tails instead of the reverse.
    for edge in edges:
        if edge["source"] not in centres or edge["destination"] not in centres:
            continue
        cx1, cy1 = centres[edge["source"]]
        cx2, cy2 = centres[edge["destination"]]
        x1, y1 = boundary(cx1, cy1, cx2, cy2)
        x2, y2 = boundary(cx2, cy2, cx1, cy1)
        shape_id += 1
        shapes.append(_connector(
            shape_id, f'{edge["source"]}->{edge["destination"]}',
            _px(x1), _px(y1), _px(x2), _px(y2), _rgb(stroke)))

    for element, kind in nodes:
        x, y = element.layout.get("x", 0), element.layout.get("y", 0)
        paragraphs = []
        for line in wrap(element.name, title_chars)[:2]:
            paragraphs.append(_para(_run(line, size_pt=10, bold=True)))
        technology = element.data.get("technology")
        if technology:
            paragraphs.append(
                _para(_run(f"[{technology}]", size_pt=8, italic=True)))
        for line in wrap(element.data.get("description", ""),
                         chars_per_line)[:3]:
            paragraphs.append(_para(_run(line, size_pt=8)))
        shape_id += 1
        shapes.append(_shape(
            shape_id, element.id, "roundRect",
            _xfrm(_px(x), _px(y), _px(box_w), _px(box_h)),
            fill=_rgb(fill_by_kind[kind]), line=_rgb(stroke),
            line_w=BOX_LINE_EMU, body=_textbox("".join(paragraphs))))

        seen = []
        for entry in element.grounding:
            badge = badge_by_kind.get(entry.get("kind", ""))
            if badge and badge not in seen:
                seen.append(badge)
        for index, (letter, colour) in enumerate(seen[:3]):
            shape_id += 1
            shapes.append(_badge(shape_id, _px(x + box_w - 14 - index * 17),
                                 _px(y + 14), letter, colour))

    group = (
        f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr>'
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{outer_w}" cy="{outer_h}"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="{canvas_w}" cy="{canvas_h}"/>'
        f'</a:xfrm></wpg:grpSpPr>{"".join(shapes)}</wpg:wgp>')

    return (
        f'<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{outer_w}" cy="{outer_h}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{first_id}" name={quoteattr(name)}/>'
        f'<wp:cNvGraphicFramePr/>'
        f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/'
        f'office/word/2010/wordprocessingGroup">{group}</a:graphicData>'
        f'</a:graphic></wp:inline></w:drawing></w:r></w:p>')
