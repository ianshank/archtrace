#!/usr/bin/env python3
"""Emit the archtrace platform architecture as a self-contained SVG.

Documentation of the system, not of an engagement — not part of the gated render
set. Standard library only.

One deliberate departure from the reference layout this imitates: external
systems are drawn as ABSENT, not as "disabled by default". Nothing is switched
off; nothing is written. A diagram that shows unbuilt adapters as dormant
features is an aspirational architecture presented as a real one, which is the
failure this whole tool exists to prevent.

No product logos are drawn. Naming a product in text is fine; reproducing its
mark is not.
"""

from xml.sax.saxutils import escape

W, H = 1680, 918

INK, MUTED, FAINT = "#16202e", "#4a5568", "#8a94a3"
BLUE, BLUE_BG, BLUE_EDGE = "#1f5f9e", "#eef4fb", "#9dbfdd"
GREEN, GREEN_BG, GREEN_EDGE = "#2f6b4f", "#f1f8f3", "#9ccbb0"
AMBER, AMBER_BG, AMBER_EDGE = "#8a5a20", "#fdf6ec", "#dfbc8a"
RED, RED_BG, RED_EDGE = "#a4302b", "#fcecea", "#e3a9a4"
CARD, CARD_EDGE = "#ffffff", "#c9d6e4"

out = []


def rect(x, y, w, h, fill, stroke, r=10, sw=1.4, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
               f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=12, fill=INK, weight="normal", anchor="start",
         style="normal"):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
               f'font-weight="{weight}" text-anchor="{anchor}" '
               f'font-style="{style}">{escape(s)}</text>')


def wrap(s, width):
    words, lines, cur = s.split(), [], ""
    for word in words:
        cand = f"{cur} {word}".strip()
        if len(cand) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def para(x, y, s, width, size=10.5, fill=MUTED, lh=13.5):
    for i, line in enumerate(wrap(s, width)):
        text(x, y + i * lh, line, size, fill)
    return y + len(wrap(s, width)) * lh


def badge(x, y, w, label, fill, stroke, fg):
    rect(x, y, w, 22, fill, stroke, r=11, sw=1.1)
    text(x + w / 2, y + 15, label, 10.5, fg, "bold", "middle")


def glyph(cx, cy, r, colour, kind="dot"):
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colour}"/>')
    if kind.isdigit():
        text(cx, cy + 5, kind, 14, "#ffffff", "bold", "middle")
    elif kind == "lock":
        out.append(f'<rect x="{cx - 5}" y="{cy - 1}" width="10" height="8" '
                   f'rx="1.5" fill="#ffffff"/>')
        out.append(f'<path d="M {cx - 3} {cy - 1} v -3 a 3 3 0 0 1 6 0 v 3" '
                   f'fill="none" stroke="#ffffff" stroke-width="1.6"/>')
    elif kind == "eye":
        out.append(f'<path d="M {cx - 7} {cy} q 7 -6 14 0 q -7 6 -14 0 z" '
                   f'fill="#ffffff"/>')
        out.append(f'<circle cx="{cx}" cy="{cy}" r="2.2" fill="{colour}"/>')
    elif kind == "check":
        out.append(f'<path d="M {cx - 5} {cy} l 3.5 3.5 l 6.5 -7" fill="none" '
                   f'stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>')
    elif kind == "doc":
        out.append(f'<rect x="{cx - 5}" y="{cy - 6}" width="10" height="12" '
                   f'rx="1.5" fill="#ffffff"/>')
        for i in range(3):
            out.append(f'<line x1="{cx - 3}" y1="{cy - 3 + i * 3}" x2="{cx + 3}" '
                       f'y2="{cy - 3 + i * 3}" stroke="{colour}" '
                       f'stroke-width="1"/>')
    elif kind == "ban":
        out.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="none" '
                   f'stroke="#ffffff" stroke-width="2"/>')
        out.append(f'<line x1="{cx - 4}" y1="{cy + 4}" x2="{cx + 4}" '
                   f'y2="{cy - 4}" stroke="#ffffff" stroke-width="2"/>')


