#!/usr/bin/env python3
"""Generate the BoltATAS project symbol library and footprint library.

  kicad/BoltATAS.kicad_sym        AD8307, WT32-ETH01, tandem-match transformer
  kicad/BoltATAS.pretty/*.kicad_mod
      WT32-ETH01_Socket           two 1x13 sockets, 22.86 mm row spacing
      Toroid_FT114_Slot_Coax      coax 1-turn through an FT114 core standing in a slot
      Toroid_FT114_Flat_Choke     FT114 core lying flat, 2 winding pads, M3 hole
      Coax_Pigtail                centre pad + 2 braid pads
"""
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.dirname(HERE)


_N = [0]


def u():                       # deterministic ids: regenerating gives identical files (clean git diffs)
    _N[0] += 1
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"boltatas-lib-{_N[0]}"))


FONT = "(effects (font (size 1.27 1.27)))"
FONT_HIDE = "(effects (font (size 1.27 1.27)) hide)"


def pin(ptype, x, y, ang, name, num, length=2.54):
    return (f'      (pin {ptype} line (at {x} {y} {ang}) (length {length})\n'
            f'        (name "{name}" {FONT})\n'
            f'        (number "{num}" {FONT}))\n')


def symbol(name, ref, value, footprint, datasheet, desc, body, pins, pin_names_offset=1.016):
    s = (f'  (symbol "{name}" (pin_names (offset {pin_names_offset})) (in_bom yes) (on_board yes)\n'
         f'    (property "Reference" "{ref}" (at 0 {body[1] + 2.54} 0) {FONT})\n'
         f'    (property "Value" "{value}" (at 0 {body[3] - 2.54} 0) {FONT})\n'
         f'    (property "Footprint" "{footprint}" (at 0 0 0) {FONT_HIDE})\n'
         f'    (property "Datasheet" "{datasheet}" (at 0 0 0) {FONT_HIDE})\n'
         f'    (property "ki_description" "{desc}" (at 0 0 0) {FONT_HIDE})\n'
         f'    (symbol "{name}_0_1"\n'
         f'      (rectangle (start {body[0]} {body[1]}) (end {body[2]} {body[3]})\n'
         f'        (stroke (width 0.254) (type default)) (fill (type background)))\n')
    return s


def sym_ad8307():
    s = symbol("AD8307", "U", "AD8307", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
               "https://www.analog.com/media/en/technical-documentation/data-sheets/AD8307.pdf",
               "Logarithmic amplifier / RF detector, DC-500 MHz, 92 dB, 25 mV/dB",
               (-7.62, 5.08, 7.62, -5.08), None)
    s += '    )\n    (symbol "AD8307_1_1"\n'
    s += pin("input", -10.16, 2.54, 0, "INP", "8")
    s += pin("input", -10.16, -2.54, 0, "INM", "1")
    s += pin("output", 10.16, 0, 180, "OUT", "4")
    s += pin("power_in", -2.54, 7.62, 270, "VPS", "7")
    s += pin("input", 2.54, 7.62, 270, "ENB", "6")
    s += pin("passive", -5.08, -7.62, 90, "OFS", "3")
    s += pin("power_in", 0, -7.62, 90, "COM", "2")
    s += pin("passive", 5.08, -7.62, 90, "INT", "5")
    s += '    )\n  )\n'
    return s


WT32_LEFT = [  # pin, name, type  (physical order, antenna end first)
    (1, "CLK_EN", "passive"), (2, "GND", "power_in"), (3, "3V3", "power_out"),
    (4, "EN", "input"), (5, "IO32", "bidirectional"), (6, "IO33", "bidirectional"),
    (7, "IO5", "bidirectional"), (8, "IO17", "bidirectional"), (9, "GND", "power_in"),
    (10, "3V3", "power_out"), (11, "GND", "power_in"), (12, "5V", "power_in"),
    (13, "LINK", "output")]
