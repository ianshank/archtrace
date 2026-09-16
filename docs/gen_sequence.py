#!/usr/bin/env python3
"""Emit the archtrace workflow sequence diagram as a self-contained SVG.

Documentation of the operating model, not of an engagement — so this is NOT part
of the gated render set and nothing here is verified by `archtrace check`.

Standard library only, like everything else. The .mmd next to this file is the
editable source of record (GitHub renders mermaid `sequenceDiagram` natively,
unlike the C4 extension); this exists because a diagram going into a deck needs
layout control that Mermaid does not offer.
"""

from xml.sax.saxutils import escape

LANES = [
    ("Stakeholders", "actor"),
    ("System of record\nTeams · SharePoint", "system"),
    ("Architect", "actor"),
    ("Agents\nread-only", "agent"),
    ("archtrace\ndeterministic", "tool"),
    ("Git · CI · Reviewer", "system"),
    ("Publish\nJira · Lucid · Word", "system"),
]
IDX = {"SH": 0, "SOR": 1, "AR": 2, "AG": 3, "AT": 4, "GIT": 5, "PUB": 6}

LANE_W, LANE_GAP, HEAD_H, TOP = 176, 40, 52, 66
ROW, NOTE_ROW, GATE_ROW, BAND_PAD = 40, 46, 52, 14
LEFT, RIGHT = 30, 30

FILL = {"actor": "#dbe4f0", "system": "#e6e6e6", "agent": "#efe3c9",
        "tool": "#cfe3d8"}
BANDS = {"evidence": "#eef4fa", "interpret": "#eef5ee", "gate": "#faf4ec"}
STROKE, TEXT, MUTED = "#33415c", "#16202e", "#4a5568"
GATE_FILL, GATE_STROKE = "#fdf0e6", "#b4531f"

# (kind, *args). call/ret = arrow; self = loop; note = spanning box;
# gate = full-width human-decision bar; band = phase background.
SCRIPT = [
    ("band", "evidence", "Loop 1 — after every meeting (~2 min)"),
    ("call", "SH", "SOR", "meeting recorded, consent captured"),
    ("call", "AR", "SOR", "export transcript"),
    ("call", "AR", "AT", "evidence add --authority stakeholder-confirmed"),
    ("self", "AT", "normalise (NFKC + punctuation fold), sha256"),
    ("call", "AT", "GIT", "commit MANIFEST only — id, hash, owner, retention"),
    ("note", "SOR", "GIT",
     "Recording content never enters git: a repository cannot satisfy a "
     "retention obligation, and deleting a file does not delete the blob. "
     "The repo holds claims about evidence; the content stays where its "
     "lifecycle is enforced."),
    ("endband",),

    ("band", "interpret",
     "Loop 2 — per batch (~30 min) · the only step that needs judgement"),
    ("call", "AR", "AG", "copilot --deny-tool=write,shell --allow-tool=read"),
    ("ret", "SOR", "AG", "evidence text — data, never instructions"),
    ("call", "AG", "AT", 'quote EV-004 "<fragment>"'),
    ("ret", "AT", "AG", "verifiable byte span"),
    ("ret", "AG", "AR", "proposed.json — spans, speakers, statements"),
    ("note", "AG", "AT",
     "Single agent, no debate ensemble: naming consistency collapses\n"
     "60.85 → 8.24 across three collaborative rounds."),
    ("call", "AR", "AT", "promote REQ-014   (dry run)"),
    ("ret", "AT", "AR", "statement + quote + speaker + authority tier"),
    ("gate", "HUMAN GATE — does the quote actually SUPPORT the statement?",
     "The only control for a plausible-but-wrong requirement carrying a real, "
     "correctly attributed quote. No deterministic rule reaches it."),
    ("call", "AR", "AT", "promote REQ-014 --yes"),
    ("ret", "AG", "AR", "model.json diff — grounding kinds, not invented REQs"),
    ("call", "AR", "GIT", "signed commit behind CODEOWNERS"),
    ("endband",),

    ("band", "gate", "Loop 3 — before anything leaves the repo (seconds)"),
    ("call", "AR", "AT", "make gate   (fmt · render · check)"),
    ("self", "AT", "G1 hash · G2 citation · G3 coverage · G4 grounding · G5 C4 form"),
    ("self", "AT", "G6 render freshness · G7 ADR · G9 conflicts · G11 authority · G12 NFR"),
    ("ret", "AT", "AR", "exit 1 + named rule and fix   /   exit 0"),
    ("note", "AT", "AT",
     '"Green" means grounded and internally consistent.\n'
     "It never means correct. Correctness is still the architect's."),
    ("ret", "AG", "AR", "review/advisory.md — advisory only, always exit 0"),
    ("call", "AR", "AT", "release --approved-by … --role …"),
    ("self", "AT", "refuse if the gate blocks or the tree is dirty"),
    ("call", "AT", "GIT", "release.json — commit + sha256 of every source and output"),
    ("self", "GIT", "PR: model diff reviewed · render/** collapsed"),
    ("call", "AR", "AT", "release --verify"),
    ("ret", "AT", "AR", "MATCH (byte-identical)   /   DRIFT (names what changed)"),
    ("gate", "PUBLISH ONLY ON MATCH",
     "Publishing a post-approval edit under an approved-looking provenance "
     "trail is exactly the failure this catches."),
    ("call", "AR", "PUB", "publish"),
    ("endband",),
]


