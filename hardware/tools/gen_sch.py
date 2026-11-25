#!/usr/bin/env python3
"""Generate BoltATAS.kicad_sch (KiCad 7) as one connected drawing.

Parts are placed by functional block and joined with real wires; net
labels only name a wire. Power rails use power symbols. Every part still
carries its intended pin->net map (PARTS), and check_netlist.py compares
that against the netlist KiCad itself extracts from the drawing, so a
mis-drawn wire is caught.

Signal flow on the sheet:
  top left      RF path: J1 -> T1 -> RF_LINE -> C1..C3 -> RF_ANT -> J2, T2, L1, COAX_DC
  middle left   REF detector, FWD detector below it
  top middle    current sense, relay drivers K1/K2
  right         WT32-ETH01, PROG header, buttons, status LED
  bottom left   power supply
"""
import os
import re
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.dirname(HERE)
STD = os.environ.get("KICAD7_SYMBOL_DIR", "/usr/share/kicad/symbols")
PROJECT = "BoltATAS"
ROOT = str(uuid.uuid5(uuid.NAMESPACE_URL, "boltatas-root"))
POWER_NETS = {"GND", "+5V", "+12V", "+8V", "+3V3"}
G = 2.54


_N = [0]


def uid(seed=None):            # deterministic ids: regenerating gives identical files (clean git diffs)
    if not seed:
        _N[0] += 1
        seed = f"boltatas-sch-auto-{_N[0]}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


# ── library access ──────────────────────────────────────────
def block_at(text, start):
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise ValueError("unbalanced")


_libcache = {}


def lib_symbol(lib_id):
    lib, name = lib_id.split(":")
    path = os.path.join(KDIR, "BoltATAS.kicad_sym") if lib == "BoltATAS" else os.path.join(STD, lib + ".kicad_sym")
    if path not in _libcache:
        _libcache[path] = open(path).read()
    text = _libcache[path]
    m = re.search(r'\n  \(symbol "%s"' % re.escape(name), text)
    if not m:
        raise KeyError(lib_id)
    blk = block_at(text, m.start() + 3)
    ext = re.search(r'\(extends "([^"]+)"\)', blk)
    if ext:
        parent = lib_symbol(lib + ":" + ext.group(1))
        pblk = parent["block"].replace('(symbol "%s:%s"' % (lib, ext.group(1)), '(symbol "%s"' % lib_id, 1)
        pblk = pblk.replace('(symbol "%s_' % ext.group(1), '(symbol "%s_' % name)
        blk = pblk
    else:
        blk = blk.replace('(symbol "%s"' % name, '(symbol "%s"' % lib_id, 1)
    pins = {}
    for pm in re.finditer(r'\(pin (\w+) \w+ \(at ([-\d.]+) ([-\d.]+) (\d+)\)', blk):
        pb = block_at(blk, pm.start())
        num = re.search(r'\(number "([^"]+)"', pb).group(1)
        pins.setdefault(num, []).append((float(pm.group(2)), float(pm.group(3)), int(pm.group(4)), pm.group(1)))
    return {"block": blk, "pins": pins}


