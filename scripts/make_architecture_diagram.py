"""Generate docs/architecture/quotedesk-architecture.excalidraw (open it at https://excalidraw.com, or in VS Code
with the Excalidraw extension). Every box maps to something that exists in this repo.

    python scripts/make_architecture_diagram.py
"""
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "quotedesk-architecture.excalidraw"

INK, MUTED = "#1e1e1e", "#6b7280"
BLUE = ("#1971c2", "#d0ebff")
GREEN = ("#2f9e44", "#d3f9d8")
ORANGE = ("#e8590c", "#ffe8cc")
VIOLET = ("#6741d9", "#e5dbff")
YELLOW = ("#f08c00", "#fff3bf")
GRAY = ("#495057", "#f1f3f5")
WHITE = ("#495057", "#ffffff")

elements: list[dict] = []
by_id: dict[str, dict] = {}
_seed = random.Random(7)


def _base(kind, x, y, w, h, **kw):
    el = {"id": kw.pop("id"), "type": kind, "x": x, "y": y, "width": w, "height": h, "angle": 0,
          "strokeColor": kw.pop("stroke", INK), "backgroundColor": kw.pop("bg", "transparent"),
          "fillStyle": "solid", "strokeWidth": kw.pop("sw", 2), "strokeStyle": kw.pop("style", "solid"),
          "roughness": 0, "opacity": 100, "groupIds": [], "frameId": None, "roundness": kw.pop("roundness", None),
          "seed": _seed.randint(1, 2**31 - 1), "version": 1, "versionNonce": _seed.randint(1, 2**31 - 1),
          "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False}
    el.update(kw)
    elements.append(el)
    by_id[el["id"]] = el
    return el


def text_size(text, fs):
    lines = text.split("\n")
    return max(len(l) for l in lines) * fs * 0.56, len(lines) * fs * 1.25


def label(id, text, x, y, fs=16, color=INK, align="left", container=None, w=None, h=None):
    tw, th = text_size(text, fs)
    el = _base("text", x, y, w or tw, h or th, id=id, stroke=color, text=text, fontSize=fs, fontFamily=2,
               textAlign=align, verticalAlign="middle" if container else "top", containerId=container,
               originalText=text, autoResize=True, lineHeight=1.25)
    return el


def box(id, x, y, w, h, text, colors=WHITE, fs=16, shape="rectangle", style="solid", sw=2, dim_second=True):
    stroke, bg = colors
    el = _base(shape, x, y, w, h, id=id, stroke=stroke, bg=bg, style=style, sw=sw,
               roundness={"type": 3} if shape == "rectangle" else None)
    tw, th = text_size(text, fs)
    t = label(f"{id}-t", text, x + (w - tw) / 2, y + (h - th) / 2, fs=fs, align="center", container=id, w=tw, h=th)
    el["boundElements"].append({"type": "text", "id": t["id"]})
    return el


def arrow(id, pts, color=GRAY[0], src=None, dst=None, style="solid", sw=2):
    x0, y0 = pts[0]
    rel = [[px - x0, py - y0] for px, py in pts]
    w = max(abs(p[0]) for p in rel)
    h = max(abs(p[1]) for p in rel)
    el = _base("arrow", x0, y0, w, h, id=id, stroke=color, style=style, sw=sw, roundness=None,
               points=rel, lastCommittedPoint=None, startArrowhead=None, endArrowhead="arrow", elbowed=False,
               startBinding={"elementId": src, "focus": 0, "gap": 4} if src else None,
               endBinding={"elementId": dst, "focus": 0, "gap": 4} if dst else None)
    for sid in (src, dst):
        if sid:
            by_id[sid]["boundElements"].append({"type": "arrow", "id": id})
    return el


def note(id, text, x, y, fs=15):
    tw, th = text_size(text, fs)
    return box(id, x, y, tw + 34, th + 18, text, colors=YELLOW, fs=fs, style="dashed", sw=1)


def frame(id, x, y, w, h, title, color):
    _base("rectangle", x, y, w, h, id=id, stroke=color, style="dashed", sw=2, roundness={"type": 3})
    label(f"{id}-t", title, x + 20, y + 12, fs=20, color=color)


# ------------------------------------------------------------------ title + legend
label("title", "QuoteDesk: messy email → draft quote", 60, 22, fs=36)
label("subtitle", "fine-tuned student model  +  production harness  +  learning loop", 60, 72, fs=20, color=MUTED)
label("lg1", "━  normal flow", 1730, 28, fs=15, color=GRAY[0])
label("lg2", "━  ① student confident", 1730, 50, fs=15, color=GREEN[0])
label("lg3", "━  ② escalation / correction", 1730, 72, fs=15, color=ORANGE[0])
label("lg4", "┅  ③ learning loop", 1730, 94, fs=15, color=VIOLET[0])

# ------------------------------------------------------------------ 1. TRAINING
frame("fA", 40, 130, 2120, 190, "1 · TRAINING  (offline, one time)", GRAY[0])
box("A1", 70, 185, 250, 100, "Dataset\ncode-made labels\nGemini writes emails", GRAY)
box("A2", 370, 185, 260, 100, "Splits\ntrain 1,334 · val 150\nexam 150 · hard exam 30", GRAY)
box("A3", 680, 185, 250, 100, "LoRA fine-tune\nUnsloth · Kaggle T4 GPU\nGemma 3 270M", BLUE)
box("A4", 980, 185, 220, 100, "Hugging Face\nadapter v1", BLUE)
box("A5", 1250, 185, 270, 100, "Deployed\nCPU inference (Modal)", BLUE)
for i, (a, b) in enumerate([("A1", "A2"), ("A2", "A3"), ("A3", "A4"), ("A4", "A5")]):
    ax, bx = by_id[a], by_id[b]
    arrow(f"aA{i}", [(ax["x"] + ax["width"], 235), (bx["x"], 235)], src=a, dst=b)
note("nGemma", "Gemma + LoRA = fast, cheap student", 1580, 215)

# ------------------------------------------------------------------ 2. HARNESS
frame("fB", 40, 340, 2120, 480, "2 · HARNESS  (production, every email)", GRAY[0])
cy = 505  # row centre
box("B1", 70, 460, 120, 90, "Email", WHITE, fs=18)
box("B2", 240, 460, 190, 90, "Safety check\nlength · injection flag", WHITE)
box("B3", 480, 460, 240, 90, "Extract (student)\nGemma 3 270M + LoRA", BLUE, sw=3)
box("B4", 770, 460, 190, 90, "Validate\nschema · rules", WHITE)
box("B5", 1010, 435, 230, 140, "Router\nconfidence ≥ 0.66", YELLOW, shape="diamond", sw=3)
box("B6", 1330, 460, 230, 90, "Resolve (tools)\ncatalog · stock · pricing", GREEN, sw=3)
box("B7", 1610, 460, 150, 90, "Draft quote", WHITE)
box("B8", 1810, 460, 170, 90, "Human approval\napprove · correct", ORANGE, sw=3)
box("B9", 2050, 460, 100, 90, "Quote", GREEN, fs=18, sw=3)

for i, (a, b) in enumerate([("B1", "B2"), ("B2", "B3"), ("B3", "B4"), ("B4", "B5")]):
    ax, bx = by_id[a], by_id[b]
    arrow(f"aB{i}", [(ax["x"] + ax["width"], cy), (bx["x"], cy)], src=a, dst=b)
arrow("aB-r6", [(1240, cy), (1330, cy)], color=GREEN[0], src="B5", dst="B6", sw=3)
label("l-conf", "① confident", 1250, cy - 28, fs=13, color=GREEN[0])
arrow("aB-67", [(1560, cy), (1610, cy)], src="B6", dst="B7")
arrow("aB-78", [(1760, cy), (1810, cy)], src="B7", dst="B8")
arrow("aB-89", [(1980, cy), (2050, cy)], src="B8", dst="B9", color=GREEN[0])
label("l-appr", "approve", 1995, cy - 26, fs=13, color=GREEN[0])

# repair loop under Validate
box("B4r", 770, 625, 190, 70, "Repair\n1 retry", WHITE)
arrow("aRep1", [(830, 550), (830, 625)], src="B4", dst="B4r", color=ORANGE[0])
arrow("aRep2", [(900, 625), (900, 550)], src="B4r", dst="B4", color=ORANGE[0])
label("l-inv", "invalid", 745, 580, fs=13, color=ORANGE[0])
label("l-retry", "retry", 912, 580, fs=13, color=ORANGE[0])

# path 2: teacher fallback
box("B5g", 1010, 650, 230, 90, "Gemini 3.8 Flash\nteacher · expert fallback", VIOLET, sw=3)
arrow("aB-r5", [(1125, 575), (1125, 650)], color=ORANGE[0], src="B5", dst="B5g", sw=3)
label("l-unc", "② uncertain / invalid", 1138, 598, fs=15, color=ORANGE[0])
box("B10", 1345, 655, 200, 80, "Validate output\nsame checks", WHITE)
arrow("aB-g10", [(1240, 695), (1345, 695)], color=ORANGE[0], src="B5g", dst="B10")
arrow("aB-10r", [(1445, 655), (1445, 550)], color=ORANGE[0], src="B10", dst="B6")
label("l-valid", "validated", 1458, 596, fs=13, color=ORANGE[0])

# callouts
note("nRouter", "Router = decides when to escalate", 975, 372)
note("nTools", "Tools = catalog · inventory · pricing", 1320, 372)
note("nGemini", "Gemini = fallback / expert", 1010, 758)

# deploy link from training band into the student
arrow("aDeploy", [(1385, 285), (1385, 318), (600, 318), (600, 460)], color=BLUE[0], src="A5", dst="B3")
label("l-deploy", "serves the student", 940, 296, fs=13, color=BLUE[0])

# ------------------------------------------------------------------ 3. LEARNING LOOP
frame("fC", 40, 860, 2120, 250, "3 · LEARNING LOOP  (corrections → next version)", VIOLET[0])
box("C1", 1790, 940, 210, 95, "Human correction\nadmin · Correct result", ORANGE, sw=3)
box("C2", 1520, 940, 240, 95, "Correction dataset\nadmin only · 20 needed", VIOLET)
box("C3", 1250, 940, 240, 95, "Retrain (LoRA)\nbase data + corrections", VIOLET)
box("C4", 980, 940, 240, 95, "New LoRA version\nHugging Face tag v2", VIOLET)
box("C5", 710, 940, 240, 95, "Evaluation + gate\nsealed exam must improve", VIOLET)
box("C6", 470, 940, 210, 95, "Promote + deploy\nhot-swap · rollback", VIOLET)
arrow("aC0", [(1895, 550), (1895, 940)], color=ORANGE[0], src="B8", dst="C1", sw=3)
label("l-fix", "wrong result? fix it", 1908, 700, fs=15, color=ORANGE[0])
for i, (a, b) in enumerate([("C1", "C2"), ("C2", "C3"), ("C3", "C4"), ("C4", "C5"), ("C5", "C6")]):
    ax, bx = by_id[a], by_id[b]
    arrow(f"aC{i + 1}", [(ax["x"], 987), (bx["x"] + bx["width"], 987)], color=VIOLET[0], src=a, dst=b, style="dashed")
arrow("aC-up", [(575, 940), (575, 550)], color=VIOLET[0], src="C6", dst="B3", style="dashed", sw=3)
label("l-live", "new version goes live", 590, 760, fs=15, color=VIOLET[0])
note("nHuman", "Human corrections = future training data", 1520, 1052)

doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com", "elements": elements,
       "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"}, "files": {}}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
print(f"wrote {OUT} ({len(elements)} elements)")
