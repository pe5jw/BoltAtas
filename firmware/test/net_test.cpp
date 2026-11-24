// Host test for the Ethernet/WiFi switching in BoltATAS.ino:
// "one or the other, never both".
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
void digitalWrite(uint8_t p, uint8_t v) { if (p == PIN_K1_12V) g_k1 = v; if (p == PIN_K2_8V) g_k2 = v; }
int32_t analogReadMilliVolts(uint8_t) { return 250; }   // no RF, no motor current
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

static const char* linkName() { return link == Link::Eth ? "eth" : (link == Link::Wifi ? "wifi" : "none"); }

int main() {
  setup();
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

  printf(failures ? "%d FAILURES\n" : "NETWORK TEST PASSED\n", failures);
  return failures ? 1 : 0;
}
