// Host test for BoltATAS.ino:
//  1. Ethernet/WiFi switching: "one or the other, never both"
//  2. front panel: UP / DOWN / TUNE buttons and SWR LEDs, against the
//     real sketch with simulated pins and detector voltages
//   g++ -std=gnu++17 -DARDUINO=10819 -DARDUINOJSON_ENABLE_PROGMEM=0 
//       -DARDUINOJSON_ENABLE_ARDUINO_STREAM=0 -DARDUINOJSON_ENABLE_ARDUINO_PRINT=0 
//       -I stubs -I ../BoltATAS -I <ArduinoJson>/src net_test.cpp -o net_test
#include "../BoltATAS/BoltATAS.ino"

// ── stub implementations with controllable state ────────────
static unsigned long g_ms = 0;
static NetworkEventCb g_cb = nullptr;
static wifi_mode_t g_wifiMode = WIFI_OFF;
static unsigned long g_wifiBeganAt = 0;
static bool g_wifiBegun = false;
static int g_k1 = 0, g_k2 = 0;
static int g_pin[40];                 // output levels written by the sketch
static int g_btn[40];                 // input levels (HIGH = released)
static int32_t g_mv[40];              // ADC millivolts per pin

HardwareSerial Serial;
ETHClass ETH;
WiFiClass WiFi;
MDNSResponder MDNS;
ArduinoOTAClass ArduinoOTA;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
NetworkManager Network;
int NetworkManager::onEvent(NetworkEventCb cb, arduino_event_id_t) { g_cb = cb; return 0; }
bool ETHClass::begin(eth_phy_type_t t, int32_t a, int mdc, int mdio, int pwr, eth_clock_mode_t c) {
  return t == ETH_PHY_LAN8720 && a == 1 && mdc == 23 && mdio == 18 && pwr == 16 && c == ETH_CLOCK_GPIO0_IN;
}
#else
int WiFiClass::onEvent(NetworkEventCb cb, arduino_event_id_t) { g_cb = cb; return 0; }
bool ETHClass::begin(uint8_t a, int pwr, int mdc, int mdio, eth_phy_type_t t, eth_clock_mode_t c) {
  return t == ETH_PHY_LAN8720 && a == 1 && mdc == 23 && mdio == 18 && pwr == 16 && c == ETH_CLOCK_GPIO0_IN;
}
#endif
bool ETHClass::setHostname(const char*) { return true; }
IPAddress ETHClass::localIP() { return IPAddress(); }
String ETHClass::macAddress() { return String("eth"); }
bool WiFiClass::mode(wifi_mode_t m) { g_wifiMode = m; if (m == WIFI_OFF) g_wifiBegun = false; return true; }
bool WiFiClass::setHostname(const char*) { return true; }
int WiFiClass::begin(const char*, const char*) { g_wifiBegun = true; g_wifiBeganAt = g_ms; return 0; }
bool WiFiClass::disconnect(bool off, bool, unsigned long) { g_wifiBegun = false; if (off) g_wifiMode = WIFI_OFF; return true; }
bool WiFiClass::setAutoReconnect(bool) { return true; }
wl_status_t WiFiClass::status() {
  return (g_wifiMode == WIFI_STA && g_wifiBegun && g_ms - g_wifiBeganAt > 2000) ? WL_CONNECTED : WL_IDLE_STATUS;
}
IPAddress WiFiClass::localIP() { return IPAddress(); }
String WiFiClass::macAddress() { return String("wifi"); }
int8_t WiFiClass::RSSI() { return -60; }
bool MDNSResponder::begin(const char*) { return true; }
bool MDNSResponder::addService(const char*, const char*, uint16_t) { return true; }
ArduinoOTAClass& ArduinoOTAClass::setHostname(const char*) { return *this; }
ArduinoOTAClass& ArduinoOTAClass::setPassword(const char*) { return *this; }
ArduinoOTAClass& ArduinoOTAClass::onStart(THandlerFunction) { return *this; }
void ArduinoOTAClass::begin() {}
void ArduinoOTAClass::handle() {}
bool Preferences::begin(const char*, bool, const char*) { return true; }
void Preferences::end() {}
size_t Preferences::putUInt(const char*, uint32_t) { return 4; }
size_t Preferences::putFloat(const char*, float) { return 4; }
uint32_t Preferences::getUInt(const char*, uint32_t d) { return d; }
float Preferences::getFloat(const char*, float d) { return d; }
WebServer::WebServer(int) {}
void WebServer::on(const char*, HTTPMethod, THandlerFunction) {}
void WebServer::onNotFound(THandlerFunction) {}
void WebServer::begin() {}
void WebServer::handleClient() {}
String WebServer::arg(const String&) const { return String(""); }
bool WebServer::hasArg(const String&) const { return false; }
void WebServer::sendHeader(const String&, const String&, bool) {}
void WebServer::send(int, const char*, const String&) {}
void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t p, uint8_t v) { g_pin[p] = v; if (p == PIN_K1_12V) g_k1 = v; if (p == PIN_K2_8V) g_k2 = v; }
int digitalRead(uint8_t p) { return g_btn[p]; }
int32_t analogReadMilliVolts(uint8_t p) { return g_mv[p]; }   // 250 mV: no RF; IMOT 125 mA
void analogReadResolution(uint8_t) {}
void analogSetPinAttenuation(uint8_t, adc_attenuation_t) {}
unsigned long millis() { return g_ms; }
void delay(uint32_t ms) { g_ms += ms; }