def xf(px, py, rot, mirror):
    """symbol (y up) -> screen offset (y down) for KiCad rotation/mirror"""
    x, y = px, -py
    for _ in range((rot // 90) % 4):
        x, y = y, -x
    if mirror == "y":
        x = -x
    elif mirror == "x":
        y = -y
    return x, y


def q(v):
    return round(v * 100) / 100


# ── drawing model ───────────────────────────────────────────
PARTS = {}      # ref -> dict(lib, value, fp, x, y, rot, mirror, pins(intended), spec, refxy, valxy)
WIRES = []      # (x1, y1, x2, y2)
LABELS = []     # (name, x, y, dir)
POWERS = []     # (net, x, y, dir, show)
FLAGS = []      # (x, y)
NOCONN = []     # (x, y)
TEXTS = []      # (text, x, y, size)
LABELED = set()

R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
CP63 = "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm"
CP8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"


def place(ref, lib, value, fp, x, y, pins, rot=0, mirror=None, spec=None, refxy=None, valxy=None):
    PARTS[ref] = dict(lib=lib, value=value, fp=fp, x=x, y=y, rot=rot, mirror=mirror, pins=pins,
                      spec=spec, refxy=refxy, valxy=valxy, L=lib_symbol(lib))


def P(spec):
    """'REF.N' -> screen position of that pin's connection point"""
    ref, num = spec.split(".")
    p = PARTS[ref]
    px, py, _, _ = p["L"]["pins"][num][0]
    dx, dy = xf(px, py, p["rot"], p["mirror"])
    return q(p["x"] + dx), q(p["y"] + dy)


def pt(v):
    return P(v) if isinstance(v, str) else (q(v[0]), q(v[1]))


def W(*pts):
    pts = [pt(p) for p in pts]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x1 != x2 and y1 != y2:
            raise SystemExit(f"diagonal wire {pts}")
        if (x1, y1) != (x2, y2):
            WIRES.append((x1, y1, x2, y2))


def PWR(net, at, d, show=True):
    x, y = pt(at)
    POWERS.append((net, x, y, d, show))


def LBL(name, at, d="R"):
    x, y = pt(at)
    LABELS.append((name, x, y, d))
    LABELED.add(name)


def NC(at):
    NOCONN.append(pt(at))


def FLAG(at):
    FLAGS.append(pt(at))


def TXT(s, x, y, size=1.27):
    TEXTS.append((s, x, y, size))


# ════════════════════════════════════════════════════════════
#  A  RF path, tandem match, DC block, bias tee
# ════════════════════════════════════════════════════════════
TXT("A  RF path: tandem match, DC block, bias tee", 20.32, 27.94, 2.0)

place("J1", "Connector:Conn_Coaxial", "RF IN", "BoltATAS:Coax_Pigtail", 25.4, 45.72, {"1": "RF_TX", "2": "GND"},
      mirror="y", spec="pigtail RG-58/RG-400 to panel SO-239, from FT-897D",
      refxy=(-2.54, -5.08, None), valxy=(-2.54, -7.62, None))
place("T1", "BoltATAS:Tandem_Xfmr", "FT114-43 1T:30T", "BoltATAS:Toroid_FT114_Slot_Coax", 50.8, 50.8,
      {"1": "RF_TX", "2": "RF_LINE", "3": "GND", "4": "GND", "5": "FWD_PORT"},
      spec="current transformer: 30T 0.4 mm CuL; 1T = 60 mm RG-58/RG-400, braid to SH at end A only",
      refxy=(0, -12.7, None), valxy=(0, -10.16, None))
place("T2", "BoltATAS:Tandem_Xfmr", "FT114-43 30T:1T", "BoltATAS:Toroid_FT114_Slot_Coax", 73.66, 66.04,
      {"1": "REF_PORT", "2": "FWD_PORT", "3": "GND", "4": "RF_LINE", "5": "GND"}, rot=180,
      spec="voltage transformer: 30T PTFE/double-enamel wire (full line voltage); 1T = coax centre, braid to SH at end A only",
      refxy=(11.43, -2.54, "left"), valxy=(-3.81, 12.7, None))
for i, ref in enumerate(["C1", "C2", "C3"]):
    place(ref, "Device:C", "100n", C1206, 104.14, 45.72 + 10.16 * i, {"1": "RF_LINE", "2": "RF_ANT"}, rot=90,
          spec="X7R 100V 1206; DC block, 3 in parallel = 0.3 uF")
place("J2", "Connector:Conn_Coaxial", "ANT", "BoltATAS:Coax_Pigtail", 139.7, 45.72, {"1": "RF_ANT", "2": "GND"},
      spec="pigtail RG-58/RG-400 to panel SO-239, to ATAS-100", refxy=(2.54, -5.08, None), valxy=(2.54, -7.62, None))
place("L1", "Device:L", "240u", "BoltATAS:Toroid_FT114_Flat_Choke", 121.92, 53.34, {"1": "RF_ANT", "2": "COAX_DC"},
      spec="RF choke: 20T 0.8 mm CuL on FT114-43, single layer; |Z| >= 1.5k 1.8-30 MHz")
place("C4", "Device:C", "1n", C0805, 129.54, 69.85, {"1": "COAX_DC", "2": "GND"}, spec="C0G 100V")
place("C5", "Device:C", "100n", C0805, 137.16, 69.85, {"1": "COAX_DC", "2": "GND"}, spec="X7R 50V")
place("D5", "Device:D_Zener", "SMBJ15A", "Diode_SMD:D_SMB", 144.78, 69.85, {"1": "COAX_DC", "2": "GND"}, rot=270,
      spec="TVS on motor line", refxy=(2.54, -1.27, "left"), valxy=(2.54, 1.27, "left"))

W("J1.1", "T1.1"); LBL("RF_TX", (35.56, 45.72))
PWR("GND", "J1.2", "D")
W("T1.3", (40.64, 48.26), (40.64, 58.42)); W("T1.4", (40.64, 55.88)); PWR("GND", (40.64, 58.42), "D")
W("T1.2", "C1.1"); LBL("RF_LINE", (88.9, 45.72))
W("T2.4", (81.28, 45.72))                                   # T2 30T primary from RF_LINE ...
W("T2.5", (63.5, 60.96)); PWR("GND", (63.5, 60.96), "D")    # ... to GND
W("T1.5", (60.96, 55.88), (60.96, 71.12), "T2.2")          # FWD port: T1 30T secondary -> T2 1T
LBL("FWD_PORT", (60.96, 66.04), "U")
W("T2.3", (88.9, 68.58)); PWR("GND", (88.9, 68.58), "D")
W("T2.1", (83.82, 71.12)); LBL("REF_PORT", (83.82, 78.74), "U")
W("C1.1", "C3.1"); W("C1.2", "C3.2")                        # three caps in parallel
W("C1.2", "J2.1"); LBL("RF_ANT", (114.3, 45.72))
PWR("GND", "J2.2", "D")
W((121.92, 45.72), "L1.1")
W("L1.2", (121.92, 66.04), (156.21, 66.04)); LBL("COAX_DC", (124.46, 66.04))
for r_ in ("C4", "C5", "D5"):
    PWR("GND", r_ + ".2", "D")

# ════════════════════════════════════════════════════════════
#  B  detectors: 13 dB pad -> AD8307 (REF above, FWD below)
# ════════════════════════════════════════════════════════════
TXT("B  Detectors", 20.32, 99.06, 2.0)
TXT("13 dB pi-pad + AD8307\nREF above, FWD below", 20.32, 104.14, 1.27)


def detector(tag, n0, uref, xp, yb):
    port, adc, vd = f"{tag}_PORT", f"{tag}_ADC", f"VDET_{tag[0]}"
    det, inp, inm, ofs, out = (f"{tag}_DET", f"{tag}_INP", f"{tag}_INM", f"{tag}_OFS", f"{tag}_OUT")
    place(f"R{n0}", "Device:R", "78.7", "Resistor_SMD:R_2010_5025Metric", xp, yb + 6.35, {"1": port, "2": "GND"},
          spec="1% 0.75W 2010; 13 dB pi-pad input shunt")
    place(f"R{n0+1}", "Device:R", "105", R1206, xp + 7.62, yb, {"1": port, "2": det}, rot=90,
          spec="1% 1206; pad series", refxy=(0, -5.08, None), valxy=(0, -2.54, None))
    place(f"R{n0+2}", "Device:R", "31.6", R0805, xp + 15.24, yb + 3.81, {"1": det, "2": "GND"},
          spec="1%; pad output shunt + 50 ohm termination (78.7 || 52.3)")
    place(f"C{n0}", "Device:C", "100n", C0805, xp + 22.86, yb, {"1": det, "2": inp}, rot=90,
          refxy=(0, -5.08, None), valxy=(0, -2.54, None))
    place(uref, "BoltATAS:AD8307", "AD8307ARZ", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", xp + 40.64, yb + 2.54,
          {"8": inp, "1": inm, "3": ofs, "5": "NC", "4": out, "7": vd, "6": vd, "2": "GND"},
          refxy=(7.62, 12.7, "left"), valxy=(7.62, 15.24, "left"))
    place(f"C{n0+1}", "Device:C", "100n", C0805, xp + 27.94, yb + 8.89, {"1": inm, "2": "GND"},
          refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))
    place(f"C{n0+2}", "Device:C", "1u", C0805, xp + 35.56, yb + 13.97, {"1": ofs, "2": "GND"},
          spec="X7R; offset loop corner below 1.8 MHz (700 kHz without)",
          refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))
    place(f"R{n0+3}", "Device:R", "10", R0805, xp + 55.88, yb - 16.51, {"1": "+5V", "2": vd})
    place(f"C{n0+3}", "Device:C", "100n", C0805, xp + 50.8, yb - 8.89, {"1": vd, "2": "GND"})
    place(f"C{n0+4}", "Device:C", "100n", C0805, xp + 55.88, yb + 6.35, {"1": out, "2": "GND"},
          spec="with internal 12.5k: 1.25 ms filter")
    place(f"R{n0+4}", "Device:R", "1k", R0805, xp + 63.5, yb + 2.54, {"1": out, "2": adc}, rot=90,
          spec="ADC pin protection", refxy=(0, -5.08, None), valxy=(0, -2.54, None))
    R0, R1, R2, R3, R4 = (f"R{n0+i}" for i in range(5))
    C0, C1, C2, C3, C4 = (f"C{n0+i}" for i in range(5))
    W((xp, yb), f"{R0}.1"); W((xp, yb), f"{R1}.1"); PWR("GND", f"{R0}.2", "D")
    W(f"{R1}.2", f"{C0}.1"); PWR("GND", f"{R2}.2", "D")             # R2 hangs on this wire
    W(f"{C0}.2", f"{uref}.8")
    W(f"{uref}.1", f"{C1}.1"); PWR("GND", f"{C1}.2", "D")
    PWR("GND", f"{C2}.2", "D")                                       # C2 sits on OFS
    PWR("GND", f"{uref}.2", "D")
    NC(f"{uref}.5")
    W(f"{uref}.7", (xp + 38.1, yb - 12.7)); W(f"{uref}.6", (xp + 43.18, yb - 12.7))
    W((xp + 38.1, yb - 12.7), f"{R3}.2"); LBL(vd, (xp + 45.72, yb - 12.7))
    PWR("GND", f"{C3}.2", "D")
    PWR("+5V", f"{R3}.1", "U")
    FLAG((xp + 40.64, yb - 12.7))
    W(f"{uref}.4", f"{R4}.1"); PWR("GND", f"{C4}.2", "D")
    return P(f"{R4}.2")