WT32_RIGHT = [
    (26, "IO1/TXD0", "bidirectional"), (25, "IO3/RXD0", "bidirectional"),
    (24, "IO0/ETH_CLK", "bidirectional"), (23, "GND", "power_in"),
    (22, "IO39/VN", "input"), (21, "IO36/VP", "input"), (20, "IO15", "bidirectional"),
    (19, "IO14", "bidirectional"), (18, "IO12", "bidirectional"), (17, "IO35", "input"),
    (16, "IO4", "bidirectional"), (15, "IO2", "bidirectional"), (14, "GND", "power_in")]


WT32_SYM = {  # functional arrangement: pin -> (x, y, angle); symbol is drawn mirrored
    # top: supplies
    12: (-5.08, 20.32, 270), 3: (0, 20.32, 270), 10: (5.08, 20.32, 270),
    # bottom: grounds
    2: (-5.08, -20.32, 90), 9: (-2.54, -20.32, 90), 11: (0, -20.32, 90), 14: (2.54, -20.32, 90),
    23: (5.08, -20.32, 90),
    # left: programming / system (EN, TX, RX, IO0 adjacent, same order as the PROG header)
    4: (-15.24, 15.24, 0), 26: (-15.24, 12.7, 0), 25: (-15.24, 10.16, 0), 24: (-15.24, 7.62, 0),
    1: (-15.24, -5.08, 0), 13: (-15.24, -7.62, 0),
}
# right: GPIO, used ones first in the order the schematic needs them
for i, n in enumerate([16, 5, 17, 22, 21, 6, 15, 18, 19, 20, 7, 8]):   # ..IO33, IO2 IO12 IO14 (LEDs), IO15 IO5 IO17 (buttons)
    WT32_SYM[n] = (15.24, round(15.24 - 2.54 * i, 2), 180)


def sym_wt32():
    s = symbol("WT32-ETH01", "U", "WT32-ETH01", "BoltATAS:WT32-ETH01_Socket",
               "https://github.com/egnor/wt32-eth01",
               "ESP32 module with LAN8720A Ethernet. Ethernet uses IO0 (clock in), IO16, IO18, IO19, IO21-23, IO25-27",
               (-12.7, 17.78, 12.7, -17.78), None)
    s += '    )\n    (symbol "WT32-ETH01_1_1"\n'
    for n, name, t in WT32_LEFT + WT32_RIGHT:
        x, y, a = WT32_SYM[n]
        s += pin(t, x, y, a, name, n)
    s += '    )\n  )\n'
    return s


def sym_tandem():
    name = "Tandem_Xfmr"
    s = (f'  (symbol "{name}" (pin_names (offset 0.254)) (in_bom yes) (on_board yes)\n'
         f'    (property "Reference" "T" (at 0 10.16 0) {FONT})\n'
         f'    (property "Value" "FT114-43 1T:30T" (at 0 -10.16 0) {FONT})\n'
         f'    (property "Footprint" "BoltATAS:Toroid_FT114_Slot_Coax" (at 0 0 0) {FONT_HIDE})\n'
         f'    (property "Datasheet" "~" (at 0 0 0) {FONT_HIDE})\n'
         f'    (property "ki_description" "Toroid transformer: 1 turn = coax centre conductor through the core (A-B), shield grounded at one end (SH); N turns = W1-W2" (at 0 0 0) {FONT_HIDE})\n'
         f'    (symbol "{name}_0_1"\n'
         '      (rectangle (start -5.08 7.62) (end 5.08 -7.62) (stroke (width 0.254) (type default)) (fill (type background)))\n'
         '      (polyline (pts (xy -5.08 5.08) (xy 5.08 5.08)) (stroke (width 0.381) (type default)) (fill (type none)))\n'
         '      (polyline (pts (xy -3.81 0.635) (xy 3.81 0.635)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
         '      (polyline (pts (xy -3.81 -0.635) (xy 3.81 -0.635)) (stroke (width 0.254) (type default)) (fill (type none)))\n')
    for k in range(4):  # winding bumps
        x0 = -3.81 + 1.905 * k
        s += (f'      (arc (start {x0:.3f} -5.08) (mid {x0 + 0.9525:.4f} -4.1275) (end {x0 + 1.905:.3f} -5.08)'
              ' (stroke (width 0.254) (type default)) (fill (type none)))\n')
    s += ('      (polyline (pts (xy -5.08 -5.08) (xy -3.81 -5.08)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
          '      (polyline (pts (xy 3.81 -5.08) (xy 5.08 -5.08)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
          '      (text "1T" (at 0 6.35 0) (effects (font (size 1 1))))\n'
          '      (text "N" (at 0 -2.54 0) (effects (font (size 1 1))))\n'
          '    )\n'
          f'    (symbol "{name}_1_1"\n')
    s += pin("passive", -7.62, 5.08, 0, "A", "1")
    s += pin("passive", 7.62, 5.08, 180, "B", "2")
    s += pin("passive", -7.62, 2.54, 0, "SH", "3")
    s += pin("passive", -7.62, -5.08, 0, "W1", "4")
    s += pin("passive", 7.62, -5.08, 180, "W2", "5")
    s += '    )\n  )\n'
    return s