// ── harness ────────────────────────────────────────────────
static int failures = 0;
static bool ethHasIp = false;
#define CHECK(c, msg) do { if (!(c)) { failures++; printf("FAIL t=%lu ms: %s\n", g_ms, msg); } } while (0)

static void ev(arduino_event_id_t e) {
  if (e == ARDUINO_EVENT_ETH_GOT_IP) ethHasIp = true;
  if (e == ARDUINO_EVENT_ETH_DISCONNECTED || e == ARDUINO_EVENT_ETH_LOST_IP) ethHasIp = false;
  g_cb(e);
}

static void runUntil(unsigned long t) {
  while (g_ms < t) {
    loop();
    // invariant: never an Ethernet address and WiFi radio on at the same time
    CHECK(!(ethHasIp && g_wifiMode != WIFI_OFF), "Ethernet has IP while WiFi is on");
    CHECK(!(g_k1 && g_k2), "both relays on");
  }
}

// Detector voltages for a carrier of w watts at the given SWR (AD8307
// 25 mV/dB, intercept -84 dBm, 42.5 dB coupling); w = 0: no carrier.
static void setRf(float w, float swr) {
  if (w <= 0) { g_mv[PIN_ADC_FWD] = g_mv[PIN_ADC_REF] = 250; return; }
  const float dbm = 10.0f * log10f(w) + 30.0f;
  const float rho = (swr - 1.0f) / (swr + 1.0f);
  const float rl = -20.0f * log10f(rho > 1e-4f ? rho : 1e-4f);
  g_mv[PIN_ADC_FWD] = (int32_t)(25.0f * (dbm - 42.5f + 84.0f));
  g_mv[PIN_ADC_REF] = (int32_t)(25.0f * (dbm - rl - 42.5f + 84.0f));
}

static uint8_t swrLedMask() {
  return (g_pin[PIN_SWR_G] ? 1 : 0) | (g_pin[PIN_SWR_O] ? 2 : 0) | (g_pin[PIN_SWR_R] ? 4 : 0);
}

// Run for ms; returns the OR of all SWR LED masks seen and whether a relay was on.
static uint8_t runSeen(unsigned long ms, bool* relay = nullptr) {
  uint8_t seen = 0;
  bool rel = false;
  const unsigned long end = g_ms + ms;
  while (g_ms < end) {
    loop();
    seen |= swrLedMask();
    rel |= g_k1 || g_k2;
    CHECK(!(g_k1 && g_k2), "both relays on");
  }
  if (relay) *relay = rel;
  return seen;
}

static void testPanel() {
  bool rel;
  // a. no carrier: UP runs K2 (8 V) while held, release stops
  g_btn[PIN_BTN_UP] = LOW;
  runSeen(300);
  CHECK(g_k2 && !g_k1, "UP held without carrier: K2 on");
  g_btn[PIN_BTN_UP] = HIGH;
  runSeen(100);
  CHECK(!g_k1 && !g_k2, "UP released: motor off");
  // b. DOWN runs K1 (12 V)
  g_btn[PIN_BTN_DOWN] = LOW;
  runSeen(300);
  CHECK(g_k1 && !g_k2, "DOWN held: K1 on");
  g_btn[PIN_BTN_DOWN] = HIGH;
  runSeen(100);
  CHECK(!g_k1 && !g_k2, "DOWN released: motor off");
  printf("t=%5lu UP/DOWN without carrier ok\n", g_ms);
  // c. TUNE without carrier: refused, red flashes, motor stays off
  g_btn[PIN_BTN_TUNE] = LOW;
  uint8_t seen = runSeen(100, &rel);
  g_btn[PIN_BTN_TUNE] = HIGH;
  seen |= runSeen(1000, &rel);
  CHECK(seen == 4 && !rel, "TUNE without carrier: only red flashes, no motor");
  CHECK(!tuner.active(), "no tune without carrier");
  // d. SWR colours with a 10 W carrier
  setRf(10, 1.2f);  runSeen(200);  CHECK(swrLedMask() == 1, "SWR 1.2 -> green");
  setRf(10, 2.0f);  runSeen(200);  CHECK(swrLedMask() == 2, "SWR 2.0 -> orange");
  setRf(10, 3.0f);  runSeen(200);  CHECK(swrLedMask() == 4, "SWR 3.0 -> red");
  setRf(0, 1.0f);   runSeen(1000); CHECK(swrLedMask() == 0, "carrier off -> LEDs off");
  printf("t=%5lu SWR LEDs green/orange/red/off ok\n", g_ms);
  // e. 100 W: UP refused, orange+red flash
  setRf(100, 1.2f); runSeen(200);
  g_btn[PIN_BTN_UP] = LOW;
  seen = runSeen(300, &rel);
  g_btn[PIN_BTN_UP] = HIGH;
  runSeen(1000);
  CHECK(!rel && (seen & 6) == 6, "UP at 100 W: refused with orange+red flash");
  // f. 10 W: UP runs; power goes to 100 W while held -> stops
  setRf(10, 1.2f); runSeen(600);
  g_btn[PIN_BTN_UP] = LOW;
  runSeen(300);
  CHECK(g_k2, "UP at 10 W: K2 on");
  setRf(100, 1.2f);
  runSeen(150);
  CHECK(!g_k1 && !g_k2, "power above 25 W during a manual move: motor stops");
  g_btn[PIN_BTN_UP] = HIGH;
  setRf(10, 3.0f);
  runSeen(1200);
  // g. TUNE with carrier starts autotune, second press aborts
  g_btn[PIN_BTN_TUNE] = LOW;  runSeen(100);  g_btn[PIN_BTN_TUNE] = HIGH;  runSeen(300);
  CHECK(tuner.active(), "TUNE with 10 W carrier: autotune running");
  g_btn[PIN_BTN_TUNE] = LOW;  runSeen(100);  g_btn[PIN_BTN_TUNE] = HIGH;  runSeen(100);
  CHECK(!tuner.active() && tuner.result() == atas::TuneResult::Aborted, "second TUNE press aborts");
  CHECK(!g_k1 && !g_k2, "motor off after abort");
  printf("t=%5lu buttons with carrier ok\n", g_ms);
  setRf(0, 1.0f);
}

