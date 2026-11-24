#!/usr/bin/env python3
"""Compare the netlist KiCad exports from the schematic with the intended
part list in gen_sch.py, and run basic electrical-rule checks on pin types
(KiCad 7's CLI has no ERC)."""
import re, sys, importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g", os.path.join(HERE, "gen_sch.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
net = open(sys.argv[1]).read()
kic = {}
types = {}
for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)\)\)(?=\s*\(net|\s*\)\s*\)\s*$)', net, re.S):
    name = m.group(1).lstrip("/")
    nodes = re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)(?: \(pinfunction "[^"]*"\))? \(pintype "([^"]+)"\)', m.group(2))
    for ref, pin, t in nodes:
        kic[(ref, pin)] = name
        types.setdefault(name, []).append((ref, pin, t))
errors = 0
want = {}
for ref, lib, val, fp, x, y, pins, f in g.PARTS:
    for p, n in pins.items():
        want[(ref, p)] = n
for k, n in want.items():
    got = kic.get(k)
    if n == "NC":
        if got is None or not got.startswith("unconnected-"):
            print("NC pin not isolated:", k, got); errors += 1
    elif got != n:
        print("MISMATCH", k, "want", n, "kicad", got); errors += 1
extra = [k for k in kic if k not in want and not k[0].startswith("#")]
if extra:
    print("pins in KiCad netlist not in part list:", extra); errors += 1
DRV = {"power_out", "output"}
for name, nodes in types.items():
    if name.startswith("unconnected-"):
        continue
    real = [n for n in nodes if not n[0].startswith("#FLG")]
    flags = [1] if name in g.FLAGS else []
    ts = [t for _, _, t in real]
    outs = [n for n in real if n[2] in DRV]
    if len(real) < 2:
        print("single-pin net:", name, nodes); errors += 1
    if "power_in" in ts and not outs and not flags:
        print("power_in not driven:", name, [n for n in real if n[2] == "power_in"]); errors += 1
    if sum(1 for n in outs if n[2] == "power_out") + (1 if flags else 0) > 1 and len(outs) > 1:
        print("several power outputs on one net:", name, outs); errors += 1
    if sum(1 for n in outs if n[2] == "output") > 1:
        print("output conflict:", name, outs); errors += 1
print(f"{len(want)} pins checked, {len([t for t in types if not t.startswith('unconnected-')])} nets, {errors} errors")
sys.exit(1 if errors else 0)