def write_symbols():
    out = '(kicad_symbol_lib (version 20220914) (generator "boltatas_gen_libs")\n'
    out += sym_ad8307() + sym_wt32() + sym_tandem()
    out += ')\n'
    with open(os.path.join(KDIR, "BoltATAS.kicad_sym"), "w") as f:
        f.write(out)


# ── footprints ──────────────────────────────────────────────
def fp_header(name, descr, tags, attr="through_hole"):
    return (f'(footprint "{name}" (version 20221018) (generator "boltatas_gen_libs") (layer "F.Cu")\n'
            f'  (descr "{descr}")\n  (tags "{tags}")\n  (attr {attr})\n')


def fp_text(kind, text, x, y, layer, size=1.0, hide=False):
    h = " hide" if hide else ""
    return (f'  (fp_text {kind} "{text}" (at {x} {y}) (layer "{layer}"){h}\n'
            f'    (effects (font (size {size} {size}) (thickness {size * 0.15:.2f})))\n'
            f'    (tstamp {u()}))\n')


def fp_line(x1, y1, x2, y2, layer, w=0.12):
    return (f'  (fp_line (start {x1} {y1}) (end {x2} {y2}) (stroke (width {w}) (type solid))'
            f' (layer "{layer}") (tstamp {u()}))\n')


def fp_rect(x1, y1, x2, y2, layer, w=0.12):
    return (f'  (fp_rect (start {x1} {y1}) (end {x2} {y2}) (stroke (width {w}) (type solid))'
            f' (fill none) (layer "{layer}") (tstamp {u()}))\n')


def fp_circle(cx, cy, r, layer, w=0.12):
    return (f'  (fp_circle (center {cx} {cy}) (end {cx + r} {cy}) (stroke (width {w}) (type solid))'
            f' (fill none) (layer "{layer}") (tstamp {u()}))\n')


def pad_th(num, x, y, size, drill, shape="circle"):
    return (f'  (pad "{num}" thru_hole {shape} (at {x} {y}) (size {size} {size}) (drill {drill})'
            f' (layers "*.Cu" "*.Mask") (tstamp {u()}))\n')


def pad_np(x, y, drill):
    return (f'  (pad "" np_thru_hole circle (at {x} {y}) (size {drill} {drill}) (drill {drill})'
            f' (layers "*.Cu" "*.Mask") (tstamp {u()}))\n')


