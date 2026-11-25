#!/usr/bin/env python3
"""Fabrication outputs and documentation images for BoltATAS.

  hardware/fab/BoltATAS-gerbers.zip   Gerbers (X2) + Excellon drill (PTH/NPTH separate) + job file
  hardware/fab/BoltATAS-BOM.csv       grouped BOM from the schematic netlist (Spec field = notes)
  hardware/fab/BoltATAS-pos.csv       pick & place (mm)
  docs/BoltATAS_schematic.pdf, docs/schematic.png, docs/pcb_top.png, docs/pcb_bottom.png

Needs kicad-cli (KiCad 7), rsvg-convert, pdftoppm and Pillow. Run from anywhere.
"""
import csv
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
ROOT = os.path.dirname(HW)
FAB = os.path.join(HW, "fab")
DOCS = os.path.join(ROOT, "docs")
PCB = os.path.join(HW, "BoltATAS.kicad_pcb")
SCH = os.path.join(HW, "BoltATAS.kicad_sch")
LAYERS = "F.Cu,B.Cu,F.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"


def run(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def gerbers(tmp):
    g = os.path.join(tmp, "gerbers") + os.sep
    os.makedirs(g)
    run("kicad-cli", "pcb", "export", "gerbers", "-l", LAYERS, "--subtract-soldermask", "-o", g, PCB)
    run("kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "-u", "mm", "-o", g, PCB)
    out = os.path.join(FAB, "BoltATAS-gerbers.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(g)):
            z.write(os.path.join(g, f), f)
    return out


def pos():
    out = os.path.join(FAB, "BoltATAS-pos.csv")
    run("kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", out, PCB)
    return out


def refkey(r):
    m = re.match(r"([A-Za-z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def bom(tmp):
    net = os.path.join(tmp, "bom.net")
    run("kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, SCH)
    txt = open(net).read()
    groups = OrderedDict()
    for m in re.finditer(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)\s*\(footprint "([^"]*)"\)', txt):
        end = txt.find("(comp (ref", m.end())
        block = txt[m.end():end if end > 0 else len(txt)]
        spec = re.search(r'\(field \(name "Spec"\) "([^"]*)"\)', block)
        key = (m.group(2), m.group(3).split(":")[-1], spec.group(1) if spec else "")
        groups.setdefault(key, []).append(m.group(1))
    rows = sorted(groups.items(), key=lambda kv: refkey(sorted(kv[1], key=refkey)[0]))
    out = os.path.join(FAB, "BoltATAS-BOM.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Qty", "References", "Value", "Footprint", "Notes"])
        for (val, fp, spec), refs in rows:
            refs = sorted(refs, key=refkey)
            w.writerow([len(refs), " ".join(refs), val, fp, spec])
    return out


def trim(png, bg):
    from PIL import Image, ImageChops
    im = Image.open(png).convert("RGB")
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg))
    box = diff.getbbox()
    if box:
        pad = 12
        box = (max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height))
        im.crop(box).save(png)


def images(tmp):
    pdf = os.path.join(DOCS, "BoltATAS_schematic.pdf")
    run("kicad-cli", "sch", "export", "pdf", "-o", pdf, SCH)
    run("pdftoppm", "-r", "120", "-png", "-singlefile", pdf, os.path.join(DOCS, "schematic"))
    bg = "#0b1a10"
    for name, layers, extra in (("pcb_top", "F.Cu,F.Silkscreen,F.Mask,Edge.Cuts", []),
                                ("pcb_bottom", "B.Cu,B.Silkscreen,B.Mask,Edge.Cuts", ["--mirror"])):
        svg = os.path.join(tmp, name + ".svg")
        run("kicad-cli", "pcb", "export", "svg", "--page-size-mode", "2", "--exclude-drawing-sheet",
            "-l", layers, *extra, "-o", svg, PCB)
        png = os.path.join(DOCS, name + ".png")
        run("rsvg-convert", "-w", "1800", "-b", bg, svg, "-o", png)
        trim(png, (0x0b, 0x1a, 0x10))
    shutil.copy(os.path.join(HW, "BoltATAS-drc.rpt"), os.path.join(DOCS, "BoltATAS-drc.rpt"))


if __name__ == "__main__":
    os.makedirs(FAB, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for f in (gerbers(tmp), pos(), bom(tmp)):
            print("wrote", os.path.relpath(f, ROOT))
        images(tmp)
        print("wrote docs/ (schematic pdf/png, pcb_top/bottom png, drc report)")
