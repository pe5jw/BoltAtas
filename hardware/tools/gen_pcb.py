#!/usr/bin/env python3
"""Build BoltATAS.kicad_pcb from the netlist KiCad exports from the schematic.

  stage "place":  footprints, nets, outline, keep-outs, hand-routed RF/power
                  tracks, net classes -> BoltATAS.kicad_pcb + BoltATAS.dsn
  stage "finish": import Freerouting's .ses, GND pours, fill, save, DRC

Usage:
  kicad-cli sch export netlist -o BoltATAS.net BoltATAS.kicad_sch
  python3 tools/gen_pcb.py place BoltATAS.net
  java -jar freerouting.jar -de BoltATAS.dsn -do BoltATAS.ses -mp 40
  python3 tools/gen_pcb.py finish BoltATAS.net
"""
import json
import math
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.dirname(HERE)
PCB = os.path.join(KDIR, "BoltATAS.kicad_pcb")
STDFP = os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
X0, Y0 = 50.0, 50.0          # board origin on the page
W, H = 150.0, 100.0          # board size


def V(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(X0 + x), pcbnew.FromMM(Y0 + y))


# ── placement: ref -> (x, y, rotation) in board coordinates (mm) ──
PLACE = {
    # RF band (top left): radio -> J1 -> T1 -> C1..C3 -> J2 / L1
    "J1": (5, 20, 0), "T1": (30, 20, 0),
    "C1": (53, 14, 0), "C2": (53, 20, 0), "C3": (53, 26, 0),
    "J2": (64, 20, 0), "L1": (88, 20, 270),
    "T2": (40, 56, 180),
    # bias tee cold side + motor current sense
    "C4": (67, 30.5, 90), "C5": (70.5, 30.5, 90), "D5": (63.5, 36, 90),
    "R40": (69, 38.5, 90), "U7": (76, 40, 0), "C25": (76, 36, 0), "R25": (80.5, 40, 90), "C26": (83.5, 40, 90),
    # FWD detector (left column)
    "R10": (14, 62, 90), "R11": (18.5, 65, 90), "R12": (18.5, 71, 90), "C10": (14, 75, 0),
    "U4": (12, 84, 0), "C11": (5, 82, 90), "C12": (5, 88, 90),
    "R13": (20.5, 80, 90), "C13": (24, 80, 90), "C14": (20.5, 90, 90), "R14": (24, 90, 90),
    # REF detector (under T2)
    "R20": (57, 77, 90), "R21": (52.5, 80, 90), "R22": (52.5, 86, 90), "C20": (48, 89, 0),
    "U5": (42, 93, 0), "C21": (35, 91, 90), "C22": (35, 97, 90),
    "R23": (48, 81, 90), "C23": (44.5, 81, 90), "C24": (51, 96, 90), "R24": (54.5, 96, 90),
    # relays (K1 COM pad at the given point), drivers, indicators
    "K1": (64, 52, 0), "K2": (64, 72, 0),
    "D1": (60.5, 52, 90), "D2": (60.5, 72, 90),
    "Q1": (85, 59, 0), "R42": (88, 52, 0), "R43": (88, 55, 0),
    "Q2": (85, 79, 0), "R44": (88, 72, 0), "R45": (88, 75, 0),
    "R41": (84, 66, 90),
    "R46": (70, 90.5, 0), "LED2": (69, 96, 0), "R47": (79, 90.5, 0), "LED3": (78, 96, 0),
    # power
    "J3": (108, 6, 0), "F1": (108.5, 16, 0), "D3": (116, 16, 0), "D4": (116, 22, 0),
    "C40": (106, 26, 0), "C41": (116, 27, 0),
    "U1": (98, 40, 0), "C43": (109, 40, 0), "C44": (100.5, 44.5, 0),
    "U2": (98, 51, 0), "C45": (115, 45, 0), "C46": (109, 51, 0), "C47": (100.5, 55.5, 0),
    "U3": (98, 63, 0), "C48": (110, 59, 0), "C49": (110, 67, 0), "C50": (100.5, 70, 0),
    # controller
    "U6": (135, 27.5, 180), "C51": (118.5, 52, 90), "C52": (110, 76, 0),
    "R50": (119.5, 44, 90), "J4": (119.5, 62, 0), "SW1": (125, 64, 0), "SW2": (125, 76, 0),
    "R51": (132, 91, 0), "LED1": (131, 96, 0),
    # mounting holes
    "H1": (4, 4, 0), "H2": (4, 96, 0), "H3": (146, 96, 0), "H4": (100, 96, 0),
}