def fp_wt32():
    s = fp_header("WT32-ETH01_Socket",
                  "WT32-ETH01 on two 1x13 female headers, 22.86 mm row spacing. Module outline 26x55 mm, RJ45 overhangs the +Y end by 8 mm, WiFi antenna at the -Y end (keep copper away)",
                  "WT32-ETH01 ESP32 LAN8720")
    s += fp_text("reference", "REF**", 0, -24, "F.SilkS")
    s += fp_text("value", "WT32-ETH01", 0, 0, "F.Fab")
    for i in range(13):
        y = round(-19.05 + 2.54 * i, 2)
        s += pad_th(1 + i, -11.43, y, 1.7, 1.0, "rect" if i == 0 else "circle")
        s += pad_th(26 - i, 11.43, y, 1.7, 1.0)
    s += fp_rect(-13, -27.5, 13, 27.5, "F.Fab", 0.1)
    s += fp_rect(-8.89, 12.7, 8.89, 35.56, "F.Fab", 0.1)       # RJ45
    s += fp_rect(-7.62, -27.5, 7.62, -21.6, "F.Fab", 0.1)       # antenna area
    s += fp_text("user", "ANT", 0, -24.5, "F.Fab")
    s += fp_text("user", "RJ45", 0, 30, "F.Fab")
    s += fp_rect(-13.1, -27.6, 13.1, 27.6, "F.SilkS")
    s += fp_rect(-13.35, -27.85, 13.35, 35.81, "F.CrtYd", 0.05)
    for i, (n, name, _) in enumerate(WT32_LEFT):
        s += fp_text("user", name, -8.6, round(-19.05 + 2.54 * i, 2), "F.SilkS", 0.8)
    for i, (n, name, _) in enumerate(WT32_RIGHT):
        s += fp_text("user", name.split("/")[0], 8.6, round(-19.05 + 2.54 * i, 2), "F.SilkS", 0.8)
    return s + ")\n"


def fp_toroid_slot():
    # Coax (RG-58/RG-400) lies flat across the slot along X; the FT114 core
    # (OD 29, ID 19, H 7.5 mm) stands in the slot around it.
    s = fp_header("Toroid_FT114_Slot_Coax",
                  "FT114 toroid standing in a 9.5x30.5 mm board slot, 1-turn = coax centre conductor A-B, braid to SH at end A only, N-turn winding W1-W2",
                  "toroid tandem match FT114 coax")
    s += fp_text("reference", "REF**", 0, -18, "F.SilkS")
    s += fp_text("value", "FT114-43", 0, 18, "F.Fab")
    # slot (board cutout)
    w, h, r = 4.75, 15.25, 1.0
    s += (f'  (fp_rect (start {-w} {-h}) (end {w} {h}) (stroke (width 0.1) (type solid)) (fill none)'
          f' (layer "Edge.Cuts") (tstamp {u()}))\n')
    s += pad_th(1, -16, 0, 2.8, 1.4)          # A  coax centre
    s += pad_th(2, 16, 0, 2.8, 1.4)           # B  coax centre
    s += pad_th(3, -16, -4.2, 3.6, 2.0)       # SH braid (end A), two pads
    s += pad_th(3, -16, 4.2, 3.6, 2.0)
    s += pad_th(4, -7.62, 12.7, 2.2, 1.0)     # W1
    s += pad_th(5, 7.62, 12.7, 2.2, 1.0)      # W2
    s += fp_rect(-3.75, -14.5, 3.75, 14.5, "F.Fab", 0.1)
    s += fp_line(-16, 0, 16, 0, "F.Fab", 0.1)
    s += fp_text("user", "A", -19.2, 0, "F.SilkS", 1.0)
    s += fp_text("user", "B", 19.2, 0, "F.SilkS", 1.0)
    s += fp_text("user", "SH", -19.8, -4.2, "F.SilkS", 0.8)
    s += fp_text("user", "N", 0, 12.7, "F.SilkS", 1.0)
    s += fp_line(-5.25, -15.75, 5.25, -15.75, "F.SilkS")
    s += fp_line(-5.25, 15.75, 5.25, 15.75, "F.SilkS")
    s += fp_rect(-18.5, -16.5, 18.5, 16.5, "F.CrtYd", 0.05)
    return s + ")\n"


