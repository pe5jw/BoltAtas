#!/bin/bash
# Rebuild libraries, schematic, netlist, PCB (place -> autoroute -> finish), DRC, fab outputs and docs images.
# Needs KiCad 7 (kicad-cli + pcbnew python) and Java 25 + freerouting 2.5 jar ($FREEROUTING).
set -e
cd "$(dirname "$0")/.."
FREEROUTING=${FREEROUTING:-freerouting-2.5.0.jar}
JAVA=${JAVA:-java}
python3 tools/gen_libs.py
python3 tools/gen_sch.py
kicad-cli sch export netlist --format kicadsexpr -o BoltATAS.net BoltATAS.kicad_sch
python3 tools/check_netlist.py BoltATAS.net
python3 tools/gen_pcb.py place BoltATAS.net
cp BoltATAS.kicad_pcb /tmp/BoltATAS.placed.kicad_pcb
# freerouting is not deterministic: retry until DRC is clean (no errors, no dangling vias)
for try in 1 2 3 4 5 6 7 8; do
  cp /tmp/BoltATAS.placed.kicad_pcb BoltATAS.kicad_pcb
  rm -f BoltATAS.ses
  "$JAVA" -jar "$FREEROUTING" -de BoltATAS.dsn -do BoltATAS.ses -mp 40 --gui.enabled=false > freerouting.log 2>&1
  python3 tools/gen_pcb.py finish BoltATAS.net
  if python3 tools/drc.py && ! grep -q via_dangling BoltATAS-drc.rpt; then
    echo "routing attempt $try: clean"
    python3 tools/fab.py
    exit 0
  fi
  echo "routing attempt $try: not clean, retrying"
done
exit 1
