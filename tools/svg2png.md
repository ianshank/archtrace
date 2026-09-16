# Getting a PNG

`archtrace render` emits SVG, not PNG, and that is a constraint rather than an
oversight: rasterising vector graphics needs a rasteriser, every candidate
(Node, Cairo, drawio CLI, ImageMagick+RSVG, headless Chromium) is an install,
and the gate's whole premise is that it runs with none.

Rasterisation is also **not deterministic across versions** — font hinting and
anti-aliasing differ between machines — so a PNG must never enter the gated
render set. It would fail the render-freshness gate on a different laptop for
reasons nobody could diagnose. PNG is a publish-time step, outside the gate.

## Which path to use

**1. Don't. Office takes SVG directly.** Insert > Pictures in PowerPoint and
Word accepts `.svg`, and Microsoft 365 can convert it to an editable shape
(Graphics Format > Convert to Shape). This is the zero-install answer and it
keeps the diagram vector, so it stays sharp when someone projects the deck.
Try this before installing anything.

**2. draw.io desktop.** Open the generated `render/model.drawio`, File > Export
as > PNG. Also the path if you want to nudge something before a presentation —
but remember the nudge is thrown away on the next regeneration, by design. If
the position matters, put it in the model's `layout`.

**3. CI, where an install is allowed.** Add a publish job — separate from the
gate job, and never gating:

```yaml
- run: sudo apt-get install -y librsvg2-bin
- run: |
    for f in render/*.svg; do
      rsvg-convert -z 2 "$f" -o "${f%.svg}.png"
    done
- uses: actions/upload-artifact@v4
  with: { name: diagrams, path: render/*.png }
```

`-z 2` gives 2x pixel density, which is what a projector or a retina screen
needs. Do not commit the output.

**4. Headless Chromium**, if you already have Node and Playwright for other
reasons. Load the SVG in a page sized to its `width`/`height` attributes with
`deviceScaleFactor: 2` and screenshot it. Highest fidelity of the four, largest
dependency.