ref_out = detector("REF", 20, "U5", 83.82, 104.14)
W((83.82, 71.12), (83.82, 104.14))                                   # REF_PORT down to the pad
fwd_out = detector("FWD", 10, "U4", 60.96, 154.94)
W((60.96, 71.12), (60.96, 154.94))                                   # FWD_PORT down to the pad

# ════════════════════════════════════════════════════════════
#  C  current sense + relay interlock + drivers
# ════════════════════════════════════════════════════════════
TXT("C  Motor: current sense, K1 (12 V, DOWN) -> K2 (8 V, UP) interlock", 160.02, 22.86, 2.0)

place("R40", "Device:R", "0.1", "Resistor_SMD:R_2512_6332Metric", 160.02, 66.04, {"1": "MOT_FEED", "2": "COAX_DC"},
      rot=270, spec="1% 1W 2512; motor current shunt")
place("U7", "Amplifier_Current:INA180A1", "INA180A1", "Package_TO_SOT_SMD:SOT-23-5", 175.26, 86.36,
      {"3": "MOT_FEED", "4": "COAX_DC", "5": "+5V", "2": "GND", "1": "IMOT_OUT"}, spec="20 V/V: 2 mV per mA",
      refxy=(-10.16, 7.62, "right"), valxy=(-10.16, 10.16, "right"))
place("C25", "Device:C", "100n", C0805, 187.96, 80.01, {"1": "+5V", "2": "GND"})
place("R25", "Device:R", "1k", R0805, 189.23, 96.52, {"1": "IMOT_OUT", "2": "IMOT_ADC"}, rot=90)
place("C26", "Device:C", "100n", C0805, 195.58, 100.33, {"1": "IMOT_ADC", "2": "GND"})

W("R40.1", (193.04, 66.04), (193.04, 71.12), (198.12, 71.12)); LBL("MOT_FEED", (175.26, 66.04))
W("U7.3", (165.1, 83.82), (165.1, 66.04))                      # IN+ to MOT_FEED
W("U7.4", (156.21, 88.9), "R40.2")                              # IN- to COAX_DC
W("U7.5", (172.72, 76.2), (187.96, 76.2)); PWR("+5V", (172.72, 76.2), "U")
PWR("GND", "C25.2", "D"); PWR("GND", "U7.2", "D")
W("U7.1", (182.88, 96.52), "R25.1")
PWR("GND", "C26.2", "D")


