#!/usr/bin/env python3
"""Generate printable, fold-in-half checklist cards from DA62checklists.json.

Every sheet is a landscape US Letter page printed on ONE side only. Fold it
down the middle with the print facing outwards and you get a 5.5" x 8.5"
two-sided card, ready to laminate.

Outputs (see SHEETS below):
  DA62-card-combined.pdf   Normal on the left face, Emergency on the right face
  DA62-card-normal.pdf     Normal Procedures spread over both faces
  DA62-card-emergency.pdf  Emergency Procedures spread over both faces

Usage:  python3 make_cards.py [--json DA62checklists.json] [--outdir .]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

# ---------------------------------------------------------------- page geometry

PAGE_W, PAGE_H = landscape(letter)  # 792 x 612 pt
FACE_W = PAGE_W / 2  # 396 pt = 5.5"

OUTER_MARGIN = 22.0  # 0.3" from the paper edge, clear of any printer's dead zone
FOLD_MARGIN = 13.0  # from the fold line, where nothing gets clipped
FACE_MARGIN_Y = 21.0
BOX_PAD = 6.0  # inside the border box
GUTTER = 11.0  # between columns

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FONT_I = "Helvetica-Oblique"

MIN_FONT, MAX_FONT = 4.2, 13.0
LEADER_GAP = 3.0  # blank space either side of the dot leader
MIN_LEADER = 7.0  # shortest acceptable dot leader


@dataclass(frozen=True)
class Theme:
    bar: Color  # section header bar
    accent: Color  # title bar
    warn: Color
    stripe: Color = field(default_factory=lambda: HexColor("#EFEFEF"))


THEMES = {
    "normal": Theme(bar=HexColor("#1F3864"), accent=HexColor("#1F3864"), warn=HexColor("#B00000")),
    "emergency": Theme(bar=HexColor("#8B0000"), accent=HexColor("#8B0000"), warn=HexColor("#B00000")),
}

# ---------------------------------------------------------------- content model


@dataclass(frozen=True)
class Item:
    kind: str  # section | challenge | subtitle | note | warning
    text: str
    response: str = ""
    blanks: int = 0
    indent: float = 0.0
    group: int = 0  # index of the owning checklist, used to avoid splitting


def load_groups(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text())
    return {
        "revision": data.get("description", ""),
        "groups": {g["name"]: g["checklists"] for g in data["groups"]},
    }


def entry_to_item(entry: dict, group: int) -> Item:
    kind = {
        "Challenge": "challenge",
        "Sensed": "challenge",
        "Subtitle": "subtitle",
        "Note": "note",
        "Plain Text": "note",
        "Warning": "warning",
        "Caution": "warning",
    }.get(entry["type"], "note")
    indent = 8.0 if entry.get("justification", "").startswith("indent") else 0.0
    return Item(
        kind=kind,
        text=entry.get("text", ""),
        response=entry.get("response", ""),
        blanks=int(entry.get("blanksBelow", 0)),
        indent=indent,
        group=group,
    )


def flatten(checklists: list[dict]) -> list[Item]:
    """Turn a Garmin checklist group into a flat, renderable item stream."""
    return [
        item
        for i, cl in enumerate(checklists)
        for item in [Item("section", cl["name"].upper(), group=i)]
        + [entry_to_item(e, i) for e in cl["entries"]]
    ]


# ---------------------------------------------------------------- measurement


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word wrap; never returns an empty list."""

    def fold(lines: list[str], word: str) -> list[str]:
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and stringWidth(trial, font, size) > width:
            return lines + [word]
        return lines[:-1] + [trial]

    from functools import reduce

    return reduce(fold, text.split(), [""]) or [""]


def challenge_layout(it: Item, f: float, colw: float) -> list[str]:
    """Response lines for a challenge.

    One line means "Item .... RESPONSE"; when that does not fit, the response
    moves under the item text, right-aligned, wrapped as many times as needed.
    """
    if (
        stringWidth(it.text, FONT, f)
        + stringWidth(it.response, FONT_B, f)
        + 2 * LEADER_GAP
        + MIN_LEADER
        + it.indent
        <= colw - 2
    ):
        return [it.response]
    return wrap(it.response, FONT_B, f, colw - it.indent - f - 2)


def challenge_lines(it: Item, f: float, colw: float) -> int:
    resp = challenge_layout(it, f, colw)
    return 1 if len(resp) == 1 and resp[0] == it.response and (
        stringWidth(it.text, FONT, f)
        + stringWidth(it.response, FONT_B, f)
        + 2 * LEADER_GAP
        + MIN_LEADER
        + it.indent
        <= colw - 2
    ) else 1 + len(resp)


