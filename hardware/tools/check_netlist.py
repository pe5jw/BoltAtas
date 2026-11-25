#!/usr/bin/env python3
"""Compare the netlist KiCad extracts from the drawn schematic with the
intended pin->net map in gen_sch.py (connectivity partition, plus names of
the nets that carry a label), and run basic pin-type checks (KiCad 7's CLI
has no ERC)."""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g", os.path.join(HERE, "gen_sch.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

txt = open(sys.argv[1]).read()
kic, types = {}, {}
for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)\)\)(?=\s*\(net|\s*\)\s*\)\s*$)', txt, re.S):
    name = m.group(1).lstrip("/")
    for ref, pin, t in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)(?: \(pinfunction "[^"]*"\))? '
                                  r'\(pintype "([^"]+)"\)', m.group(2)):
        kic[(ref, pin)] = name
        types.setdefault(name, []).append((ref, pin, t))

want = {}
for ref, p in g.PARTS.items():
    for pin, net in p["pins"].items():
        want[(ref, pin)] = net
errors = 0
missing = [k for k in kic if k not in want and not k[0].startswith("#")]
if missing:
    print("pins in KiCad netlist without an intended net:", missing); errors += 1
groups = {}
for k, n in want.items():
    if n == "NC":
        if not kic.get(k, "").startswith("unconnected-"):
            print("NC pin is connected:", k, kic.get(k)); errors += 1
        continue
    groups.setdefault(n, set()).add(k)
kgroups = {}
for k, n in kic.items():
    kgroups.setdefault(n, set()).add(k)
for n, pins in groups.items():
    knames = {kic.get(k) for k in pins}
    if len(knames) != 1 or None in knames:
        print(f"net {n} is split in the drawing: {sorted(knames, key=str)}"); errors += 1
        continue
    kn = knames.pop()
    if kgroups[kn] != pins:
        print(f"net {n} ({kn}) has extra pins: {sorted(kgroups[kn] - pins)}"); errors += 1
    if (n in g.LABELED or n in g.POWER_NETS) and kn != n:
        print(f"net {n} is named {kn} in KiCad"); errors += 1

DRV = {"power_out", "output"}
for name, nodes in types.items():
    if name.startswith("unconnected-"):
        continue
    ts = [t for _, _, t in nodes]
    outs = [x for x in nodes if x[2] in DRV]
    flagged = name in g.FLAG_NETS
    if "power_in" in ts and not outs and not flagged:
        print("power_in not driven:", name); errors += 1
    if sum(1 for x in outs if x[2] == "power_out") + (1 if flagged else 0) > 1:
        print("several power outputs on one net:", name, outs); errors += 1
    if sum(1 for x in outs if x[2] == "output") > 1:
        print("output conflict:", name, outs); errors += 1
print(f"{len(want)} pins, {len(groups)} nets checked against KiCad's netlist: {errors} errors")
sys.exit(1 if errors else 0)
