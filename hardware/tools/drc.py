#!/usr/bin/env python3
"""Run KiCad's DRC on BoltATAS.kicad_pcb (KiCad 7 has no DRC in kicad-cli) and summarise."""
import os, re, sys, collections
os.environ.setdefault("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
import pcbnew
KDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pcb = os.path.join(KDIR, "BoltATAS.kicad_pcb")
rpt = os.path.join(KDIR, "BoltATAS-drc.rpt")
b = pcbnew.LoadBoard(pcb)
pcbnew.WriteDRCReport(b, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
txt = open(rpt).read()
items = re.findall(r'^\[(\w+)\]:.*?Severity: (\w+)', txt, re.M | re.S)
cnt = collections.Counter(items)
for (k, sev), n in sorted(cnt.items(), key=lambda x: (x[0][1], x[0][0])):
    print(f"{sev:8s} {k:28s} {n}")
errors = sum(n for (k, sev), n in cnt.items() if sev == "error")
print("errors:", errors)
sys.exit(1 if errors else 0)