def relay(n, kref, qref, rb, rpd, dref, ledref, rled, x0, ctrl, supply, nc_net, led_val):
    """relay at (x0, 66.04) rotated 270: COM left, NC/NO right, coil on top"""
    place(kref, "Relay:SANYOU_SRD_Form_C", "SRD-05VDC-SL-C", "Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C",
          x0, 66.04, None, rot=270, refxy=(0, 13.97, None), valxy=(0, 16.51, None))
    place(qref, "Transistor_BJT:BC547", "BC547", "Package_TO_SOT_THT:TO-92_Inline_Wide", x0 - 17.78, 50.8,
          {"1": f"K{n}_DRV", "2": f"Q{n}_B", "3": "GND"}, refxy=(-5.08, -5.08, "right"), valxy=(-5.08, -7.62, "right"))
    place(rb, "Device:R", "1k", R0805, x0 - 33.02, 50.8, {"1": ctrl, "2": f"Q{n}_B"}, rot=90,
          refxy=(0, -5.08, None), valxy=(0, -2.54, None))
    place(rpd, "Device:R", "10k", R0805, x0 - 26.67, 54.61, {"1": f"Q{n}_B", "2": "GND"},
          spec="relay off during reset", refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))
    place(dref, "Device:D", "1N4148W", "Diode_SMD:D_SOD-123", x0, 55.88, {"1": "+5V", "2": f"K{n}_DRV"}, rot=180,
          refxy=(6.35, -2.54, "left"), valxy=(-1.27, -2.54, None))
    place(ledref, "Device:LED", led_val, "LED_THT:LED_D3.0mm", x0 - 3.81, 48.26,
          {"2": f"LED{n+1}_A", "1": f"K{n}_DRV"}, refxy=(0, -2.54, None), valxy=(0, -5.08, None))
    place(rled, "Device:R", "1k", R0805, x0 + 3.81, 48.26, {"1": "+5V", "2": f"LED{n+1}_A"}, rot=270,
          refxy=(0, -2.54, None), valxy=(0, -5.08, None))
    xl, xr = x0 - 7.62, x0 + 7.62
    W(f"{kref}.2", (xl, 43.18), (x0 - 15.24, 43.18), f"{qref}.1")        # coil low side -> collector
    LBL(f"K{n}_DRV", (xl, 58.42), "U")
    W((xl, 55.88), f"{dref}.2"); W(f"{dref}.1", (xr, 55.88))
    W(f"{kref}.5", f"{rled}.1"); PWR("+5V", f"{rled}.1", "U")
    PWR("GND", f"{qref}.3", "D")
    W(f"{rb}.2", f"{qref}.2"); PWR("GND", f"{rpd}.2", "D")
    PWR(supply, f"{kref}.3", "R")
    return P(f"{rb}.1")


k1_in = relay(1, "K1", "Q1", "R42", "R43", "D1", "LED2", "R46", 205.74, "K1_CTRL", "+12V", "K_CHAIN", "red")
k2_in = relay(2, "K2", "Q2", "R44", "R45", "D2", "LED3", "R47", 259.08, "K2_CTRL", "+8V", "MOT_IDLE", "yellow")
PARTS["LED2"]["spec"] = "DOWN / 12 V indicator"
PARTS["LED3"]["spec"] = "UP / 8 V indicator"
PARTS["K1"]["pins"] = {"1": "MOT_FEED", "3": "+12V", "4": "K_CHAIN", "2": "K1_DRV", "5": "+5V"}
PARTS["K2"]["pins"] = {"1": "K_CHAIN", "3": "+8V", "4": "MOT_IDLE", "2": "K2_DRV", "5": "+5V"}
PARTS["K1"]["spec"] = "K1: +12 V = whip longer (DOWN); NC feeds K2 COM = hardware interlock"
PARTS["K2"]["spec"] = "K2: +8 V = whip shorter (UP)"
W("K1.4", (248.92, 68.58), (248.92, 71.12), "K2.1"); LBL("K_CHAIN", (228.6, 68.58))
place("R41", "Device:R", "1k", R0805, 276.86, 72.39, {"1": "MOT_IDLE", "2": "GND"}, spec="idle: motor line to 0 V")
W("K2.4", "R41.1"); LBL("MOT_IDLE", (267.97, 68.58)); PWR("GND", "R41.2", "D")

# ════════════════════════════════════════════════════════════
#  E  controller
# ════════════════════════════════════════════════════════════
TXT("E  Controller WT32-ETH01", 320.04, 22.86, 2.0)
U6P = {"1": "NC", "2": "GND", "3": "+3V3", "4": "ESP_EN", "5": "K2_CTRL", "6": "LED_CTRL", "7": "BTN_DOWN",
       "8": "BTN_TUNE", "9": "GND", "10": "NC", "11": "GND", "12": "+5V", "13": "NC",
       "26": "ESP_TX", "25": "ESP_RX", "24": "ESP_IO0", "23": "GND", "22": "REF_ADC", "21": "FWD_ADC",
       "20": "BTN_UP", "19": "SWR_R", "18": "SWR_O", "17": "IMOT_ADC", "16": "K1_CTRL", "15": "SWR_G", "14": "GND"}
place("U6", "BoltATAS:WT32-ETH01", "WT32-ETH01", "BoltATAS:WT32-ETH01_Socket", 342.9, 76.2, U6P, mirror="y",
      spec="plugs into 2x PinSocket 1x13 2.54 mm", refxy=(25.4, 22.86, "left"), valxy=(25.4, 25.4, "left"))
place("C51", "Device:C", "100n", C0805, 360.68, 49.53, {"1": "+5V", "2": "GND"},
      refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))
place("C52", "Device:C_Polarized", "22u", CP63, 368.3, 49.53, {"1": "+5V", "2": "GND"}, spec="16V")
place("R50", "Device:R", "1k", R0805, 364.49, 68.58, {"1": "ESP_IO0", "2": "IO0_EXT"}, rot=90,
      spec="isolates the 50 MHz Ethernet clock on IO0 from header and button",
      refxy=(0, 2.54, None), valxy=(0, 5.08, None))
place("J4", "Connector_Generic:Conn_01x06", "PROG", "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
      396.24, 66.04, {"1": "ESP_EN", "2": "ESP_TX", "3": "ESP_RX", "4": "IO0_EXT", "5": "+3V3", "6": "GND"},
      spec="USB-serial 3.3 V: 1 EN, 2 TX, 3 RX, 4 IO0, 5 3V3 (reference), 6 GND",
      refxy=(0, -7.62, None), valxy=(0, 12.7, None))