def item_height(it: Item, f: float, colw: float) -> float:
    lead = f * 1.24
    if it.kind == "section":
        return f * 1.62 + f * 0.34
    if it.kind == "cont":
        return f * 1.45 + f * 0.24
    if it.kind == "challenge":
        return lead * challenge_lines(it, f, colw)
    if it.kind == "subtitle":
        return f * 0.45 + f * 1.34 + f * 0.12
    if it.kind == "warning":
        lines = wrap(it.text, FONT_B, f, colw - 2 * f - 4)
        return f * 0.35 + len(lines) * lead + f * 0.45 + it.blanks * lead
    lines = wrap(it.text, FONT_I, f, colw - it.indent)
    return f * 0.12 + len(lines) * lead + f * 0.22 + it.blanks * lead


def space_before(it: Item, first_in_col: bool, f: float) -> float:
    if first_in_col or it.kind != "section":
        return 0.0
    return f * 0.95


def fits_width(items: list[Item], f: float, colw: float) -> bool:
    """Challenge text and response each fit the column; headers are never clipped."""
    return all(
        max(
            [stringWidth(it.text, FONT, f) + it.indent]
            + [stringWidth(w, FONT_B, f) for w in it.response.split()]
        )
        <= colw - 4
        for it in items
        if it.kind == "challenge"
    ) and all(
        stringWidth(it.text, FONT_B, f * 1.02) <= colw - 6
        for it in items
        if it.kind == "section"
    )


# ---------------------------------------------------------------- column packing


def pack(items: list[Item], f: float, colw: float, colh: float, ncols: int):
    """Flow items into at most `ncols` columns of height `colh`.

    A checklist is never split across columns when it fits whole in an empty
    one; when it has to be split, the continuation column is labelled. Returns
    the columns, or None when the content does not fit.
    """
    names = {i.group: i.text for i in items if i.kind == "section"}
    group_h = {
        g: sum(item_height(i, f, colw) for i in items if i.group == g)
        for g in {i.group for i in items}
    }

    cols: list[list[Item]] = [[]]
    used = 0.0
    for it in items:
        gap = space_before(it, not cols[-1], f)
        need = item_height(it, f, colw) + gap
        # Keep a checklist whole: start a new column before its header when the
        # block would not fit here but would fit in a fresh column.
        whole_elsewhere = (
            it.kind == "section"
            and cols[-1]
            and used + gap + group_h[it.group] > colh
            and group_h[it.group] <= colh
        )
        if whole_elsewhere or (cols[-1] and used + need > colh):
            cols.append([])
            used = 0.0
            need = item_height(it, f, colw)
            if it.kind != "section":  # split inside a checklist: label it
                cont = Item("cont", f"{names[it.group]} (cont.)", group=it.group)
                cols[-1].append(cont)
                used += item_height(cont, f, colw)
                need = item_height(it, f, colw)
        if used + need > colh:
            return None
        cols[-1].append(it)
        used += need
        if len(cols) > ncols:
            return None
    return cols


def has_split(cols) -> bool:
    """True when some checklist is spread over more than one column."""
    return any(
        len({n for n, col in enumerate(cols) if any(i.group == g for i in col)}) > 1
        for g in {i.group for col in cols for i in col}
    )


def best_fit(items: list[Item], colw_for, colh: float, ncols_options, nfaces: int):
    """Pick the column count and font size that make the content as large as possible."""

    def largest_font(ncols: int):
        colw = colw_for(ncols)
        lo, hi, best = MIN_FONT, MAX_FONT, None
        for _ in range(40):
            mid = (lo + hi) / 2
            ok = fits_width(items, mid, colw) and pack(items, mid, colw, colh, ncols * nfaces)
            if ok:
                best, lo = mid, mid
            else:
                hi = mid
        return best, ncols

    candidates = [c for c in map(largest_font, ncols_options) if c[0]]
    if not candidates:
        raise SystemExit("content does not fit on the sheet")
    # Widest possible type wins, but fewer (wider) columns are preferred when
    # the extra column only buys a marginally bigger font.
    best = max(f for f, _ in candidates)
    font, ncols = min(
        (c for c in candidates if c[0] >= best * 0.92), key=lambda c: c[1]
    )
    colw = colw_for(ncols)

    # Balance the columns: shrink the usable height as far as the content still
    # fits, without letting a checklist be broken across columns.
    full = pack(items, font, colw, colh, ncols * nfaces)
    keep_whole = not has_split(full)

    def ok(h: float) -> bool:
        cols = pack(items, font, colw, h, ncols * nfaces)
        return bool(cols) and (not keep_whole or not has_split(cols))

    lo, hi = 0.0, colh
    for _ in range(50):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    cols = pack(items, font, colw, hi, ncols * nfaces) if ok(hi) else full
    return font, ncols, colw, cols


