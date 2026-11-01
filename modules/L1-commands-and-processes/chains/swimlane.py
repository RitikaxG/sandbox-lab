"""Render a swimlane chain (lanes x time) to SVG. Usage: python3 swimlane.py <spec.py> <out.svg>"""
import runpy
import sys
from xml.sax.saxutils import escape

spec = runpy.run_path(sys.argv[1])
LANES = spec["LANES"]          # [(name, width)]
ROWS = spec["ROWS"]            # [(time_label, {lane_index: (text, style)})]
ARROWS = spec["ARROWS"]        # [((row, lane), (row, lane), label)]
TITLE = spec["TITLE"]
NOTE = spec.get("NOTE", "")

TIME_W = 100
PAD = 10
LINE_H = 17
TOP = 70
STYLES = {
    "": ("#ffffff", "#444444"),
    "bad": ("#fde8e8", "#b42318"),
    "key": ("#fff4d6", "#b54708"),
    "ok": ("#e7f6ec", "#067647"),
    "inf": ("#eef2ff", "#3538cd"),
}


def wrap(text, width):
    max_chars = max(10, int((width - 2 * PAD) / 7.7))
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            if len(line) + len(word) + 1 > max_chars and line:
                out.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        out.append(line)
    return out


lane_x = []
x = TIME_W
for _, w in LANES:
    lane_x.append(x)
    x += w
total_w = x + 20

row_y, row_h, boxes = [], [], {}
y = TOP + 30
for r, (_, cells) in enumerate(ROWS):
    h = 40
    for li, (text, _) in cells.items():
        h = max(h, len(wrap(text, LANES[li][1] - 16)) * LINE_H + 24)
    row_y.append(y)
    row_h.append(h)
    for li in cells:
        boxes[(r, li)] = (lane_x[li] + 8, y, LANES[li][1] - 16, h - 12)
    y += h + 14
note_lines = wrap(NOTE, total_w - 40) if NOTE else []
total_h = y + 20 + len(note_lines) * LINE_H

svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" '
       f'font-family="Helvetica, Arial, sans-serif" font-size="13">',
       '<defs><marker id="ah" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
       '<path d="M0,0 L10,4 L0,8 z" fill="#b42318"/></marker></defs>',
       f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>',
       f'<text x="20" y="32" font-size="19" font-weight="bold" fill="#111">{escape(TITLE)}</text>']
for i, (name, w) in enumerate(LANES):
    fill = "#f7f7f8" if i % 2 == 0 else "#ffffff"
    svg.append(f'<rect x="{lane_x[i]}" y="{TOP}" width="{w}" height="{y - TOP}" fill="{fill}" stroke="#d0d5dd"/>')
    svg.append(f'<text x="{lane_x[i] + w / 2}" y="{TOP + 20}" text-anchor="middle" font-weight="bold" fill="#111">{escape(name)}</text>')
svg.append(f'<text x="12" y="{TOP + 20}" font-weight="bold" fill="#111">time</text>')
svg.append(f'<line x1="{TIME_W - 8}" y1="{TOP + 30}" x2="{TIME_W - 8}" y2="{y - 6}" stroke="#98a2b3" marker-end="url(#ah)"/>')
for r, (t, _) in enumerate(ROWS):
    for k, line in enumerate(wrap(t, TIME_W)):
        svg.append(f'<text x="12" y="{row_y[r] + 18 + k * LINE_H}" fill="#475467" font-weight="bold">{escape(line)}</text>')
for (r, li), (bx, by, bw, bh) in boxes.items():
    text, style = ROWS[r][1][li]
    fill, stroke = STYLES[style]
    svg.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    for k, line in enumerate(wrap(text, bw)):
        svg.append(f'<text x="{bx + PAD}" y="{by + 18 + k * LINE_H}" fill="#111">{escape(line)}</text>')


def anchor(box, toward):
    bx, by, bw, bh = box
    cx, cy = bx + bw / 2, by + bh / 2
    tx, ty = toward
    if abs(tx - cx) > bw / 2 + 4:
        return (bx + bw if tx > cx else bx, cy)
    return (cx, by + bh if ty > cy else by)


for a, b, label in ARROWS:
    A, B = boxes[a], boxes[b]
    ca = (A[0] + A[2] / 2, A[1] + A[3] / 2)
    cb = (B[0] + B[2] / 2, B[1] + B[3] / 2)
    x1, y1 = anchor(A, cb)
    x2, y2 = anchor(B, ca)
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#b42318" stroke-width="1.8" marker-end="url(#ah)"/>')
    if label and ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 > 90:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        svg.append(f'<text x="{mx + 4}" y="{my - 4}" font-size="11" font-style="italic" fill="#b42318">{escape(label)}</text>')
for k, line in enumerate(note_lines):
    svg.append(f'<text x="20" y="{y + 14 + k * LINE_H}" font-size="12" fill="#475467">{escape(line)}</text>')
svg.append("</svg>")
open(sys.argv[2], "w").write("\n".join(svg))