static const char* linkName() { return link == Link::Eth ? "eth" : (link == Link::Wifi ? "wifi" : "none"); }

int main() {
  for (int i = 0; i < 40; i++) { g_btn[i] = HIGH; g_mv[i] = 250; }
  setup();
  CHECK(swrLedMask() == 0, "SWR LEDs off before the first loop");
  runUntil(60);
  CHECK(swrLedMask() == 7, "lamp test: all SWR LEDs on at boot");
  CHECK(g_cb != nullptr, "network event handler not registered");
  ev(ARDUINO_EVENT_ETH_START);

  // 1. boot without cable -> WiFi after the Ethernet wait
  runUntil(3000);
  CHECK(g_wifiMode == WIFI_OFF, "WiFi must stay off during Ethernet wait");
  runUntil(9000);
  CHECK(g_wifiMode == WIFI_STA && link == Link::Wifi, "WiFi should be up without cable");
  printf("t=%5lu no cable        -> %s\n", g_ms, linkName());

  // 2. plug cable: WiFi off at link-up, before DHCP
  ev(ARDUINO_EVENT_ETH_CONNECTED);
  runUntil(g_ms + 5);
  CHECK(g_wifiMode == WIFI_OFF, "WiFi must go off as soon as the cable is in");
  runUntil(g_ms + 1500);
  ev(ARDUINO_EVENT_ETH_GOT_IP);
  runUntil(g_ms + 100);
  CHECK(link == Link::Eth, "should be on Ethernet");
  printf("t=%5lu cable plugged   -> %s\n", g_ms, linkName());

  // 3. pull cable: WiFi again after grace time
  ev(ARDUINO_EVENT_ETH_DISCONNECTED);
  runUntil(g_ms + 3000);
  CHECK(g_wifiMode == WIFI_OFF, "WiFi must wait for grace time");
  runUntil(g_ms + 5000);
  CHECK(link == Link::Wifi, "WiFi after cable pulled");
  printf("t=%5lu cable pulled    -> %s\n", g_ms, linkName());

  // 4. cable without DHCP: WiFi stays off 20 s, then fallback
  ev(ARDUINO_EVENT_ETH_CONNECTED);
  runUntil(g_ms + 10000);
  CHECK(g_wifiMode == WIFI_OFF, "WiFi off while waiting for DHCP");
  runUntil(g_ms + 15000);
  CHECK(link == Link::Wifi, "WiFi fallback when Ethernet gets no address");
  printf("t=%5lu cable, no DHCP  -> %s\n", g_ms, linkName());

  // 5. DHCP finally answers: back to Ethernet, WiFi off
  ev(ARDUINO_EVENT_ETH_GOT_IP);
  runUntil(g_ms + 100);
  CHECK(link == Link::Eth && g_wifiMode == WIFI_OFF, "late DHCP -> Ethernet only");
  printf("t=%5lu late DHCP       -> %s\n", g_ms, linkName());

  testPanel();

  printf(failures ? "%d FAILURES\n" : "NETWORK + FRONT PANEL TEST PASSED\n", failures);
  return failures ? 1 : 0;
}