# ---------------------------------------------------------------- drawing


def draw_leader(c: Canvas, x1: float, x2: float, y: float, f: float) -> None:
    if x2 - x1 < MIN_LEADER:
        return
    c.saveState()
    c.setDash(0.5, 2.1)
    c.setLineWidth(0.45)
    c.setStrokeColorRGB(0.45, 0.45, 0.45)
    c.line(x1, y + f * 0.26, x2, y + f * 0.26)
    c.restoreState()


def draw_item(c: Canvas, it: Item, x: float, top: float, colw: float, f: float, th: Theme, shade: bool) -> float:
    """Draw one item with its top edge at `top`; return the new top edge."""
    lead = f * 1.24
    if it.kind == "section":
        h = f * 1.62
        c.setFillColor(th.bar)
        c.rect(x, top - h, colw, h, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont(FONT_B, f * 1.02)
        c.drawString(x + 3, top - h + f * 0.46, it.text)
        return top - h - f * 0.34

    if it.kind == "cont":
        h = f * 1.45
        c.setFillColor(th.bar)
        c.setFont(FONT_I, f * 0.92)
        c.drawString(x + 3, top - h + f * 0.46, it.text)
        c.setLineWidth(0.6)
        c.setStrokeColor(th.bar)
        c.line(x, top - h, x + colw, top - h)
        return top - h - f * 0.24

    if it.kind == "challenge":
        nlines = challenge_lines(it, f, colw)
        if shade:
            c.setFillColor(th.stripe)
            c.rect(x, top - lead * nlines, colw, lead * nlines, stroke=0, fill=1)
        base = top - lead + f * 0.30
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT, f)
        c.drawString(x + 1 + it.indent, base, it.text)
        c.setFont(FONT_B, f)
        resp_lines = challenge_layout(it, f, colw)
        for n, line in enumerate(resp_lines):
            y = base if nlines == 1 else base - lead * (n + 1)
            c.drawRightString(x + colw - 1, y, line)
        if it.response:
            first = resp_lines[0]
            y = base if nlines == 1 else base - lead
            leader_x1 = (
                x + 1 + it.indent + stringWidth(it.text, FONT, f) + LEADER_GAP
                if nlines == 1
                else x + 1 + it.indent + f
            )
            draw_leader(c, leader_x1, x + colw - 1 - stringWidth(first, FONT_B, f) - LEADER_GAP, y, f)
        return top - lead * nlines

    if it.kind == "subtitle":
        top -= f * 0.45
        h = f * 1.34
        c.setFillColorRGB(0.87, 0.87, 0.87)
        c.rect(x, top - h, colw, h, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT_B, f * 0.96)
        c.drawCentredString(x + colw / 2, top - h + f * 0.36, it.text.upper())
        return top - h - f * 0.12

    if it.kind == "warning":
        lines = wrap(it.text, FONT_B, f, colw - 2 * f - 4)
        h = f * 0.35 + len(lines) * lead + f * 0.45
        c.setFillColor(th.warn)
        c.rect(x, top - h, 2.2, h, stroke=0, fill=1)
        c.setFillColor(th.warn)
        c.setFont(FONT_B, f)
        for n, line in enumerate(lines):
            c.drawString(x + 6, top - f * 0.35 - (n + 1) * lead + f * 0.30, line)
        return top - h - it.blanks * lead

    lines = wrap(it.text, FONT_I, f, colw - it.indent)
    h = f * 0.12 + len(lines) * lead + f * 0.22
    c.setFillColorRGB(0.28, 0.28, 0.28)
    c.setFont(FONT_I, f)
    for n, line in enumerate(lines):
        c.drawString(x + 2 + it.indent, top - f * 0.12 - (n + 1) * lead + f * 0.30, line)
    return top - h - it.blanks * lead