# reference text offsets (board mm, from footprint origin) where the default collides
REFPOS = {"J3": (2.5, 7.5), "C48": (6.5, 0), "C49": (6.5, 0), "C46": (6.5, 0), "C43": (6.5, 0),
          "C52": (6.5, 0), "C40": (1.75, 5.6), "Q1": (1.27, 3.6), "Q2": (1.27, 3.6), "C26": (2.2, 0),
          "C51": (0, 2.7), "R43": (3.2, 0), "R45": (3.2, 0), "R41": (1.75, 0)}

# ── net classes ──
CLASSES = {
    #  name     track  clear  via   drill
    "Default": (0.30, 0.25, 0.8, 0.4),
    "Power":   (1.00, 0.30, 1.0, 0.5),
    "RF":      (2.50, 1.00, 1.2, 0.6),
    "Gnd":     (0.60, 0.25, 0.8, 0.4),
}
POWER_NETS = ["VIN_RAW", "VIN_F", "VIN", "+12V", "+8V", "+5V", "MOT_FEED", "COAX_DC", "K_CHAIN", "MOT_IDLE"]
RF_NETS = ["RF_TX", "RF_LINE", "RF_ANT"]


def net_class(name):
    n = name.lstrip("/")
    if n in RF_NETS:
        return "RF"
    if n in POWER_NETS:
        return "Power"
    if n == "GND":
        return "Gnd"
    return "Default"


# ── hand routes: (net, layer, width, [points or "REF.PAD"]) ──
HAND = [
    # RF main line, 2.5 mm, top layer
    ("RF_TX", "F", 2.5, ["J1.1", "T1.1"]),
    ("RF_LINE", "F", 2.5, ["T1.2", (49.5, 20)]),
    ("RF_LINE", "F", 1.5, [(49.5, 14), (49.5, 26)]),
    ("RF_LINE", "F", 1.5, [(49.5, 14), "C1.1"]), ("RF_LINE", "F", 1.5, [(49.5, 20), "C2.1"]),
    ("RF_LINE", "F", 1.5, [(49.5, 26), "C3.1"]),
    ("RF_LINE", "F", 1.0, [(49.5, 26), (49.5, 37), "T2.4"]),
    ("RF_ANT", "F", 1.5, ["C1.2", (56.5, 14)]), ("RF_ANT", "F", 1.5, ["C2.2", (56.5, 20)]),
    ("RF_ANT", "F", 1.5, ["C3.2", (56.5, 26)]),
    ("RF_ANT", "F", 1.5, [(56.5, 14), (56.5, 26)]),
    ("RF_ANT", "F", 2.5, [(56.5, 20), "J2.1"]),
    ("RF_ANT", "F", 1.0, [(56.5, 14), (58, 10), (68, 10), "L1.1"]),
    # sample ports
    ("FWD_PORT", "F", 0.8, ["T1.5", (37.62, 37.5), (27, 37.5), (24, 40.5), "T2.2"]),
]


