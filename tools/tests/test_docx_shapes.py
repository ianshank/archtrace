"""Tests for the DrawingML diagram emitter.

A malformed shape does not raise — Word simply refuses to open the file, and the
gate would happily pass a document nobody can read. So these tests assert on the
XML that actually ships: it parses, every shape the model implies is present,
the geometry is inside the envelope Word accepts, and the bytes are identical
across runs.

Standard library only; run with `python3 -m unittest`.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import docx_shapes
from archtrace.model import Engagement
from archtrace.renders import MAX_DOCX_ID_STRIDE, render_all

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}


class _Element:
    """The minimum an element needs to expose for the emitter."""

    def __init__(self, eid, name, x, y, grounding=(), data=None):
        self.id = eid
        self.name = name
        self.layout = {"x": x, "y": y}
        self.grounding = list(grounding)
        self.data = data or {}


def _wrap(text, width):
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def _boundary(cx, cy, tx, ty, pad=6):
    return cx, cy


BADGES = {"satisfies": ("S", "#2f6b4f"), "derived": ("D", "#3b5a7a"),
          "standard": ("T", "#6b5a2f"), "existing": ("E", "#5a5a5a"),
          "assumption": ("A", "#9a4b2f")}

FILLS = {"person": "#dbe4f0", "system": "#c7d7ee", "container": "#cfe3d8"}


def _diagram(nodes, edges, **overrides):
    kwargs = {"box_w": 180, "box_h": 90, "margin": 30, "fill_by_kind": FILLS,
              "stroke": "#33415c", "badge_by_kind": BADGES, "wrap": _wrap,
              "title_chars": 22, "chars_per_line": 30, "boundary": _boundary}
    kwargs.update(overrides)
    return docx_shapes.diagram(nodes, edges, **kwargs)


def _parse(fragment):
    """Parse a bare `<w:p>` by supplying the namespace declarations."""
    decls = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NS.items())
    return ET.fromstring(f"<root {decls}>{fragment}</root>")


class EmitterShape(unittest.TestCase):
    def test_no_nodes_emits_nothing(self):
        """A narrative-only document must still render, not crash."""
        self.assertEqual(_diagram([], []), "")

    def test_every_node_and_edge_becomes_a_shape(self):
        nodes = [(_Element("A", "Alpha", 0, 0), "system"),
                 (_Element("B", "Beta", 300, 0), "container")]
        edges = [{"source": "A", "destination": "B", "description": "calls"}]
        root = _parse(_diagram(nodes, edges))
        shapes = root.findall(".//wps:wsp", NS)
        self.assertEqual(len(shapes), 3)
        geometries = [g.get("prst") for g in root.findall(".//a:prstGeom", NS)]
        self.assertEqual(geometries.count("roundRect"), 2)
        self.assertEqual(geometries.count("straightConnector1"), 1)

    def test_edge_to_missing_element_is_skipped(self):
        """A relationship that leaves the view must not emit a stray line."""
        nodes = [(_Element("A", "Alpha", 0, 0), "system")]
        edges = [{"source": "A", "destination": "GONE"}]
        root = _parse(_diagram(nodes, edges))
        self.assertEqual(
            [g.get("prst") for g in root.findall(".//a:prstGeom", NS)],
            ["roundRect"])

    def test_grounding_badges_are_drawn_with_their_letters(self):
        nodes = [(_Element("A", "Alpha", 0, 0,
                           grounding=[{"kind": "derived"},
                                      {"kind": "assumption"}]), "system")]
        root = _parse(_diagram(nodes, []))
        letters = [t.text for t in root.findall(".//wps:txbx//w:t", NS)]
        self.assertIn("D", letters)
        self.assertIn("A", letters)

    def test_duplicate_grounding_kinds_draw_one_badge(self):
        nodes = [(_Element("A", "Alpha", 0, 0,
                           grounding=[{"kind": "derived"},
                                      {"kind": "derived"}]), "system")]
        root = _parse(_diagram(nodes, []))
        ellipses = [g for g in root.findall(".//a:prstGeom", NS)
                    if g.get("prst") == "ellipse"]
        self.assertEqual(len(ellipses), 1)

    def test_at_most_three_badges_per_element(self):
        """Four badges would overrun the box; the SVG caps at three too."""
        nodes = [(_Element("A", "Alpha", 0, 0,
                           grounding=[{"kind": k} for k in BADGES]), "system")]
        root = _parse(_diagram(nodes, []))
        ellipses = [g for g in root.findall(".//a:prstGeom", NS)
                    if g.get("prst") == "ellipse"]
        self.assertEqual(len(ellipses), 3)

    def test_unknown_grounding_kind_draws_no_badge(self):
        nodes = [(_Element("A", "Alpha", 0, 0,
                           grounding=[{"kind": "invented"}]), "system")]
        root = _parse(_diagram(nodes, []))
        self.assertEqual([g for g in root.findall(".//a:prstGeom", NS)
                          if g.get("prst") == "ellipse"], [])


class EmitterGeometry(unittest.TestCase):
    def test_right_to_left_edge_sets_flip(self):
        """Without flips a connector runs along the wrong diagonal."""
        nodes = [(_Element("A", "Alpha", 300, 300), "system"),
                 (_Element("B", "Beta", 0, 0), "system")]
        edges = [{"source": "A", "destination": "B"}]
        root = _parse(_diagram(nodes, edges))
        connector = next(w for w in root.findall(".//wps:wsp", NS)
                         if w.find(".//a:prstGeom", NS).get("prst")
                         == "straightConnector1")
        xfrm = connector.find(".//a:xfrm", NS)
        self.assertEqual(xfrm.get("flipH"), "1")
        self.assertEqual(xfrm.get("flipV"), "1")

    def test_axis_aligned_edge_never_emits_a_zero_extent(self):
        """Word rejects cx=0 or cy=0, and a vertical edge produces exactly that."""
        nodes = [(_Element("A", "Alpha", 0, 0), "system"),
                 (_Element("B", "Beta", 0, 400), "system")]
        edges = [{"source": "A", "destination": "B"}]
        root = _parse(_diagram(nodes, edges))
        for ext in root.findall(".//a:ext", NS):
            self.assertGreaterEqual(int(ext.get("cx")), 1)
            self.assertGreaterEqual(int(ext.get("cy")), 1)

    def test_wide_diagram_is_scaled_into_the_text_column(self):
        nodes = [(_Element("A", "Alpha", 0, 0), "system"),
                 (_Element("B", "Beta", 4000, 0), "system")]
        root = _parse(_diagram(nodes, []))
        extent = root.find(".//wp:extent", NS)
        self.assertLessEqual(int(extent.get("cx")), docx_shapes.MAX_WIDTH_EMU)

    def test_narrow_diagram_is_not_scaled_up(self):
        """Scaling up a two-box diagram to fill the page looks like a mistake."""
        nodes = [(_Element("A", "Alpha", 0, 0), "system")]
        root = _parse(_diagram(nodes, []))
        extent = root.find(".//wp:extent", NS)
        expected = (180 + 30) * docx_shapes.EMU_PER_PX
        self.assertEqual(int(extent.get("cx")), expected)

    def test_child_extent_keeps_authored_coordinates(self):
        """Children stay in model units so a box moved in Word moves in the
        same units the model uses."""
        nodes = [(_Element("A", "Alpha", 0, 0), "system"),
                 (_Element("B", "Beta", 4000, 0), "system")]
        root = _parse(_diagram(nodes, []))
        xfrm = root.find(".//wpg:grpSpPr/a:xfrm", NS)
        self.assertEqual(int(xfrm.find("a:chExt", NS).get("cx")),
                         (4000 + 180 + 30) * docx_shapes.EMU_PER_PX)

    def test_shape_ids_are_unique_and_derived_from_first_id(self):
        nodes = [(_Element(f"E{i}", f"El {i}", i * 200, 0,
                           grounding=[{"kind": "derived"}]), "system")
                 for i in range(5)]
        root = _parse(_diagram(nodes, [], first_id=7000))
        ids = [int(p.get("id")) for p in root.findall(".//wps:cNvPr", NS)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i > 7000 for i in ids))


class EmitterEscaping(unittest.TestCase):
    def test_markup_in_names_does_not_break_the_document(self):
        """An element called `<b>&"x"` must not produce unparseable XML."""
        nodes = [(_Element('<b>&"x"', '<b>&"x"', 0, 0,
                           data={"description": "a & b < c",
                                 "technology": '"quoted"'}), "system")]
        root = _parse(_diagram(nodes, []))
        texts = [t.text for t in root.findall(".//w:t", NS)]
        self.assertIn('<b>&"x"', texts)


class DocxIntegration(unittest.TestCase):
    """The emitter is only useful if the document it lands in still opens."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        self.eng = Engagement.load(self.root)
        self.outputs = render_all(self.eng)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _document_xml(self, data):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("word/document.xml")

    def test_document_xml_parses(self):
        ET.fromstring(self._document_xml(self.outputs["architecture.docx"]))

    def test_required_namespaces_are_declared(self):
        """A prefix used but not declared makes Word report a corrupt file."""
        xml = self._document_xml(self.outputs["architecture.docx"]).decode()
        for uri in NS.values():
            self.assertIn(uri, xml)

    def test_both_c4_views_are_drawn(self):
        root = ET.fromstring(self._document_xml(
            self.outputs["architecture.docx"]))
        self.assertEqual(len(root.findall(".//wpg:wgp", NS)), 2)

    def test_diagram_shape_ids_are_unique_across_views(self):
        """Two views sharing an id is the classic way Word reports corruption."""
        root = ET.fromstring(self._document_xml(
            self.outputs["architecture.docx"]))
        ids = [int(p.get("id")) for p in root.findall(".//wps:cNvPr", NS)]
        ids += [int(p.get("id")) for p in root.findall(".//wp:docPr", NS)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_view_cannot_outgrow_its_id_stride(self):
        """Ids are allocated per view in fixed blocks; a view with more shapes
        than the stride would collide with the next view's block."""
        root = ET.fromstring(self._document_xml(
            self.outputs["architecture.docx"]))
        for group in root.findall(".//wpg:wgp", NS):
            self.assertLess(len(group.findall(".//wps:cNvPr", NS)),
                            MAX_DOCX_ID_STRIDE)

    def test_render_is_byte_identical_across_runs(self):
        """No clock, no id counter that survives the call, no set ordering."""
        again = render_all(Engagement.load(self.root))
        self.assertEqual(again["architecture.docx"],
                         self.outputs["architecture.docx"])

    def test_every_modelled_element_appears_in_a_diagram(self):
        """The document is the stakeholder artifact; a silently dropped box is
        the failure that matters most here."""
        root = ET.fromstring(self._document_xml(
            self.outputs["architecture.docx"]))
        names = {p.get("name") for p in root.findall(".//wps:cNvPr", NS)}
        drawn = {e.id for e in self.eng.elements() if e.id in names}
        expected = {e.id for e in self.eng.elements()
                    if e.level in ("person", "system", "container")}
        self.assertEqual(drawn, expected)


if __name__ == "__main__":
    unittest.main()