def draw_face(
    c: Canvas,
    face: int,
    title: str,
    subtitle: str,
    footer: str,
    cols: list[list[Item]],
    font: float,
    colw: float,
    th: Theme,
) -> None:
    x0, box_w = face_box(face)
    y0, box_h = FACE_MARGIN_Y, PAGE_H - 2 * FACE_MARGIN_Y

    c.setStrokeColor(th.accent)
    c.setLineWidth(1.1)
    c.roundRect(x0, y0, box_w, box_h, 6, stroke=1, fill=0)

    title_h = 21.0
    c.setFillColor(th.accent)
    c.rect(x0 + 1, y0 + box_h - title_h - 1, box_w - 2, title_h, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(FONT_B, 12)
    c.drawString(x0 + BOX_PAD, y0 + box_h - title_h + 5, title)
    c.setFont(FONT, 7.5)
    c.drawRightString(x0 + box_w - BOX_PAD, y0 + box_h - title_h + 6, subtitle)

    foot_h = 9.0
    c.setFillColorRGB(0.45, 0.45, 0.45)
    c.setFont(FONT, 5.6)
    c.drawString(x0 + BOX_PAD, y0 + 4, footer)
    c.drawRightString(x0 + box_w - BOX_PAD, y0 + 4, "Not a substitute for the AFM")

    top0 = y0 + box_h - title_h - 6
    for n, col in enumerate(cols):
        x = x0 + BOX_PAD + n * (colw + GUTTER)
        top = top0
        shade = False
        for it in col:
            top -= space_before(it, it is col[0], font)
            shade = False if it.kind == "section" else (not shade if it.kind == "challenge" else shade)
            top = draw_item(c, it, x, top, colw, font, th, shade and it.kind == "challenge")


def draw_fold_line(c: Canvas) -> None:
    c.saveState()
    c.setDash(2.5, 3.5)
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0.72, 0.72, 0.72)
    c.line(FACE_W, 8, FACE_W, PAGE_H - 8)
    c.restoreState()
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.setFont(FONT, 5.5)
    c.saveState()
    c.translate(FACE_W - 2.5, PAGE_H / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, "F O L D")
    c.restoreState()


# ---------------------------------------------------------------- sheet builders


def face_box(face: int) -> tuple[float, float]:
    """(x, width) of a face's border box; the outer paper edge gets more margin."""
    x = OUTER_MARGIN if face == 0 else FACE_W + FOLD_MARGIN
    return x, FACE_W - OUTER_MARGIN - FOLD_MARGIN


def content_width(ncols: int) -> float:
    return (face_box(0)[1] - 2 * BOX_PAD - (ncols - 1) * GUTTER) / ncols


def column_height() -> float:
    return PAGE_H - 2 * FACE_MARGIN_Y - 21.0 - 6 - 11.0


def build_sheet(path: Path, faces: list[tuple[str, str, list[Item], tuple[int, ...]]], footer: str) -> None:
    """faces: (title, theme key, items, allowed column counts) per printed face."""
    c = Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(path.stem)
    for face, (title, theme, items, ncols_opts) in enumerate(faces):
        font, ncols, colw, cols = best_fit(items, content_width, column_height(), ncols_opts, 1)
        draw_face(c, face, title, "DA62", footer, cols, font, colw, THEMES[theme])
    draw_fold_line(c)
    c.showPage()
    c.save()


def build_spread(path: Path, title: str, theme: str, items: list[Item], ncols_opts, footer: str) -> None:
    """One group flowed across both faces of a single sheet."""
    c = Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(path.stem)
    font, ncols, colw, cols = best_fit(items, content_width, column_height(), ncols_opts, 2)
    per_face = [cols[:ncols], cols[ncols:]]
    for face, face_cols in enumerate(per_face):
        sub = "DA62" if face == 0 else "DA62  (continued)"
        draw_face(c, face, title if face == 0 else f"{title} (cont.)", sub, footer, face_cols, font, colw, THEMES[theme])
    draw_fold_line(c)
    c.showPage()
    c.save()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="DA62checklists.json", type=Path)
    ap.add_argument("--outdir", default=".", type=Path)
    args = ap.parse_args()

    loaded = load_groups(args.json)
    groups = loaded["groups"]
    footer = f"DA62 checklists rev {loaded['revision']}"

    normal = flatten(groups["Normal Procedures"])
    emergency = flatten(groups["Emergency Procedures"])

    build_sheet(
        args.outdir / "DA62-card-combined.pdf",
        [
            ("NORMAL PROCEDURES", "normal", normal, (2, 3)),
            ("EMERGENCY PROCEDURES", "emergency", emergency, (1, 2)),
        ],
        footer,
    )
    build_spread(args.outdir / "DA62-card-normal.pdf", "NORMAL PROCEDURES", "normal", normal, (2, 3), footer)
    build_spread(args.outdir / "DA62-card-emergency.pdf", "EMERGENCY PROCEDURES", "emergency", emergency, (1, 2), footer)
    print("wrote DA62-card-combined.pdf, DA62-card-normal.pdf, DA62-card-emergency.pdf")


if __name__ == "__main__":
    main()