place("SW2", "Switch:SW_Push", "RESET", "Button_Switch_THT:SW_PUSH_6mm", 378.46, 55.88, {"1": "ESP_EN", "2": "GND"},
      rot=90, refxy=(2.54, -1.27, "right"), valxy=(2.54, 1.27, "right"))
place("SW1", "Switch:SW_Push", "BOOT", "Button_Switch_THT:SW_PUSH_6mm", 378.46, 73.66, {"1": "IO0_EXT", "2": "GND"},
      rot=270, refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))

# supplies
W("U6.12", (347.98, 45.72), (368.3, 45.72)); PWR("+5V", (347.98, 45.72), "U")
PWR("GND", "C51.2", "D"); PWR("GND", "C52.2", "D")
PWR("+3V3", "U6.3", "U"); NC("U6.10")
for n in ("2", "9", "11", "14", "23"):
    W(f"U6.{n}", (P(f"U6.{n}")[0], 99.06))
W((337.82, 99.06), (347.98, 99.06)); PWR("GND", (342.9, 99.06), "D")
for n in ("1", "13"):
    NC(f"U6.{n}")
# programming side: straight to the header
W("U6.4", "J4.1"); LBL("ESP_EN", (360.68, 60.96))
W("U6.26", "J4.2"); LBL("ESP_TX", (360.68, 63.5))
W("U6.25", "J4.3"); LBL("ESP_RX", (360.68, 66.04))
W("U6.24", "R50.1"); W("R50.2", "J4.4"); LBL("IO0_EXT", (381.0, 68.58))
PWR("GND", "SW2.2", "U"); PWR("GND", "SW1.2", "D")
PWR("+3V3", "J4.5", "L"); PWR("GND", "J4.6", "L")
# relay control bus over the top of the sheet
W(k1_in, (166.37, 50.8), (166.37, 30.48), (312.42, 30.48), (312.42, 60.96), "U6.16"); LBL("K1_CTRL", (190.5, 30.48))
W(k2_in, (219.71, 50.8), (219.71, 33.02), (309.88, 33.02), (309.88, 63.5), "U6.5"); LBL("K2_CTRL", (284.48, 33.02))
# ADC lines
W("R25.2", (299.72, 96.52), (299.72, 66.04), "U6.17"); LBL("IMOT_ADC", (205.74, 96.52))
W(ref_out, (153.67, 106.68), (153.67, 111.76), (302.26, 111.76), (302.26, 68.58), "U6.22")
LBL("REF_ADC", (200.66, 111.76))
W(fwd_out, (304.8, 157.48), (304.8, 71.12), "U6.21"); LBL("FWD_ADC", (200.66, 157.48))

# ════════════════════════════════════════════════════════════
#  F  front panel: SWR LEDs, status LED, UP / DOWN / TUNE
# ════════════════════════════════════════════════════════════
TXT("F  Front panel", 330.2, 107.95, 2.0)
place("J5", "Connector_Generic:Conn_01x08", "FRONT", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
      396.24, 111.76, {"1": "GND", "2": "TUNE_SW", "3": "DOWN_SW", "4": "UP_SW", "5": "SWR_R_A", "6": "SWR_O_A",
                       "7": "SWR_G_A", "8": "LED1_A"},
      spec="front panel: 1 GND, 2 TUNE, 3 DOWN, 4 UP (switch to GND), 5 SWR red, 6 SWR orange, 7 SWR green, "
           "8 STATUS (LED anode, series R on board)", refxy=(0, -10.16, None), valxy=(0, 12.7, None))
W("J5.1", (368.3, 104.14)); PWR("GND", (368.3, 104.14), "D")

# rows, top to bottom; GPIO verticals further left for lower rows, J5 verticals further right
F_ROWS = [  # (kind, U6 pin, gpio net, label, row y, gpio x, j5 x, J5 pin, parts)
    ("btn", "8", "BTN_TUNE", "BTN_TUNE", 127.0, 322.58, 373.38, "2", ("R60", "R61", "C60", "SW5", "TUNE")),
    ("btn", "7", "BTN_DOWN", "BTN_DOWN", 144.78, 320.04, 375.92, "3", ("R62", "R63", "C61", "SW4", "DOWN")),
    ("btn", "20", "BTN_UP", "BTN_UP", 162.56, 317.5, 378.46, "4", ("R64", "R65", "C62", "SW3", "UP")),
    ("led", "19", "SWR_R", "SWR_R", 180.34, 314.96, 381.0, "5", ("R66", "LED6", "330", "red", "SWR >= 2.5")),
    ("led", "18", "SWR_O", "SWR_O", 195.58, 312.42, 383.54, "6", ("R67", "LED5", "330", "orange", "SWR 1.5 - 2.5")),
    ("led", "15", "SWR_G", "SWR_G", 210.82, 309.88, 386.08, "7", ("R68", "LED4", "330", "green", "SWR < 1.5")),
    ("led", "6", "LED_CTRL", None, 226.06, 307.34, 388.62, "8", ("R51", "LED1", "470", "green", "STATUS")),
]
for kind, upin, gnet, lbl, y, gx, jx, jpin, parts in F_ROWS:
    if kind == "btn":
        rpu, rs, c, sw, name = parts
        nn = f"{name}_SW"
        place(rs, "Device:R", "1k", R0805, 335.28, y, {"1": gnet, "2": nn}, rot=90,
              refxy=(0, -2.54, None), valxy=(0, 2.54, None))
        place(rpu, "Device:R", "10k", R0805, 345.44, y - 3.81, {"1": "+3V3", "2": nn},
              refxy=(2.54, -1.27, "left"), valxy=(2.54, 1.27, "left"))
        place(c, "Device:C", "100n", C0805, 353.06, y + 3.81, {"1": nn, "2": "GND"},
              refxy=(2.54, -1.27, "left"), valxy=(2.54, 1.27, "left"))
        place(sw, "Switch:SW_Push", name, "Button_Switch_THT:SW_PUSH_6mm", 363.22, y + 5.08, {"1": nn, "2": "GND"},
              rot=270, refxy=(2.54, -1.27, "left"), valxy=(2.54, 1.27, "left"), spec=f"{name} button")
        W(f"{rs}.2", (jx, y), (jx, P(f"J5.{jpin}")[1]), f"J5.{jpin}")
        PWR("+3V3", f"{rpu}.1", "U"); PWR("GND", f"{c}.2", "D"); PWR("GND", f"{sw}.2", "D")
        W(f"U6.{upin}", (gx, P(f"U6.{upin}")[1]), (gx, y), f"{rs}.1")
    else:
        r, led, rv, col, spec = parts
        nn = f"{led}_A" if led == "LED1" else f"{gnet}_A"
        place(r, "Device:R", rv, R0805, 335.28, y, {"1": gnet, "2": nn}, rot=90,
              refxy=(0, -2.54, None), valxy=(0, 2.54, None))
        place(led, "Device:LED", col, "LED_THT:LED_D3.0mm", 345.44, y + 3.81, {"2": nn, "1": "GND"}, rot=90,
              spec=spec, refxy=(2.54, -1.27, "right"), valxy=(2.54, 1.27, "right"))
        W(f"{r}.2", (jx, y), (jx, P(f"J5.{jpin}")[1]), f"J5.{jpin}")
        PWR("GND", f"{led}.1", "D")
        W(f"U6.{upin}", (gx, P(f"U6.{upin}")[1]), (gx, y), f"{r}.1")
    if lbl:
        LBL(lbl, (gx, 116.84), "U")