def lane_x(key: str) -> int:
    return LEFT + IDX[key] * (LANE_W + LANE_GAP) + LANE_W // 2


def wrap(text: str, width: int) -> list:
    lines = []
    for para in text.split("\n"):
        words, current = para.split(), ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def build() -> str:
    width = LEFT + len(LANES) * LANE_W + (len(LANES) - 1) * LANE_GAP + RIGHT
    body, bands = [], []
    _ = width  # used by self-message overflow handling below
    y = TOP + HEAD_H + 24
    band_open = None

    for step in SCRIPT:
        kind = step[0]
        if kind == "band":
            band_open = (step[1], step[2], y - BAND_PAD)
            y += 26
            continue
        if kind == "endband":
            key, label, top = band_open
            bands.append((top, y - ROW + BAND_PAD + 12, key, label))
            band_open = None
            y += 18
            continue
        if kind == "note":
            lines = wrap(step[3], 74)
            x1, x2 = lane_x(step[1]), lane_x(step[2])
            if x1 == x2:
                x1, x2 = x1 - 240, x2 + 240
            box_w = max(x2 - x1 + 120, 300)
            box_x = max(LEFT, (x1 + x2) // 2 - box_w // 2)
            box_h = 12 + len(lines) * 14
            body.append(f'<rect x="{box_x}" y="{y - 12}" width="{box_w}" '
                        f'height="{box_h}" rx="4" fill="#fffdf2" '
                        f'stroke="#c9be8f"/>')
            ty = y + 3
            for line in lines:
                body.append(f'<text x="{box_x + 12}" y="{ty}" font-size="11" '
                            f'fill="{MUTED}">{escape(line)}</text>')
                ty += 14
            y += box_h + 14
            continue
        if kind == "gate":
            lines = wrap(step[2], 96)
            box_h = 30 + len(lines) * 13
            body.append(f'<rect x="{LEFT}" y="{y - 16}" width="{width - LEFT - RIGHT}" '
                        f'height="{box_h}" rx="5" fill="{GATE_FILL}" '
                        f'stroke="{GATE_STROKE}" stroke-width="1.6"/>')
            body.append(f'<text x="{LEFT + 14}" y="{y + 2}" font-size="12.5" '
                        f'font-weight="bold" fill="{GATE_STROKE}">'
                        f'{escape(step[1])}</text>')
            ty = y + 18
            for line in lines:
                body.append(f'<text x="{LEFT + 14}" y="{ty}" font-size="10.5" '
                            f'fill="{MUTED}">{escape(line)}</text>')
                ty += 13
            y += box_h + 14
            continue
        if kind == "self":
            x = lane_x(step[1])
            body.append(f'<path d="M {x} {y - 8} h 26 v 18 h -26" fill="none" '
                        f'stroke="{STROKE}" stroke-width="1.3"/>')
            body.append(f'<path d="M {x + 6} {y + 6} L {x} {y + 10} L {x + 6} '
                        f'{y + 14} z" fill="{STROKE}"/>')
            # Lanes near the right edge have no room on the right, so the label
            # flips to the left of the loop rather than running off the canvas.
            text_w = len(step[2]) * 6
            if x + 34 + text_w > width - RIGHT:
                anchor, tx = "end", x - 12
            else:
                anchor, tx = "start", x + 34
            body.append(f'<rect x="{tx - (text_w + 8 if anchor == "end" else 4)}" '
                        f'y="{y - 8}" width="{text_w + 12}" height="15" '
                        f'fill="#ffffff" opacity="0.9"/>')
            body.append(f'<text x="{tx}" y="{y + 4}" font-size="11" '
                        f'text-anchor="{anchor}" fill="{TEXT}">'
                        f'{escape(step[2])}</text>')
            y += ROW
            continue

        x1, x2 = lane_x(step[1]), lane_x(step[2])
        dash = ' stroke-dasharray="5 4"' if kind == "ret" else ""
        direction = 1 if x2 > x1 else -1
        tip = x2 - direction * 5
        body.append(f'<line x1="{x1}" y1="{y}" x2="{tip}" y2="{y}" '
                    f'stroke="{STROKE}" stroke-width="1.4"{dash}/>')
        body.append(f'<path d="M {tip} {y - 5} L {x2} {y} L {tip} {y + 5} z" '
                    f'fill="{STROKE}"/>')
        label = escape(step[3])
        mid = (x1 + x2) // 2
        plate = len(step[3]) * 6 + 14
        body.append(f'<rect x="{mid - plate // 2}" y="{y - 17}" width="{plate}" '
                    f'height="15" fill="#ffffff"/>')
        body.append(f'<text x="{mid}" y="{y - 6}" font-size="11" '
                    f'text-anchor="middle" fill="{TEXT}">{label}</text>')
        y += ROW

    height = y + 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="{LEFT}" y="30" font-size="17" font-weight="bold" '
           f'fill="{TEXT}">archtrace — operating model</text>',
           f'<text x="{LEFT}" y="50" font-size="11.5" fill="{MUTED}">'
           'Three loops · two human gates · no LLM in the critical path    '
           '|    solid = invocation, dashed = data returned</text>']

    for top, bottom, key, label in bands:
        out.append(f'<rect x="{LEFT - 8}" y="{top}" width="{width - LEFT - RIGHT + 16}" '
                   f'height="{bottom - top}" rx="6" fill="{BANDS[key]}"/>')
        out.append(f'<text x="{LEFT + 2}" y="{top + 17}" font-size="12" '
                   f'font-weight="bold" fill="{MUTED}">{escape(label)}</text>')

    for key, index in IDX.items():
        x = lane_x(key)
        out.append(f'<line x1="{x}" y1="{TOP + HEAD_H}" x2="{x}" y2="{height - 14}" '
                   f'stroke="#9aa5b5" stroke-width="1" stroke-dasharray="3 4"/>')

    for index, (name, kind) in enumerate(LANES):
        x = LEFT + index * (LANE_W + LANE_GAP)
        out.append(f'<rect x="{x}" y="{TOP}" width="{LANE_W}" height="{HEAD_H}" '
                   f'rx="5" fill="{FILL[kind]}" stroke="{STROKE}" '
                   f'stroke-width="1.4"/>')
        lines = name.split("\n")
        ty = TOP + (24 if len(lines) > 1 else 31)
        for i, line in enumerate(lines):
            weight = "bold" if i == 0 else "normal"
            size = 12.5 if i == 0 else 10
            out.append(f'<text x="{x + LANE_W // 2}" y="{ty}" font-size="{size}" '
                       f'font-weight="{weight}" text-anchor="middle" '
                       f'fill="{TEXT}">{escape(line)}</text>')
            ty += 15

    out.extend(body)
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import os
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "workflow-sequence.svg")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(build())
    print(f"wrote {target}")