def parse_netlist(path):
    txt = open(path).read()
    comps = {}
    for m in re.finditer(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)\s*\(footprint "([^"]*)"\)', txt):
        nxt = txt.find("(comp (ref", m.end())
        block = txt[m.end():nxt if nxt > 0 else len(txt)]
        ts = re.search(r'\(tstamps "([0-9a-f-]{36})"\)', block)
        comps[m.group(1)] = (m.group(2), m.group(3), ts.group(1) if ts else None)
    pins = {}
    nets = []
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)', txt):
        start = m.start()
        end = txt.find("(net (code", start + 5)
        body = txt[start:end if end > 0 else len(txt)]
        name = m.group(1)
        if name.startswith("unconnected-"):
            continue
        nets.append(name)
        for n in re.finditer(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', body):
            pins[(n.group(1), n.group(2))] = name
    return comps, nets, pins


def load_fp(fpid):
    lib, name = fpid.split(":")
    d = os.path.join(KDIR, "BoltATAS.pretty") if lib == "BoltATAS" else os.path.join(STDFP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(d, name)
    if fp is None:
        raise SystemExit("footprint not found: " + fpid)
    return fp


def layer(l):
    return pcbnew.F_Cu if l == "F" else pcbnew.B_Cu


def setup_classes(board, netmap):
    ds = board.GetDesignSettings()
    ns = ds.m_NetSettings
    objs = {}
    for name, (tw, cl, vd, vdr) in CLASSES.items():
        nc = ns.m_DefaultNetClass if name == "Default" else pcbnew.NETCLASS(name)
        nc.SetTrackWidth(pcbnew.FromMM(tw))
        nc.SetClearance(pcbnew.FromMM(cl))
        nc.SetViaDiameter(pcbnew.FromMM(vd))
        nc.SetViaDrill(pcbnew.FromMM(vdr))
        if name != "Default":
            ns.m_NetClasses[name] = nc
        objs[name] = nc
    for name, ni in netmap.items():
        ni.SetNetClass(objs[net_class(name)])
    ds.m_MinClearance = pcbnew.FromMM(0.2)
    ds.m_TrackMinWidth = pcbnew.FromMM(0.15)
    ds.m_ViasMinSize = pcbnew.FromMM(0.6)
    ds.m_MinThroughDrill = pcbnew.FromMM(0.3)
    ds.m_CopperEdgeClearance = pcbnew.FromMM(0.5)
    ds.m_HoleClearance = pcbnew.FromMM(0.25)
    return objs


def pad_pos(board, spec):
    ref, num = spec.split(".")
    fp = board.FindFootprintByReference(ref)
    pads = [p for p in fp.Pads() if p.GetNumber() == num]
    p = pads[0].GetPosition()
    return pcbnew.ToMM(p.x) - X0, pcbnew.ToMM(p.y) - Y0


def add_track(board, netmap, net, lay, width, pts):
    ni = netmap["/" + net] if "/" + net in netmap else netmap[net]
    xy = [pad_pos(board, p) if isinstance(p, str) else p for p in pts]
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(x1, y1))
        t.SetEnd(V(x2, y2))
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(layer(lay))
        t.SetNet(ni)
        t.SetLocked(True)
        board.Add(t)


def add_rect_shape(board, x1, y1, x2, y2, lay, width=0.1):
    for (a, b) in [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(*a))
        s.SetEnd(V(*b))
        s.SetLayer(lay)
        s.SetWidth(pcbnew.FromMM(width))
        board.Add(s)


def add_zone(board, pts, lay_set, net=None, keepout=False, name="", priority=0, clearance=0.4):
    z = pcbnew.ZONE(board)
    z.SetLayerSet(lay_set)
    if keepout:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowCopperPour(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
    else:
        z.SetNet(net)
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetLocalClearance(pcbnew.FromMM(clearance))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(pcbnew.FromMM(0.4))
        z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))
        z.SetAssignedPriority(priority)
    z.SetZoneName(name)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(pcbnew.FromMM(X0 + x), pcbnew.FromMM(Y0 + y))
    board.Add(z)
    return z


def lset(*layers):
    s = pcbnew.LSET()
    for l in layers:
        s.AddLayer(l)
    return s