LBL("LED_CTRL", (326.39, 73.66), "L")

# ════════════════════════════════════════════════════════════
#  D  power supply
# ════════════════════════════════════════════════════════════
TXT("D  Power: 13.8 V -> 12 V (LDO) / 8 V / 5 V", 20.32, 190.5, 2.0)
place("J3", "Connector:Screw_Terminal_01x02", "13.8V IN",
      "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
      25.4, 203.2, {"1": "VIN_RAW", "2": "GND"}, mirror="y", refxy=(-2.54, -5.08, None), valxy=(-2.54, 7.62, None))
place("F1", "Device:Polyfuse", "1.5A", "Fuse:Fuse_1812_4532Metric", 48.26, 203.2, {"1": "VIN_RAW", "2": "VIN_F"},
      rot=90, spec="PTC 1.5 A hold, 24 V, 1812 (Littelfuse 1812L150/24)")
place("D3", "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", 63.5, 203.2, {"2": "VIN_F", "1": "VIN"}, rot=180,
      spec="reverse polarity protection", refxy=(0, -6.35, None), valxy=(0, -3.81, None))
place("D4", "Device:D_Zener", "SMBJ16A", "Diode_SMD:D_SMB", 73.66, 207.01, {"1": "VIN", "2": "GND"}, rot=270,
      spec="TVS", refxy=(-2.54, -1.27, "right"), valxy=(-2.54, 1.27, "right"))
place("C40", "Device:C_Polarized", "220u", CP8, 81.28, 207.01, {"1": "VIN", "2": "GND"}, spec="25V")
place("C41", "Device:C", "100n", C0805, 91.44, 207.01, {"1": "VIN", "2": "GND"})
place("U1", "Regulator_Linear:LM7805_TO220", "LM2940CT-12", "Package_TO_SOT_THT:TO-220-3_Vertical", 121.92, 203.2,
      {"1": "VIN", "2": "GND", "3": "+12V"}, spec="LDO: 12 V from 13.3 V (an LM7812 drops out); heatsink",
      refxy=(0, -7.62, None), valxy=(0, -5.08, None))
place("C43", "Device:C_Polarized", "47u", CP63, 134.62, 207.01, {"1": "+12V", "2": "GND"}, spec="25V; LM2940 needs >= 22 uF")
place("C44", "Device:C", "100n", C0805, 144.78, 207.01, {"1": "+12V", "2": "GND"})
place("U2", "Regulator_Linear:LM7805_TO220", "LM7808", "Package_TO_SOT_THT:TO-220-3_Vertical", 121.92, 228.6,
      {"1": "VIN", "2": "GND", "3": "+8V"}, spec="heatsink", refxy=(0, -7.62, None), valxy=(0, -5.08, None))
place("C45", "Device:C", "330n", C0805, 107.95, 232.41, {"1": "VIN", "2": "GND"})
place("C46", "Device:C_Polarized", "10u", CP63, 134.62, 232.41, {"1": "+8V", "2": "GND"}, spec="25V")
place("C47", "Device:C", "100n", C0805, 144.78, 232.41, {"1": "+8V", "2": "GND"})
place("U3", "Regulator_Switching:TSR_1-2450", "TSR 1-2450", "Converter_DCDC:Converter_DCDC_TRACO_TSR-1_THT",
      124.46, 254.0, {"1": "VIN", "2": "GND", "3": "+5V"},
      spec="Traco 1 A switcher, LM7805 pin compatible (then add heatsink)", refxy=(0, -10.16, None), valxy=(0, -7.62, None))
place("C48", "Device:C_Polarized", "10u", CP63, 107.95, 255.27, {"1": "VIN", "2": "GND"}, spec="25V")
place("C49", "Device:C_Polarized", "22u", CP63, 139.7, 255.27, {"1": "+5V", "2": "GND"}, spec="16V")
place("C50", "Device:C", "100n", C0805, 149.86, 255.27, {"1": "+5V", "2": "GND"})

