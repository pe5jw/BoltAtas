#!/usr/bin/env python3
"""Generate BoltATAS.kicad_sch (KiCad 7 format).

Every pin gets a short wire stub ending in a net label (or a power
symbol / no-connect flag), so connectivity is explicit and checked by
KiCad's ERC. The part list below is the single source of truth for the
netlist; the PCB is built from the netlist KiCad exports from this file.
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


def uid(seed=None):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed)) if seed else str(uuid.uuid4())


# ── s-expression block extraction ───────────────────────────
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
    if ext:   # flatten derived symbol onto its parent
        parent = lib_symbol(lib + ":" + ext.group(1))
        pblk = parent["block"]
        pblk = pblk.replace('(symbol "%s:%s"' % (lib, ext.group(1)), '(symbol "%s"' % lib_id, 1)
        pblk = pblk.replace('(symbol "%s_' % ext.group(1), '(symbol "%s_' % name)
        for prop in re.finditer(r'\(property "([^"]+)" "([^"]*)"', blk):
            pblk = re.sub(r'\(property "%s" "[^"]*"' % re.escape(prop.group(1)),
                          '(property "%s" "%s"' % (prop.group(1), prop.group(2).replace("\\", "\\\\")), pblk, count=1)
        blk = pblk
    else:
        blk = blk.replace('(symbol "%s"' % name, '(symbol "%s"' % lib_id, 1)
    pins = {}
    for pm in re.finditer(r'\(pin (\w+) \w+ \(at ([-\d.]+) ([-\d.]+) (\d+)\)', blk):
        pb = block_at(blk, pm.start())
        num = re.search(r'\(number "([^"]+)"', pb).group(1)
        pins.setdefault(num, []).append((float(pm.group(2)), float(pm.group(3)), int(pm.group(4)), pm.group(1)))
    return {"block": blk, "pins": pins}


# ── part list ───────────────────────────────────────────────
# (ref, lib_id, value, footprint, x, y, {pin: net}, extra_fields)
R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
CP63 = "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm"
CP8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"

PARTS = []


def P(ref, lib, val, fp, x, y, pins, **f):  # f: extra (hidden) fields, e.g. Spec
    PARTS.append((ref, lib, val, fp, x, y, pins, f))


# Block A — RF path, tandem match, DC block, bias tee
P("J1", "Connector:Conn_Coaxial", "RF IN", "BoltATAS:Coax_Pigtail", 25.4, 45.72, {"1": "RF_TX", "2": "GND"},
  Spec="pigtail RG-58/RG-400 to panel SO-239, from FT-897D")
P("T1", "BoltATAS:Tandem_Xfmr", "FT114-43 1T:30T", "BoltATAS:Toroid_FT114_Slot_Coax", 60.96, 45.72,
  {"1": "RF_TX", "2": "RF_LINE", "3": "GND", "4": "GND", "5": "FWD_PORT"},
  Spec="current transformer: 30T 0.4 mm CuL; 1T = 60 mm RG-58/RG-400, braid to SH at end A only")
P("T2", "BoltATAS:Tandem_Xfmr", "FT114-43 30T:1T", "BoltATAS:Toroid_FT114_Slot_Coax", 60.96, 81.28,
  {"1": "REF_PORT", "2": "FWD_PORT", "3": "GND", "4": "RF_LINE", "5": "GND"},
  Spec="voltage transformer: 30T PTFE/double-enamel wire (full line voltage); 1T = coax centre, braid to SH at end A only")
for i, ref in enumerate(["C1", "C2", "C3"]):
    P(ref, "Device:C", "100n", C1206, 96.52 + 10.16 * i, 45.72, {"1": "RF_LINE", "2": "RF_ANT"},
      Spec="X7R 100V 1206; DC block, 3 in parallel = 0.3 uF")
P("J2", "Connector:Conn_Coaxial", "ANT", "BoltATAS:Coax_Pigtail", 149.86, 45.72, {"1": "RF_ANT", "2": "GND"},
  Spec="pigtail RG-58/RG-400 to panel SO-239, to ATAS-100")
P("L1", "Device:L", "240u", "BoltATAS:Toroid_FT114_Flat_Choke", 124.46, 66.04, {"1": "RF_ANT", "2": "COAX_DC"},
  Spec="RF choke: 20T 0.8 mm CuL on FT114-43, single layer; |Z| >= 1.5k 1.8-30 MHz")
P("C4", "Device:C", "1n", C0805, 132.08, 101.6, {"1": "COAX_DC", "2": "GND"}, Spec="C0G 100V")
P("C5", "Device:C", "100n", C0805, 142.24, 101.6, {"1": "COAX_DC", "2": "GND"}, Spec="X7R 50V")
P("D5", "Device:D_Zener", "SMBJ15A", "Diode_SMD:D_SMB", 154.94, 101.6, {"1": "COAX_DC", "2": "GND"},
  Spec="TVS on motor line")

# Block B — FWD / REF detectors
def detector(tag, y, n0, uref):
    port, det, inp, inm, ofs, out, adc, vd = (f"{tag}_PORT", f"{tag}_DET", f"{tag}_INP", f"{tag}_INM",
                                              f"{tag}_OFS", f"{tag}_OUT", f"{tag}_ADC", f"VDET_{tag[0]}")
    P(f"R{n0}", "Device:R", "78.7", "Resistor_SMD:R_2010_5025Metric", 25.4, y, {"1": port, "2": "GND"},
      Spec="1% 0.75W 2010; 13 dB pi-pad input shunt")
    P(f"R{n0+1}", "Device:R", "105", R1206, 35.56, y, {"1": port, "2": det}, Spec="1% 1206; pad series")
    P(f"R{n0+2}", "Device:R", "31.6", R0805, 45.72, y, {"1": det, "2": "GND"},
      Spec="1%; pad output shunt + 50 ohm termination (78.7 || 52.3)")
    P(f"C{n0}", "Device:C", "100n", C0805, 55.88, y, {"1": det, "2": inp})
    P(f"C{n0+1}", "Device:C", "100n", C0805, 66.04, y, {"1": inm, "2": "GND"})
    P(f"C{n0+2}", "Device:C", "1u", C0805, 76.2, y, {"1": ofs, "2": "GND"},
      Spec="X7R; offset loop corner below 1.8 MHz (700 kHz without)")
    P(uref, "BoltATAS:AD8307", "AD8307ARZ", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 106.68, y,
      {"8": inp, "1": inm, "3": ofs, "5": "NC", "4": out, "7": vd, "6": vd, "2": "GND"})
    P(f"R{n0+3}", "Device:R", "10", R0805, 127.0, y - 5.08, {"1": "+5V", "2": vd})
    P(f"C{n0+3}", "Device:C", "100n", C0805, 134.62, y - 5.08, {"1": vd, "2": "GND"})
    P(f"C{n0+4}", "Device:C", "100n", C0805, 144.78, y + 2.54, {"1": out, "2": "GND"},
      Spec="with internal 12.5k: 1.25 ms filter")
    P(f"R{n0+4}", "Device:R", "1k", R0805, 154.94, y + 2.54, {"1": out, "2": adc}, Spec="ADC pin protection")


detector("FWD", 129.54, 10, "U4")
detector("REF", 165.1, 20, "U5")

# Block C — motor switching, interlock, current sense
SRD = "Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C"
P("D1", "Device:D", "1N4148W", "Diode_SMD:D_SOD-123", 180.34, 40.64, {"1": "+5V", "2": "K1_DRV"})
P("K1", "Relay:SANYOU_SRD_Form_C", "SRD-05VDC-SL-C", SRD, 205.74, 48.26,
  {"1": "MOT_FEED", "3": "+12V", "4": "K_CHAIN", "2": "K1_DRV", "5": "+5V"}, Spec="K1: +12 V = whip longer (DOWN)")
P("R46", "Device:R", "1k", R0805, 175.26, 60.96, {"1": "+5V", "2": "LED2_A"})
P("LED2", "Device:LED", "red", "LED_THT:LED_D3.0mm", 185.42, 68.58, {"2": "LED2_A", "1": "K1_DRV"}, Spec="DOWN / 12 V")
P("Q1", "Transistor_BJT:BC547", "BC547", "Package_TO_SOT_THT:TO-92_Inline_Wide", 233.68, 63.5,
  {"1": "K1_DRV", "2": "Q1_B", "3": "GND"})
P("R42", "Device:R", "1k", R0805, 246.38, 63.5, {"1": "K1_CTRL", "2": "Q1_B"})
P("R43", "Device:R", "10k", R0805, 256.54, 63.5, {"1": "Q1_B", "2": "GND"}, Spec="relay off during reset")
P("D2", "Device:D", "1N4148W", "Diode_SMD:D_SOD-123", 180.34, 86.36, {"1": "+5V", "2": "K2_DRV"})
P("K2", "Relay:SANYOU_SRD_Form_C", "SRD-05VDC-SL-C", SRD, 205.74, 93.98,
  {"1": "K_CHAIN", "3": "+8V", "4": "MOT_IDLE", "2": "K2_DRV", "5": "+5V"}, Spec="K2: +8 V = whip shorter (UP)")
P("R47", "Device:R", "1k", R0805, 175.26, 106.68, {"1": "+5V", "2": "LED3_A"})
P("LED3", "Device:LED", "yellow", "LED_THT:LED_D3.0mm", 185.42, 114.3, {"2": "LED3_A", "1": "K2_DRV"}, Spec="UP / 8 V")
P("Q2", "Transistor_BJT:BC547", "BC547", "Package_TO_SOT_THT:TO-92_Inline_Wide", 233.68, 109.22,
  {"1": "K2_DRV", "2": "Q2_B", "3": "GND"})
P("R44", "Device:R", "1k", R0805, 246.38, 109.22, {"1": "K2_CTRL", "2": "Q2_B"})
P("R45", "Device:R", "10k", R0805, 256.54, 109.22, {"1": "Q2_B", "2": "GND"}, Spec="relay off during reset")
P("R41", "Device:R", "1k", R0805, 218.44, 119.38, {"1": "MOT_IDLE", "2": "GND"}, Spec="idle: motor line to 0 V")
P("R40", "Device:R", "0.1", "Resistor_SMD:R_2512_6332Metric", 271.78, 45.72, {"1": "MOT_FEED", "2": "COAX_DC"},
  Spec="1% 1W 2512; motor current shunt")
P("C25", "Device:C", "100n", C0805, 284.48, 27.94, {"1": "+5V", "2": "GND"})
P("U7", "Amplifier_Current:INA180A1", "INA180A1", "Package_TO_SOT_SMD:SOT-23-5", 297.18, 48.26,
  {"3": "MOT_FEED", "4": "COAX_DC", "5": "+5V", "2": "GND", "1": "IMOT_OUT"}, Spec="20 V/V: 2 mV per mA")
P("R25", "Device:R", "1k", R0805, 314.96, 50.8, {"1": "IMOT_OUT", "2": "IMOT_ADC"})
P("C26", "Device:C", "100n", C0805, 325.12, 50.8, {"1": "IMOT_ADC", "2": "GND"})

# Block D — power
P("J3", "Connector:Screw_Terminal_01x02", "13.8V IN",
  "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
  182.88, 147.32, {"1": "VIN_RAW", "2": "GND"})
P("F1", "Device:Polyfuse", "1.5A", "Fuse:Fuse_1812_4532Metric", 195.58, 147.32, {"1": "VIN_RAW", "2": "VIN_F"},
  Spec="PTC 1.5 A hold, 24 V, 1812 (Littelfuse 1812L150/24)")
P("D3", "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", 208.28, 139.7, {"2": "VIN_F", "1": "VIN"},
  Spec="reverse polarity protection")
P("D4", "Device:D_Zener", "SMBJ16A", "Diode_SMD:D_SMB", 218.44, 154.94, {"1": "VIN", "2": "GND"}, Spec="TVS")
P("C40", "Device:C_Polarized", "220u", CP8, 228.6, 147.32, {"1": "VIN", "2": "GND"}, Spec="25V")
P("C41", "Device:C", "100n", C0805, 238.76, 147.32, {"1": "VIN", "2": "GND"})
P("U1", "Regulator_Linear:LM7805_TO220", "LM2940CT-12", "Package_TO_SOT_THT:TO-220-3_Vertical", 264.16, 139.7,
  {"1": "VIN", "2": "GND", "3": "+12V"}, Spec="LDO: 12 V from 13.3 V (an LM7812 drops out); heatsink")
P("C43", "Device:C_Polarized", "47u", CP63, 279.4, 147.32, {"1": "+12V", "2": "GND"}, Spec="25V; LM2940 needs >= 22 uF")
P("C44", "Device:C", "100n", C0805, 289.56, 147.32, {"1": "+12V", "2": "GND"})
P("U2", "Regulator_Linear:LM7805_TO220", "LM7808", "Package_TO_SOT_THT:TO-220-3_Vertical", 264.16, 167.64,
  {"1": "VIN", "2": "GND", "3": "+8V"}, Spec="heatsink")
P("C45", "Device:C", "330n", C0805, 251.46, 175.26, {"1": "VIN", "2": "GND"})
P("C46", "Device:C_Polarized", "10u", CP63, 279.4, 175.26, {"1": "+8V", "2": "GND"}, Spec="25V")
P("C47", "Device:C", "100n", C0805, 289.56, 175.26, {"1": "+8V", "2": "GND"})
P("U3", "Regulator_Switching:TSR_1-2450", "TSR 1-2450", "Converter_DCDC:Converter_DCDC_TRACO_TSR-1_THT", 264.16, 195.58,
  {"1": "VIN", "2": "GND", "3": "+5V"}, Spec="Traco 1 A switcher, LM7805 pin compatible (then add heatsink)")
P("C48", "Device:C_Polarized", "10u", CP63, 251.46, 203.2, {"1": "VIN", "2": "GND"}, Spec="25V")
P("C49", "Device:C_Polarized", "22u", CP63, 279.4, 203.2, {"1": "+5V", "2": "GND"}, Spec="16V")
P("C50", "Device:C", "100n", C0805, 289.56, 203.2, {"1": "+5V", "2": "GND"})
for i in range(4):
    P(f"H{i+1}", "Mechanical:MountingHole_Pad", "M3", "MountingHole:MountingHole_3.2mm_M3_Pad_Via",
      190.5 + 12.7 * i, 190.5, {"1": "GND"}, Spec="bond to enclosure")

# Block E — controller
P("U6", "BoltATAS:WT32-ETH01", "WT32-ETH01", "BoltATAS:WT32-ETH01_Socket", 373.38, 76.2, {
    "1": "NC", "2": "GND", "3": "+3V3", "4": "ESP_EN", "5": "K2_CTRL", "6": "LED_CTRL", "7": "NC", "8": "NC",
    "9": "GND", "10": "NC", "11": "GND", "12": "+5V", "13": "NC",
    "26": "ESP_TX", "25": "ESP_RX", "24": "ESP_IO0", "23": "GND", "22": "REF_ADC", "21": "FWD_ADC",
    "20": "NC", "19": "NC", "18": "NC", "17": "IMOT_ADC", "16": "K1_CTRL", "15": "NC", "14": "GND"},
  Spec="plugs into 2x PinSocket 1x13 2.54 mm")
P("C51", "Device:C", "100n", C0805, 340.36, 111.76, {"1": "+5V", "2": "GND"})
P("C52", "Device:C_Polarized", "22u", CP63, 350.52, 111.76, {"1": "+5V", "2": "GND"}, Spec="16V")
P("R50", "Device:R", "1k", R0805, 342.9, 137.16, {"1": "ESP_IO0", "2": "IO0_EXT"},
  Spec="isolates the 50 MHz Ethernet clock on IO0 from header and button")
P("J4", "Connector_Generic:Conn_01x06", "PROG", "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
  398.78, 137.16, {"1": "GND", "2": "ESP_TX", "3": "ESP_RX", "4": "+3V3", "5": "IO0_EXT", "6": "ESP_EN"},
  Spec="USB-serial 3.3 V: GND TX RX 3V3(ref only) IO0 EN")
P("SW1", "Switch:SW_Push", "BOOT", "Button_Switch_THT:SW_PUSH_6mm", 363.22, 152.4, {"1": "IO0_EXT", "2": "GND"})
P("SW2", "Switch:SW_Push", "RESET", "Button_Switch_THT:SW_PUSH_6mm", 363.22, 167.64, {"1": "ESP_EN", "2": "GND"})
P("R51", "Device:R", "470", R0805, 342.9, 177.8, {"1": "LED_CTRL", "2": "LED1_A"})
P("LED1", "Device:LED", "green", "LED_THT:LED_D3.0mm", 383.54, 182.88, {"2": "LED1_A", "1": "GND"}, Spec="STATUS")

FLAGS = ["GND", "VIN", "VDET_F", "VDET_R"]

NOTES = [
    (20.32, 200.66, 1.7, "BoltATAS v1.1 - review fixes and design notes"),
    (20.32, 207.01, 1.27,
     "RF path: radio -> J1 -> T1 1T (RF_TX->RF_LINE) -> C1..C3 DC block -> RF_ANT -> J2 -> ATAS-100.\n"
     "Tandem match (Sontheimer): T1 = current transformer, 30T from GND to FWD_PORT. T2 = voltage transformer,\n"
     "30T from RF_LINE to GND, its 1T (coax centre) between FWD_PORT and REF_PORT. Both coax braids grounded at ONE end.\n"
     "FWD and REF swapped when testing? Swap the two 30T leads of T1.\n"
     "Coupling 20log(30) = 29.5 dB + 13 dB pi-pad = 42.5 dB. 120 W -> +8.3 dBm at the AD8307 (linear to +16 dBm),\n"
     "200 W -> +10.5 dBm = 2.36 V at the ADC (ESP32 linear to 2.45 V). Pad = the 50 ohm port load: 78.7 || (105 + 31.6||1.1k) = 49.8 ohm.\n"
     "DC is injected AFTER the DC block: it must never reach T2 (its 30T winding is a DC short) or the radio.\n"
     "Motor: K1 NC feeds K2 COM, so 12 V and 8 V can never meet; K1 wins. Idle: motor line to 0 V via R41.\n"
     "AD8307: OUT unloaded (25 mV/dB, 12.5k internal), ENB tied to VPS, INM AC-coupled, 1 uF on OFS for 160 m.\n"
     "L1: 20 turns 0.8 mm CuL on FT114-43 (about 240 uH). Measure |Z| >= 1.5 kohm over 1.8-30 MHz with a VNA.\n"
     "Relays: pin numbers per the KiCad SRD footprint (1 COM, 3 NO, 4 NC) - check COM-NC continuity before soldering.\n"
     "WT32-ETH01: IO0 is the 50 MHz Ethernet clock input, keep R50 right at the socket. IO5 not used (strapping pin).\n"
     "Tune only with <= 25 W carrier (firmware refuses above). Heatsinks on U1 and U2 (motor current)."),
    (20.32, 22.86, 2.0, "A  RF path: tandem match, DC block, bias tee"),
    (20.32, 111.76, 2.0, "B  FWD / REF detectors (13 dB pad + AD8307)"),
    (167.64, 22.86, 2.0, "C  Motor switching, interlock, current sense"),
    (167.64, 124.46, 2.0, "D  Power 13.8 V -> 12 / 8 / 5 V"),
    (322.58, 22.86, 2.0, "E  Controller WT32-ETH01"),
]


# ── emit ────────────────────────────────────────────────────
def r(v):
    return round(v / 1.27) * 1.27


REFPOS = {   # lib name -> ((ref dx, dy, justify), (value dx, dy, justify)), screen coords
    "Conn_Coaxial": ((3.81, -1.27, "left"), (3.81, 1.27, "left")),
    "Tandem_Xfmr": ((0, -10.16, None), (0, 10.16, None)),
    "AD8307": ((7.62, 11.43, "left"), (7.62, 13.97, "left")),
    "INA180A1": ((3.81, -5.08, "left"), (3.81, 6.35, "left")),
    "SANYOU_SRD_Form_C": ((11.43, -1.27, "left"), (11.43, 1.27, "left")),
    "BC547": ((5.08, -1.27, "left"), (5.08, 1.27, "left")),
    "LM7805_TO220": ((0, -8.89, None), (0, -6.35, None)),
    "TSR_1-2450": ((0, -8.89, None), (0, -6.35, None)),
    "WT32-ETH01": ((13.97, 22.86, "left"), (13.97, 25.4, "left")),
    "Screw_Terminal_01x02": ((3.81, -3.81, "left"), (3.81, 3.81, "left")),
    "Conn_01x06": ((0, -8.89, None), (0, 12.7, None)),
    "SW_Push": ((0, 2.54, None), (0, 5.08, None)),
    "MountingHole_Pad": ((3.81, -1.27, "left"), (3.81, 1.27, "left")),
}


def refpos(lib_id, lib):
    name = lib_id.split(":")[1]
    if name in REFPOS:
        return REFPOS[name]
    pins = [p for v in lib["pins"].values() for p in v]
    if len(pins) == 2 and all(abs(p[0]) < 0.01 for p in pins):      # vertical 2-pin
        return (2.54, -1.27, "left"), (2.54, 1.27, "left")
    if len(pins) == 2 and all(abs(p[1]) < 0.01 for p in pins):      # horizontal 2-pin
        return (0, -3.81, None), (0, 3.81, None)
    return (3.81, -1.27, "left"), (3.81, 1.27, "left")


class Sch:
    def __init__(self):
        self.items = []
        self.libs = {}
        self.pwr_n = 0

    def add_lib(self, lib_id):
        if lib_id not in self.libs:
            self.libs[lib_id] = lib_symbol(lib_id)
        return self.libs[lib_id]

    def wire(self, x1, y1, x2, y2):
        self.items.append(f'  (wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))\n'
                          f'    (stroke (width 0) (type default)) (uuid {uid()}))\n')

    def label(self, name, x, y, d):
        ang = {"L": 180, "R": 0, "U": 90, "D": 270}[d]
        just = "left bottom" if d in "RU" else "right bottom"
        self.items.append(f'  (label "{name}" (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced)\n'
                          f'    (effects (font (size 1.27 1.27)) (justify {just})) (uuid {uid()}))\n')

    def noconnect(self, x, y):
        self.items.append(f'  (no_connect (at {x:.2f} {y:.2f}) (uuid {uid()}))\n')

    def text(self, s, x, y, size):
        s = s.replace('"', "'").replace("\n", "\\n")
        self.items.append(f'  (text "{s}" (at {x:.2f} {y:.2f} 0)\n'
                          f'    (effects (font (size {size} {size})) (justify left top)) (uuid {uid()}))\n')

    def symbol(self, ref, lib_id, value, fp, x, y, rot=0, fields=None, hide_ref=False, in_bom=True,
               refxy=None, valxy=None, hide_val=False, field_ang=0):
        lib = self.add_lib(lib_id)
        fields = fields or {}
        rid = uid("sym-" + ref) if not ref.startswith("#") else uid()
        hide = " hide" if hide_ref else ""
        if refxy is None:
            refxy, valxy = refpos(lib_id, lib)
        (rx, ry, rj), (vx, vy, vj) = refxy, valxy
        props = [("Reference", ref, x + rx, y + ry, rj, hide),
                 ("Value", value, x + vx, y + vy, vj, " hide" if hide_val else ""),
                 ("Footprint", fp, x, y, None, " hide"), ("Datasheet", "~", x, y, None, " hide")]
        for k, v in fields.items():
            props.append((k, v, x, y, None, " hide"))
        s = (f'  (symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} {rot}) (unit 1)\n'
             f'    (in_bom yes) (on_board yes) (dnp no)\n'
             f'    (uuid {rid})\n')
        for k, v, px, py, j, h in props:
            just = f" (justify {j})" if j else ""
            v = v.replace('"', "'")
            s += (f'    (property "{k}" "{v}" (at {px:.2f} {py:.2f} {field_ang})\n'
                  f'      (effects (font (size 1.27 1.27)){just}{h}))\n')
        for num in sorted(lib["pins"].keys(), key=lambda n: (len(n), n)):
            s += f'    (pin "{num}" (uuid {uid()}))\n'
        s += (f'    (instances (project "{PROJECT}" (path "/{ROOT}" (reference "{ref}") (unit 1))))\n'
              f'  )\n')
        self.items.append(s)
        return lib

    def power(self, net, x, y, d, show=True):
        """power symbol whose pin sits at (x, y); body points in direction d"""
        self.pwr_n += 1
        if net == "GND":
            rot = {"D": 0, "U": 180, "R": 90, "L": 270}[d]
        else:
            rot = {"U": 0, "D": 180, "L": 90, "R": 270}[d]
        off = {"D": ((0, 3.81), None), "U": ((0, -3.81), None),
               "L": ((-5.08, 0), None), "R": ((5.08, 0), None)}[d]
        (vx, vy), vj = off
        self.symbol(f"#PWR{self.pwr_n:03d}", "power:" + net, net, "", x, y, rot, hide_ref=True, in_bom=False,
                    refxy=(0, 0, None), valxy=(vx, vy, vj), hide_val=not show,
                    field_ang=90 if rot in (90, 270) else 0)

    def flag(self, net, x, y):
        self.pwr_n += 1
        self.symbol(f"#FLG{self.pwr_n:03d}", "power:PWR_FLAG", "PWR_FLAG", "", x, y, 0, hide_ref=True, in_bom=False)
        self.wire(x, y, x, y + G)
        if net in POWER_NETS:
            self.power(net, x, y + G, "D")
        else:
            self.label(net, x, y + G, "D")

    def save(self, path):
        out = ['(kicad_sch (version 20230121) (generator eeschema)\n\n',
               f'  (uuid {ROOT})\n\n  (paper "A3")\n\n',
               '  (title_block\n    (title "BoltATAS - ATAS-100 controller")\n    (date "2026-11-24")\n'
               '    (rev "1.1")\n    (company "PE5JW")\n'
               '    (comment 1 "120 W HF 1.8-30 MHz, tandem match + 2x AD8307, WT32-ETH01")\n'
               '    (comment 2 "v1.1: review fixes - coupler topology, DC block, AD8307 pinout, relay interlock")\n'
               '  )\n\n  (lib_symbols\n']
        for lib_id, lib in self.libs.items():
            out.append("    " + lib["block"].replace("\n", "\n    ") + "\n")
        out.append('  )\n\n')
        out += self.items
        out.append('\n  (sheet_instances\n    (path "/" (page "1"))\n  )\n)\n')
        with open(path, "w") as f:
            f.write("".join(out))


OUTWARD = {0: "L", 180: "R", 90: "D", 270: "U"}
STEP = {"L": (-1, 0), "R": (1, 0), "U": (0, -1), "D": (0, 1)}


def build():
    sch = Sch()
    nets = {}
    for ref, lib_id, val, fp, x, y, pins, f in PARTS:
        x, y = r(x), r(y)
        lib = sch.symbol(ref, lib_id, val, fp, x, y, 0, f)
        if set(pins) != set(lib["pins"]):
            raise SystemExit(f"{ref}: pins {sorted(pins)} != symbol pins {sorted(lib['pins'])}")
        for num, net in pins.items():
            for (px, py, ang, _t) in lib["pins"][num]:
                ex, ey = x + px, y - py
                d = OUTWARD[ang]
                if net == "NC":
                    sch.noconnect(ex, ey)
                    continue
                dx, dy = STEP[d]
                sx, sy = ex + dx * G, ey + dy * G
                sch.wire(ex, ey, sx, sy)
                if net in POWER_NETS:
                    sch.power(net, sx, sy, d, show=not (ref == "U6" and net == "GND" and num != "11"))
                else:
                    sch.label(net, sx, sy, d)
                nets.setdefault(net, []).append(f"{ref}.{num}")
    for i, net in enumerate(FLAGS):
        sch.flag(net, r(200.66 + 15.24 * i), r(246.38))
    sch.text("Power flags", r(200.66), r(241.3), 1.27)
    for x, y, size, s in NOTES:
        sch.text(s, x, y, size)
    sch.save(os.path.join(KDIR, PROJECT + ".kicad_sch"))
    single = [n for n, p in nets.items() if len(p) < 2]
    if single:
        raise SystemExit(f"single-pin nets: {single}")
    print(f"schematic: {len(PARTS)} parts, {len(nets)} nets")
    return nets


if __name__ == "__main__":
    build()