def build_place(netfile):
    comps, nets, pins = parse_netlist(netfile)
    missing = set(comps) - set(PLACE)
    if missing:
        raise SystemExit("no placement for: " + ", ".join(sorted(missing)))
    board = pcbnew.NewBoard(PCB)
    netmap = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netmap[name] = ni
    setup_classes(board, netmap)

    for ref, (val, fpid, uuid) in sorted(comps.items()):
        fp = load_fp(fpid)
        fp.SetReference(ref)
        fp.SetValue(val)
        if uuid:                          # link to the schematic symbol (Update PCB from Schematic keeps it)
            fp.SetPath(pcbnew.KIID_PATH("/" + uuid))
            fp.SetProperty("Sheetname", "")
            fp.SetProperty("Sheetfile", "BoltATAS.kicad_sch")
        x, y, rot = PLACE[ref]
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        fp.SetFPIDAsString(fpid) if hasattr(fp, "SetFPIDAsString") else None
        lib, name = fpid.split(":")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        board.Add(fp)
        rtext = fp.Reference()
        if ref.startswith("H"):
            rtext.SetVisible(False)
        elif fp.GetPadCount() <= 3 and not ref.startswith(("U", "J", "Q", "LED")):
            rtext.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.9), pcbnew.FromMM(0.9)))
            rtext.SetTextThickness(pcbnew.FromMM(0.15))
        if ref in REFPOS:
            dx, dy = REFPOS[ref]
            rtext.SetPosition(V(x + dx, y + dy))
        for pad in fp.Pads():
            key = (ref, pad.GetNumber())
            if key in pins:
                pad.SetNet(netmap[pins[key]])

    add_rect_shape(board, 0, 0, W, H, pcbnew.Edge_Cuts, 0.1)
    # WiFi antenna end of the WT32-ETH01: no copper underneath
    add_zone(board, [(125, 48), (145, 48), (145, 60), (125, 60)], lset(pcbnew.F_Cu, pcbnew.B_Cu),
             keepout=True, name="WT32 antenna keep-out")
    for ref in ("T1", "T2"):
        x, y, _ = PLACE[ref]
        m = 4.75 + 0.8
        h = 15.25 + 0.8
        add_zone(board, [(x - m, y - h), (x + m, y - h), (x + m, y + h), (x - m, y + h)],
                 lset(pcbnew.F_Cu, pcbnew.B_Cu), keepout=True, name=ref + " slot keep-out")
    # 0.7 mm track-free frame along the board edge (router does not know edge clearance)
    e = 0.7
    for pts in ([(0, 0), (W, 0), (W, e), (0, e)], [(0, H - e), (W, H - e), (W, H), (0, H)],
                [(0, 0), (e, 0), (e, H), (0, H)], [(W - e, 0), (W, 0), (W, H), (W - e, H)]):
        z = add_zone(board, pts, lset(pcbnew.F_Cu, pcbnew.B_Cu), keepout=True, name="edge frame")
        z.SetDoNotAllowCopperPour(False)
    for net, lay, wdt, pts in HAND:
        add_track(board, netmap, net, lay, wdt, pts)

    tb = board.GetTitleBlock()
    tb.SetTitle("BoltATAS - ATAS-100 controller")
    tb.SetRevision("1.2")
    tb.SetDate("2026-11-25")
    tb.SetCompany("PE5JW")
    tb.SetComment(0, "2-layer FR4 1.6 mm, 1 oz; RF tracks 2.5 mm; GND pour both sides")
    board.SetTitleBlock(tb)

    # text
    t = pcbnew.PCB_TEXT(board)
    t.SetText("BoltATAS v1.2  PE5JW")
    t.SetPosition(V(104, 90))
    t.SetLayer(pcbnew.F_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.5), pcbnew.FromMM(1.5)))
    board.Add(t)
    for txt, x, y in [("RF IN", 5, 28.5), ("ANT", 64, 28.5), ("13.8V", 100.5, 3.2), ("TX", 5, 11.5)]:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(V(x, y))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.2), pcbnew.FromMM(1.2)))
        board.Add(t)

    pcbnew.SaveBoard(PCB, board)
    write_project_rules()                 # net class patterns live in the .kicad_pro
    board = pcbnew.LoadBoard(PCB)         # reload so the patterns apply
    dsn = PCB.replace(".kicad_pcb", ".dsn")
    ok = pcbnew.ExportSpecctraDSN(board, dsn)
    patch_dsn_classes(dsn)
    print("placed", len(comps), "footprints;", len(nets), "nets; DSN", ok)


def patch_dsn_classes(dsn):
    """KiCad 7 exports every net into kicad_default; move them into their classes."""
    txt = open(dsn).read()
    m = re.search(r'\(class kicad_default ""(.*?)\n\s*\(circuit', txt, re.S)
    names = m.group(1).split()
    groups = {}
    for n in names:
        groups.setdefault(net_class(n), []).append(n)
    def fmt(lst):
        out, line = [], ""
        for n in lst:
            q = '"%s"' % n if any(c in n for c in " ()") else n
            if len(line) + len(q) > 70:
                out.append(line)
                line = ""
            line += " " + q
        out.append(line)
        return "\n      ".join(out)
    txt = txt[:m.start(1)] + fmt(groups.get("Default", [])) + txt[m.end(1):]
    for cls in ("Gnd", "Power", "RF"):
        txt = re.sub(r'\(class %s\n' % cls, '(class %s %s\n' % (cls, fmt(groups.get(cls, []))), txt, count=1)
    open(dsn, "w").write(txt)