W("J3.1", "F1.1"); LBL("VIN_RAW", (31.75, 203.2))
W("J3.2", (33.02, 205.74)); PWR("GND", (33.02, 205.74), "D")
W("F1.2", "D3.2"); LBL("VIN_F", (53.34, 203.2))
W("D3.1", "U1.1"); LBL("VIN", (104.14, 203.2))
FLAG((77.47, 203.2))
for r_ in ("D4", "C40", "C41", "U1", "C43", "C44", "C45", "C46", "C47", "C48", "C49", "C50"):
    PWR("GND", r_ + ".2", "D")
PWR("GND", "U2.2", "D"); PWR("GND", "U3.2", "D")
W("U1.3", (154.94, 203.2)); PWR("+12V", (154.94, 203.2), "U")
W((101.6, 203.2), (101.6, 251.46), "U3.1"); W((101.6, 228.6), "U2.1")
W("U2.3", (154.94, 228.6)); PWR("+8V", (154.94, 228.6), "U")
W("U3.3", (154.94, 251.46)); PWR("+5V", (154.94, 251.46), "U")
# GND power flag
W((45.72, 223.52), (45.72, 226.06)); FLAG((45.72, 223.52)); PWR("GND", (45.72, 226.06), "D")
for i in range(4):
    place(f"H{i+1}", "Mechanical:MountingHole_Pad", "M3", "MountingHole:MountingHole_3.2mm_M3_Pad_Via",
          170.18 + 12.7 * i, 236.22, {"1": "GND"}, spec="bond to enclosure")
    PWR("GND", f"H{i+1}.1", "D")

TXT("BoltATAS - design notes", 162.56, 165.1, 1.7)
TXT("Tandem match (Sontheimer): T1 = current transformer, 30T from GND to FWD_PORT; T2 = voltage transformer,\n"
    "30T from RF_LINE to GND, its 1T (coax centre) between FWD_PORT and REF_PORT. Both coax braids grounded at ONE end.\n"
    "FWD and REF swapped when testing? Swap the two 30T leads of T1.\n"
    "Coupling 20log(30) = 29.5 dB + 13 dB pi-pad = 42.5 dB: 120 W -> +8.3 dBm at the AD8307 (linear to +16 dBm),\n"
    "200 W -> 2.36 V at the ADC (ESP32 linear to 2.45 V). Pad = 50 ohm port load: 78.7 || (105 + 31.6||1.1k) = 49.8 ohm.\n"
    "DC is injected AFTER the DC block C1..C3: it must never reach T2 (its 30T winding is a DC short) or the radio.\n"
    "Motor: K1 NC feeds K2 COM, so 12 V and 8 V can never meet; K1 wins. Idle: motor line to 0 V via R41.\n"
    "AD8307: OUT unloaded (25 mV/dB, 12.5k internal), ENB tied to VPS, INM AC-coupled, 1 uF on OFS for 160 m.\n"
    "L1: 20 turns 0.8 mm CuL on FT114-43 (about 240 uH); measure |Z| >= 1.5 kohm over 1.8-30 MHz with a VNA.\n"
    "Relays: pin numbers per the KiCad SRD footprint (1 COM, 3 NO, 4 NC); check COM-NC continuity before soldering.\n"
    "WT32-ETH01: IO0 is the 50 MHz Ethernet clock input, keep R50 right at the socket. Front panel: see block F.\n"
    "Tune only with <= 25 W carrier (firmware refuses above). Heatsinks on U1 and U2 (motor current).\n"
    "Front panel (F): buttons 10k pull-up + 100n = 1 ms debounce, 1k protects the GPIO. IO2/IO12 are strap pins:\n"
    "the LED to GND keeps them low at boot. IO5/IO15 are strap pins too: a pull-up is their default level.\n"
    "J5 = front panel option: buttons in parallel; fit the LEDs on the board OR on the panel (series R stays on the board).",
    162.56, 170.18, 1.27)


# ════════════════════════════════════════════════════════════
#  connectivity clean-up and output
# ════════════════════════════════════════════════════════════
def pin_points():
    pts = []
    for ref, p in PARTS.items():
        for num, lst in p["L"]["pins"].items():
            for px, py, _, _ in lst:
                dx, dy = xf(px, py, p["rot"], p["mirror"])
                pts.append((q(p["x"] + dx), q(p["y"] + dy)))
    pts += [(x, y) for _, x, y, _, _ in POWERS]
    pts += FLAGS
    return pts


def on_seg(p, s):
    x, y = p
    x1, y1, x2, y2 = s
    if x1 == x2 == x and min(y1, y2) < y < max(y1, y2):
        return True
    if y1 == y2 == y and min(x1, x2) < x < max(x1, x2):
        return True
    return False


def normalize():
    """split wires where something connects mid-segment, return junction points"""
    pins = pin_points()
    while True:
        ends = [(s[0], s[1]) for s in WIRES] + [(s[2], s[3]) for s in WIRES]
        cands = set(ends) | set(pins) | {(x, y) for _, x, y, _ in LABELS}
        done = True
        for i, s in enumerate(WIRES):
            for p in cands:
                if on_seg(p, s):
                    x1, y1, x2, y2 = s
                    WIRES[i] = (x1, y1, p[0], p[1])
                    WIRES.append((p[0], p[1], x2, y2))
                    done = False
                    break
            if not done:
                break
        if done:
            break
    deg = {}
    for x1, y1, x2, y2 in WIRES:
        for p in ((x1, y1), (x2, y2)):
            deg[p] = deg.get(p, 0) + 1
    for p in pins:
        if p in deg:
            deg[p] += 1
    return sorted(p for p, d in deg.items() if d >= 3)


def refpos_default(p):
    pins = [xf(px, py, p["rot"], p["mirror"]) for lst in p["L"]["pins"].values() for px, py, _, _ in lst]
    name = p["lib"].split(":")[1]
    if len(pins) == 2 and all(abs(x) < 0.01 for x, _ in pins):
        return (2.54, -1.27, "left"), (2.54, 1.27, "left")
    if len(pins) == 2 and all(abs(y) < 0.01 for _, y in pins):
        d = 3.81 if name in ("D", "LED", "D_Zener", "D_Schottky", "SW_Push") else 2.54
        return (0, -d, None), (0, d, None)
    return (3.81, -1.27, "left"), (3.81, 1.27, "left")


