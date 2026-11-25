#!/bin/bash
# Host tests: autotune/motor/front-panel simulation, Ethernet/WiFi switching and front panel in the sketch.
# ArduinoJson (header-only) is needed for net_test: git clone https://github.com/bblanchon/ArduinoJson
set -e
cd "$(dirname "$0")"
AJ=${ARDUINOJSON_SRC:-../../../ArduinoJson/src}
g++ -std=c++17 -O2 -Wall -Wextra -I../BoltATAS sim_test.cpp -o sim_test && ./sim_test
for core in 2 3; do
  g++ -std=gnu++17 -Wall -Wextra -DARDUINO=10819 -DARDUINOJSON_ENABLE_PROGMEM=0 \
      -DARDUINOJSON_ENABLE_ARDUINO_STREAM=0 -DARDUINOJSON_ENABLE_ARDUINO_PRINT=0 \
      -DESP_ARDUINO_VERSION_MAJOR=$core -I stubs -I ../BoltATAS -I "$AJ" net_test.cpp -o net_test
  echo "== arduino-esp32 core $core.x"; ./net_test
done