# ── Specctra session import ──
def sexpr(text):
    """tiny s-expression parser -> nested lists of strings"""
    tokens = re.findall(r'\(|\)|"[^"]*"|[^\s()]+', text)
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            e = stack.pop()
            stack[-1].append(e)
        else:
            stack[-1].append(t.strip('"'))
    return stack[0][0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def import_ses(board, ses):
    root = sexpr(open(ses).read())
    routes = find(root, "routes")[0]
    res = find(routes, "resolution")[0]
    scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4}[res[1]] / int(res[2])   # -> mm
    lib = find(routes, "library_out")
    via_dia = {}
    for ps in (find(lib[0], "padstack") if lib else []):
        for sh in find(ps, "shape"):
            circ = find(sh, "circle")
            if circ:
                via_dia[ps[1]] = int(circ[0][2]) * scale
    nets = board.GetNetsByName()
    ntr = nvia = 0
    for net in find(find(routes, "network_out")[0], "net"):
        ni = board.FindNet(net[1])
        if ni is None:
            print("SES net not on board:", net[1])
            continue
        for w in find(net, "wire"):
            for path in find(w, "path"):
                lay = pcbnew.F_Cu if path[1].startswith("F") else pcbnew.B_Cu
                width = int(path[2]) * scale
                nums = [int(v) for v in path[3:]]
                pts = [(nums[i] * scale, -nums[i + 1] * scale) for i in range(0, len(nums), 2)]
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
                    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
                    t.SetWidth(pcbnew.FromMM(width))
                    t.SetLayer(lay)
                    t.SetNet(ni)
                    board.Add(t)
                    ntr += 1
        for v in find(net, "via"):
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(int(v[2]) * scale), pcbnew.FromMM(-int(v[3]) * scale)))
            dia = via_dia.get(v[1], 0.8)
            via.SetWidth(pcbnew.FromMM(dia))
            via.SetDrill(pcbnew.FromMM(round(dia / 2, 2)))
            via.SetNet(ni)
            board.Add(via)
            nvia += 1
    print("imported", ntr, "track segments,", nvia, "vias")


def write_project_rules():
    pro = PCB.replace(".kicad_pcb", ".kicad_pro")
    d = json.load(open(pro))
    pats = []
    for n in RF_NETS:
        pats.append({"netclass": "RF", "pattern": "/" + n})
    for n in POWER_NETS:
        pats.append({"netclass": "Power", "pattern": ("/" + n) if not n.startswith("+") else n})
    pats.append({"netclass": "Gnd", "pattern": "GND"})
    d["net_settings"]["netclass_patterns"] = pats
    d.setdefault("meta", {})["filename"] = "BoltATAS.kicad_pro"
    json.dump(d, open(pro, "w"), indent=2)
    with open(PCB.replace(".kicad_pcb", ".kicad_dru"), "w") as f:
        f.write('(version 1)\n'
                '# RF line: up to ~190 V peak at 120 W with SWR 3\n'
                '(rule "RF to RF (only a capacitor between them)"\n  (condition "A.NetClass == \'RF\' && B.NetClass == \'RF\'")\n  (constraint clearance (min 0.3mm)))\n'
                '(rule "RF clearance"\n  (condition "A.NetClass == \'RF\' && B.NetClass != \'RF\'")\n  (constraint clearance (min 1.0mm)))\n'
                '# T2 primary pad and hot coax ends\n'
                '(rule "thermal spokes"\n  (constraint min_resolved_spokes 1))\n'
                '(rule "RF hole clearance"\n  (condition "A.NetClass == \'RF\' && B.NetClass != \'RF\'")\n  (constraint hole_clearance (min 0.8mm)))\n')


def build_finish(netfile):
    board = pcbnew.LoadBoard(PCB)
    ses = PCB.replace(".kicad_pcb", ".ses")
    import_ses(board, ses)
    gnd = board.FindNet("GND")
    outline = [(0.5, 0.5), (W - 0.5, 0.5), (W - 0.5, H - 0.5), (0.5, H - 0.5)]
    add_zone(board, outline, lset(pcbnew.B_Cu), gnd, name="GND bottom", clearance=0.4)
    add_zone(board, outline, lset(pcbnew.F_Cu), gnd, name="GND top", clearance=0.5)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    write_project_rules()
    print("finished; zones filled")


if __name__ == "__main__":
    stage, netfile = sys.argv[1], sys.argv[2]
    if stage == "place":
        build_place(netfile)
    elif stage == "finish":
        build_finish(netfile)