def fp_toroid_flat():
    s = fp_header("Toroid_FT114_Flat_Choke",
                  "FT114 toroid lying flat, held by an M3 nylon screw through the centre, winding leads to pads 1/2",
                  "toroid choke FT114")
    s += fp_text("reference", "REF**", 0, -17.5, "F.SilkS")
    s += fp_text("value", "FT114-43", 0, 0, "F.Fab")
    s += pad_th(1, -3.81, 17.5, 2.4, 1.1)
    s += pad_th(2, 3.81, 17.5, 2.4, 1.1)
    s += pad_np(0, 0, 3.2)
    s += fp_circle(0, 0, 14.5, "F.Fab", 0.1)
    s += fp_circle(0, 0, 9.5, "F.Fab", 0.1)
    s += fp_circle(0, 0, 15.6, "F.SilkS")
    import math
    r, hx, ty = 16.3, 5.9, 19.3
    t0 = math.degrees(math.acos(hx / r))
    pts = []
    n = 48
    for k in range(n + 1):
        t = (180 - t0) + (360 - 2 * (90 - t0) - 180 + 180 - 2 * t0 + 2 * t0) * 0  # placeholder
    pts = []
    start, end = 90 + (90 - t0), 360 + t0          # around the ring, skipping the bottom gap
    for k in range(n + 1):
        t = math.radians(start + (end - start) * k / n)
        pts.append((round(r * math.cos(t), 3), round(r * math.sin(t), 3)))
    pts += [(hx, ty), (-hx, ty)]
    s += "  (fp_poly (pts " + " ".join(f"(xy {x} {y})" for x, y in pts) + \
         f") (stroke (width 0.05) (type solid)) (fill none) (layer \"F.CrtYd\") (tstamp {u()}))\n"
    return s + ")\n"


def fp_coax():
    s = fp_header("Coax_Pigtail",
                  "Solder pads for a short coax pigtail (RG-58/RG-316/RG-400) to a panel SO-239: centre pad 1, braid split to both pads 2",
                  "coax pigtail SO-239")
    s += fp_text("reference", "REF**", 0, -6.8, "F.SilkS")
    s += fp_text("value", "COAX", 0, 6.8, "F.Fab")
    s += pad_th(1, 0, 0, 2.8, 1.4)
    s += pad_th(2, 0, -4.2, 3.6, 2.0)
    s += pad_th(2, 0, 4.2, 3.6, 2.0)
    s += fp_rect(-2.5, -6.2, 2.5, 6.2, "F.SilkS")
    s += fp_rect(-2.8, -6.5, 2.8, 6.5, "F.CrtYd", 0.05)
    return s + ")\n"


def write_footprints():
    d = os.path.join(KDIR, "BoltATAS.pretty")
    os.makedirs(d, exist_ok=True)
    for name, fn in [("WT32-ETH01_Socket", fp_wt32), ("Toroid_FT114_Slot_Coax", fp_toroid_slot),
                     ("Toroid_FT114_Flat_Choke", fp_toroid_flat), ("Coax_Pigtail", fp_coax)]:
        with open(os.path.join(d, name + ".kicad_mod"), "w") as f:
            f.write(fn())


def write_lib_tables():
    with open(os.path.join(KDIR, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n'
                '  (lib (name "BoltATAS")(type "KiCad")(uri "${KIPRJMOD}/BoltATAS.kicad_sym")(options "")(descr "BoltATAS project symbols"))\n)\n')
    with open(os.path.join(KDIR, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n'
                '  (lib (name "BoltATAS")(type "KiCad")(uri "${KIPRJMOD}/BoltATAS.pretty")(options "")(descr "BoltATAS project footprints"))\n)\n')


if __name__ == "__main__":
    write_symbols()
    write_footprints()
    write_lib_tables()
    print("libraries written to", KDIR)