FONT = "(font (size 1.27 1.27))"


def emit_symbol(out, ref, lib_id, value, fp, x, y, rot, mirror, fields, refxy, valxy, hide_ref=False,
                hide_val=False, pins=()):
    fa = 90 if rot in (90, 270) else 0
    (rx, ry, rj), (vx, vy, vj) = refxy, valxy
    mir = f" (mirror {mirror})" if mirror else ""
    s = (f'  (symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} {rot}){mir} (unit 1)\n'
         f'    (in_bom yes) (on_board yes) (dnp no)\n'
         f'    (uuid {uid("sym-" + ref) if not ref.startswith("#") else uid()})\n')
    props = [("Reference", ref, x + rx, y + ry, rj, hide_ref), ("Value", value, x + vx, y + vy, vj, hide_val),
             ("Footprint", fp, x, y, None, True), ("Datasheet", "~", x, y, None, True)]
    props += [(k, v, x, y, None, True) for k, v in fields.items()]
    for k, v, px, py, j, h in props:
        just = f" (justify {j})" if j else ""
        hide = " hide" if h else ""
        v = v.replace('"', "'")
        s += f'    (property "{k}" "{v}" (at {px:.2f} {py:.2f} {fa})\n      (effects {FONT}{just}{hide}))\n'
    for num in pins:
        s += f'    (pin "{num}" (uuid {uid()}))\n'
    s += f'    (instances (project "{PROJECT}" (path "/{ROOT}" (reference "{ref}") (unit 1))))\n  )\n'
    out.append(s)


def build():
    junctions = normalize()
    libs = {}
    out = []
    for ref, p in PARTS.items():
        libs[p["lib"]] = p["L"]
        dr, dv = refpos_default(p)
        fields = {"Spec": p["spec"]} if p["spec"] else {}
        emit_symbol(out, ref, p["lib"], p["value"], p["fp"], p["x"], p["y"], p["rot"], p["mirror"], fields,
                    p["refxy"] or dr, p["valxy"] or dv, pins=sorted(p["L"]["pins"], key=lambda n: (len(n), n)))
    n = 0
    for net, x, y, d, show in POWERS:
        n += 1
        lib_id = "power:" + net
        libs[lib_id] = lib_symbol(lib_id)
        rot = ({"D": 0, "U": 180, "R": 90, "L": 270} if net == "GND" else {"U": 0, "D": 180, "L": 90, "R": 270})[d]
        off = {"D": (0, 3.81), "U": (0, -3.81), "L": (-5.08, 0), "R": (5.08, 0)}[d]
        emit_symbol(out, f"#PWR{n:03d}", lib_id, net, "", x, y, rot, None, {}, (0, 0, None), (off[0], off[1], None),
                    hide_ref=True, hide_val=not show, pins=["1"])
    libs["power:PWR_FLAG"] = lib_symbol("power:PWR_FLAG")
    for x, y in FLAGS:
        n += 1
        emit_symbol(out, f"#FLG{n:03d}", "power:PWR_FLAG", "PWR_FLAG", "", x, y, 0, None, {}, (0, 0, None),
                    (0, -5.08, None), hide_ref=True, pins=["1"])
    for x1, y1, x2, y2 in WIRES:
        out.append(f'  (wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))\n'
                   f'    (stroke (width 0) (type default)) (uuid {uid()}))\n')
    for x, y in junctions:
        out.append(f'  (junction (at {x:.2f} {y:.2f}) (diameter 0) (color 0 0 0 0) (uuid {uid()}))\n')
    for name, x, y, d in LABELS:
        ang = {"L": 180, "R": 0, "U": 90, "D": 270}[d]
        just = "left bottom" if d in "RU" else "right bottom"
        out.append(f'  (label "{name}" (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced)\n'
                   f'    (effects {FONT} (justify {just})) (uuid {uid()}))\n')
    for x, y in NOCONN:
        out.append(f'  (no_connect (at {x:.2f} {y:.2f}) (uuid {uid()}))\n')
    for s, x, y, size in TEXTS:
        s = s.replace('"', "'").replace("\n", "\\n")
        out.append(f'  (text "{s}" (at {x:.2f} {y:.2f} 0)\n'
                   f'    (effects (font (size {size} {size})) (justify left top)) (uuid {uid()}))\n')
    head = ['(kicad_sch (version 20230121) (generator eeschema)\n\n',
            f'  (uuid {ROOT})\n\n  (paper "A3")\n\n',
            '  (title_block\n    (title "BoltATAS - ATAS-100 controller")\n    (date "2026-11-25")\n'
            '    (rev "1.3")\n    (company "PE5JW")\n'
            '    (comment 1 "120 W HF 1.8-30 MHz, tandem match + 2x AD8307, WT32-ETH01")\n'
            '    (comment 2 "v1.3: front panel (SWR LEDs, UP/DOWN/TUNE); v1.2: one connected drawing")\n'
            '  )\n\n  (lib_symbols\n']
    for lib_id, lib in libs.items():
        head.append("    " + lib["block"].replace("\n", "\n    ") + "\n")
    head.append('  )\n\n')
    tail = ['\n  (sheet_instances\n    (path "/" (page "1"))\n  )\n)\n']
    with open(os.path.join(KDIR, PROJECT + ".kicad_sch"), "w") as f:
        f.write("".join(head + out + tail))
    print(f"schematic: {len(PARTS)} parts, {len(WIRES)} wire segments, {len(junctions)} junctions, "
          f"{len(LABELS)} net names, {len(POWERS)} power symbols")


FLAG_NETS = ["GND", "VIN", "VDET_F", "VDET_R"]

if __name__ == "__main__":
    build()