def arrow(x1, y1, x2, y2, label=None, dash=None, colour=BLUE):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    dx, dy = x2 - x1, y2 - y1
    length = max((dx ** 2 + dy ** 2) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    tx, ty = x2 - ux * 9, y2 - uy * 9
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{tx}" y2="{ty}" stroke="{colour}" '
               f'stroke-width="2"{d}/>')
    out.append(f'<path d="M {x2} {y2} L {tx - uy * 5.5} {ty + ux * 5.5} '
               f'L {tx + uy * 5.5} {ty - ux * 5.5} z" fill="{colour}"/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lines = label.split("\n")
        plate = max(len(line) for line in lines) * 5.6 + 10
        out.append(f'<rect x="{mx - plate / 2}" y="{my - 10 * len(lines) - 4}" '
                   f'width="{plate}" height="{14 * len(lines) + 4}" '
                   f'fill="#ffffff"/>')
        for i, line in enumerate(lines):
            text(mx, my - 10 * len(lines) + 9 + i * 13, line, 10, MUTED,
                 "normal", "middle")


# --- canvas ---------------------------------------------------------------

out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">')
rect(0, 0, W, H, "#ffffff", "#ffffff", r=0, sw=0)

text(30, 46, "archtrace", 30, INK, "bold")
text(30, 72, "Evidence-grounded architecture pipeline.", 13, MUTED)
text(30, 90, "The model lives in git; everything downstream is a build output.",
     13, MUTED)
text(30, 106, "Zero runtime dependencies · 157 tests · 94% line coverage",
     11, FAINT)

# --- input & evidence -----------------------------------------------------

rect(24, 112, 300, 488, GREEN_BG, GREEN_EDGE)
text(44, 144, "Input & Evidence", 17, INK, "bold")
text(44, 164, "Untrusted. Content never enters git.", 11.5, MUTED)

TILES = [
    ("doc", "Teams transcripts · SharePoint · email",
     "Manual export today — no Graph API. Content stays in the system of "
     "record that owns its retention; only the manifest is committed."),
    ("eye", "GitHub repositories",
     "Read-only mining. Observed implementation is evidence of what exists, "
     "never of what is required."),
    ("lock", "Stakeholder documents",
     "SOW, standards, regulation. Authority requires a named owner and an "
     "effective date — “the policy says so” is not a citation."),
]
ty = 180
for kind, title, body in TILES:
    lines = wrap(body, 34)
    h = 54 + len(lines) * 13.5
    rect(44, ty, 260, h, CARD, CARD_EDGE, r=8, sw=1.2)
    glyph(68, ty + 26, 12, GREEN, kind)
    for i, line in enumerate(wrap(title, 22)):
        text(90, ty + 24 + i * 14, line, 11.5, INK, "bold")
    para(60, ty + 48 + (14 if len(wrap(title, 22)) > 1 else 0), body, 34)
    ty += h + 20

# --- human governance -----------------------------------------------------

rect(566, 16, 700, 244, GREEN_BG, GREEN_EDGE)
text(590, 48, "Human governance", 17, INK, "bold")
text(590, 68, "The only place judgement enters the pipeline", 11.5, MUTED)

rect(590, 84, 300, 118, CARD, "#9ccbb0", r=8, sw=1.3)
glyph(616, 112, 13, GREEN, "check")
text(638, 108, "Promote gate", 13, INK, "bold")
text(638, 124, "Architect confirms the quote", 10.5, MUTED)
text(638, 137, "actually supports the statement", 10.5, MUTED)
badge(606, 152, 268, "The one control no deterministic rule reaches",
      GREEN_BG, "#9ccbb0", GREEN)
text(606, 192, "Dry run first; --yes is a separate act.", 10, FAINT)

rect(942, 84, 300, 118, CARD, "#9ccbb0", r=8, sw=1.3)
glyph(968, 112, 13, GREEN, "lock")
text(990, 108, "Review + release approval", 13, INK, "bold")
text(990, 124, "CODEOWNERS, signed commits,", 10.5, MUTED)
text(990, 137, "branch protection, named approver", 10.5, MUTED)
badge(958, 152, 268, "Human approval required", GREEN_BG, "#9ccbb0", GREEN)
text(958, 192, "Refuses a blocking gate or a dirty tree.", 10, FAINT)

badge(590, 216, 400, "LLM review is advisory — always exit 0  ·  agent "
      "definitions validated deterministically",
      "#ffffff", "#9ccbb0", GREEN)
arrow(890, 143, 940, 143)

# --- core system ----------------------------------------------------------

rect(380, 292, 886, 350, BLUE_BG, BLUE_EDGE)
text(404, 326, "archtrace", 18, INK, "bold")
text(404, 348, "Deterministic core — Python standard library only. No network, "
               "no clock, no LLM.", 11.5, MUTED)

STAGES = [
    ("1", "Evidence manifest",
     "Normalise (NFKC + punctuation fold), SHA-256 the normalised text. "
     "Manifest in git; content outside it."),
    ("2", "Extraction agent",
     "Single agent, read-only by harness. Proposes verifiable byte spans. "
     "Never confirms anything."),
    ("3", "Deterministic gate",
     "G1–G13 + agent checks, fail-closed, exit code. Citation integrity, "
     "grounding kinds, render freshness."),
    ("4", "Renderer",
     "SVG · draw.io · PlantUML · Mermaid · docx · Jira payloads. A pure "
     "function of the model."),
    ("5", "Release + verify",
     "Binds approver, commit and SHA-256 of every source and output. "
     "MATCH or DRIFT before publish."),
]
sx = 404
for num, title, body in STAGES:
    rect(sx, 366, 162, 232, CARD, CARD_EDGE, r=9, sw=1.2)
    glyph(sx + 81, 400, 17, BLUE, num)
    for i, line in enumerate(wrap(title, 17)):
        text(sx + 81, 436 + i * 15, line, 12, INK, "bold", "middle")
    yy = 436 + len(wrap(title, 17)) * 15 + 8
    for i, line in enumerate(wrap(body, 21)):
        text(sx + 81, yy + i * 13, line, 10, MUTED, "normal", "middle")
    if num != "5":
        arrow(sx + 162 + 4, 500, sx + 176 - 2, 500)
    sx += 176

arrow(326, 470, 376, 470, "evidence\ninput")
arrow(1072, 262, 1072, 288, "approved\nproposal")

# --- external systems -----------------------------------------------------

rect(1300, 152, 356, 490, AMBER_BG, AMBER_EDGE)
text(1322, 186, "External systems", 17, INK, "bold")
text(1322, 206, "NOT BUILT — every hand-off is manual", 11.5, AMBER)

EXTERNAL = [
    ("Jira", "export JSON/CSV, import by hand"),
    ("Lucid · draw.io", "manual import; round-trip unverified"),
    ("SharePoint publishing", "manual upload"),
    ("Microsoft Graph / Work IQ", "not provisioned — procurement track"),
]
ey = 224
for name, note in EXTERNAL:
    rect(1322, ey, 312, 52, CARD, CARD_EDGE, r=8, sw=1.2)
    glyph(1348, ey + 26, 11, "#b8a07a", "ban")
    text(1370, ey + 22, name, 12, INK, "bold")
    text(1370, ey + 38, note, 10, MUTED)
    ey += 62

rect(1322, ey + 6, 312, 150, RED_BG, RED_EDGE, r=8, sw=1.4)
glyph(1348, ey + 34, 12, RED, "ban")
text(1370, ey + 32, "Absent, not disabled", 12.5, RED, "bold")
para(1338, ey + 60,
     "No adapter exists and nothing is switched off. Before one is written it "
     "must pass contract tests: least-privilege scopes, unauthorised access "
     "fails, dry-run mutates nothing, idempotency by external id, redacted "
     "logs, consistent state on failure.", 40, 10, RED)

arrow(1268, 470, 1296, 470)
rect(1246, 444, 72, 15, "#ffffff", "#ffffff", r=0, sw=0)
text(1282, 456, "artifacts", 10, MUTED, "normal", "middle")
out.append(f'<line x1="1266" y1="138" x2="1478" y2="138" stroke="{FAINT}" '
           f'stroke-width="1.8" stroke-dasharray="6 5"/>')
out.append(f'<line x1="1478" y1="138" x2="1478" y2="148" stroke="{FAINT}" '
           f'stroke-width="1.8" stroke-dasharray="6 5"/>')
out.append(f'<path d="M 1478 152 l -5 -7 l 10 0 z" fill="{FAINT}"/>')
text(1372, 112, "would require a separately", 10, FAINT, "normal", "middle")
text(1372, 124, "scoped, contract-tested adapter", 10, FAINT, "normal", "middle")

# --- trust boundary -------------------------------------------------------

rect(24, 680, 1632, 214, BLUE_BG, BLUE_EDGE)
glyph(760, 714, 13, BLUE, "lock")
text(784, 720, "Trust boundary", 18, BLUE, "bold")
text(840, 752, "Retrieved documents and model output are evidence, "
               "not instructions.", 14.5, INK, "bold", "middle")

PRINCIPLES = [
    ("lock", "Read-only by harness",
     "--deny-tool=write,shell. Deny beats allow. An agent denied write but "
     "given shell writes files anyway; prompt text is not a permission."),
    ("ban", "No injection detector",
     "Deliberately. It is trivially evaded and fires on ordinary meeting "
     "speech. Shipping one would be security theatre."),
    ("check", "Grounded \u2260 correct",
     "Green means grounded and internally consistent. Correctness stays with "
     "the architect, and the tool says so in its own output."),
    ("doc", "No LLM in the critical path",
     "Every agent unavailable means you author the same JSON by hand. Gate, "
     "renders and traceability all still work."),
]
px = 60
for kind, title, body in PRINCIPLES:
    glyph(px + 16, 792, 15, BLUE, kind)
    text(px + 42, 788, title, 12.5, INK, "bold")
    para(px + 42, 808, body, 40, 10.5)
    if px < 1200:
        out.append(f'<line x1="{px + 382}" y1="768" x2="{px + 382}" y2="874" '
                   f'stroke="{BLUE_EDGE}" stroke-width="1"/>')
    px += 400

out.append("</svg>")


if __name__ == "__main__":
    import os
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "architecture.svg")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"wrote {target}")
