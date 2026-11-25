/*
 * BoltATAS v1.2 — WT32-ETH01 controller for the Yaesu ATAS-100
 * PE5JW, 2026-11-25
 *
 * New in v1.2 (hardware v1.3): front panel
 *  - SWR LEDs: green < 1.5, orange 1.5 .. 2.5, red >= 2.5 (thresholds
 *    in /cal), off without a carrier. They also give feedback: tune ok =
 *    3x green, best effort = 3x orange, tune failed or no carrier = 3x red,
 *    power too high = 3x orange+red. All three light briefly at boot.
 *  - UP / DOWN buttons: the motor runs while the button is held (max
 *    MOTOR_MAX_RUN_MS), with or without a carrier. TUNE button: autotune
 *    when there is a carrier, a second press aborts.
 *  - The motor never moves above MANUAL_MAX_FWD_W (25 W): buttons and
 *    /up /down are refused, and a running manual move stops when the
 *    power goes above it (moving the whip under high power can arc).
 *
 * Changes in v1.1 from v1.0 (review):
 *  - WT32-ETH01 Ethernet init with the right PHY settings (addr 1,
 *    power/osc-enable GPIO16, MDC 23, MDIO 18, clock in on GPIO0).
 *    v1.0 called ETH.begin() with ESP32 defaults: Ethernet never came up.
 *  - Nothing blocks any more: motor, autotune and network are state
 *    machines driven from loop(). /stop now works while the motor runs.
 *  - Autotune rewritten (AtasCore.h) and tested in simulation
 *    (firmware/test/sim_test.cpp). v1.0 stopped after one step, because
 *    stopMotor() overwrote the TUNING state.
 *  - Tuning is refused above TUNE_MAX_FWD_W (moving the whip under high
 *    power can arc the contacts), and stops if RF disappears.
 *  - Break-before-make relay sequencing with 30 ms dead time, max run
 *    time for manual moves, and a keep-alive while tuning, so the motor
 *    stops by itself if the loop ever hangs.
 *  - AD8307 conversion matches hardware v1.1: unloaded output (25 mV/dB),
 *    13 dB pad after the coupler, analogReadMilliVolts() (eFuse calibrated).
 *  - Motor current sense (INA180 on IO35): detects shorted or open coax.
 *  - Calibration stored in flash (/cal), mDNS (boltatas.local), OTA.
 *  - Ethernet/WiFi never both: WiFi only starts when there is no
 *    Ethernet link and is switched off the moment a cable is plugged in.
 *
 * Pins (hardware v1.3, see schematic; v1.1/v1.2 have no front panel):
 *   IO36  ADC  FWD detector (AD8307 U4)
 *   IO39  ADC  REF detector (AD8307 U5)
 *   IO35  ADC  motor current (INA180A1, 2 mV per mA)
 *   IO4   OUT  K1: +12 V on coax = whip longer  = resonance DOWN
 *   IO32  OUT  K2: +8 V on coax  = whip shorter = resonance UP
 *   IO33  OUT  status LED
 *   IO2   OUT  SWR LED green   (strap pin: the LED to GND keeps it low at boot)
 *   IO12  OUT  SWR LED orange  (strap pin: idem)
 *   IO14  OUT  SWR LED red
 *   IO15  IN   UP button   (to GND, 10k pull-up; strap pin, pull-up is its default)
 *   IO5   IN   DOWN button (to GND, 10k pull-up; strap pin, idem)
 *   IO17  IN   TUNE button (to GND, 10k pull-up)
 *
 * HTTP API (all GET, JSON replies, CORS open):
 *   /status                 measurements, motor, tune state, network
 *   /up       /down         run until /stop (limited to MOTOR_MAX_RUN_MS),
 *                           refused above MANUAL_MAX_FWD_W
 *   /up?ms=N  /down?ms=N    run N ms (10..MOTOR_MAX_RUN_MS)
 *   /stop                   stop motor, abort tuning
 *   /tune                   start autotune (needs a carrier, <= 25 W)
 *   /tune?target=1.5        target SWR (1.1 .. 3.0)
 *   /tune?dir=up|down       first direction (up = frequency went up)
 *   /cal                    show calibration
 *   /cal?fwd_w=10           set FWD coupling from a known forward power
 *   /cal?ref_w=10           set REF coupling (feed RF into the ANT port)
 *   /cal?fwd_cpl=42.5&ref_cpl=42.5&travel_ms=45000   set directly
 *   /cal?swr_green=1.5&swr_red=2.5   SWR LED thresholds
 *   /cal?reset=1            back to defaults
 *   Manual /up and /down abort a running autotune.
 *
 * Build: Arduino IDE / arduino-cli, board "WT32-ETH01 Ethernet Module"
 * (or "ESP32 Dev Module"), arduino-esp32 core 2.0.x or 3.x.
 * Library: ArduinoJson 6.21+ or 7.x.
 * Put WiFi credentials in secrets.h (see the defines below).
 */

#include <Arduino.h>
#include <ETH.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <ArduinoJson.h>

#include "AtasCore.h"

#if __has_include("secrets.h")
#include "secrets.h"
#endif

// ─────────────────────────────────────────────
//  CONFIGURATION
// ─────────────────────────────────────────────
#ifndef WIFI_SSID
#define WIFI_SSID     "YourSSID"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YourPassword"
#endif
#ifndef OTA_PASSWORD
#define OTA_PASSWORD  "boltatas"
#endif

static const char* HOSTNAME   = "boltatas";
static const char* FW_VERSION = "1.2.0";

static const uint32_t MOTOR_MAX_RUN_MS = 15000;   // manual moves
static const float    TUNE_TARGET_SWR  = 1.5f;
static const float    TUNE_MAX_FWD_W   = 25.0f;
static const float    MANUAL_MAX_FWD_W = 25.0f;   // buttons and /up /down
static const uint32_t ETH_WAIT_MS      = 4000;    // at boot, before WiFi
static const uint32_t ETH_GRACE_MS     = 5000;    // cable pulled: wait before WiFi
static const uint32_t ETH_DHCP_MS      = 20000;   // cable in but no IP: give up, use WiFi

// Motor current sense (INA180A1, gain 20, 0.1 ohm): 2 mV per mA.
#define HAS_MOTOR_SENSE 1
static const float    MOTOR_MV_PER_MA  = 2.0f;
static const uint16_t MOTOR_SHORT_MA   = 900;     // coax / antenna short
static const uint16_t MOTOR_OPEN_MA    = 10;      // no ATAS connected (0 = off)

// ─────────────────────────────────────────────
//  PINS
// ─────────────────────────────────────────────
#define PIN_ADC_FWD  36
#define PIN_ADC_REF  39
#define PIN_ADC_IMOT 35
#define PIN_K1_12V   4
#define PIN_K2_8V    32
#define PIN_LED      33
#define PIN_SWR_G    2
#define PIN_SWR_O    12
#define PIN_SWR_R    14
#define PIN_BTN_UP   15
#define PIN_BTN_DOWN 5
#define PIN_BTN_TUNE 17

// WT32-ETH01 Ethernet (LAN8720A)
#define WT32_PHY_ADDR   1
#define WT32_PHY_POWER  16    // enables the 50 MHz oscillator
#define WT32_PHY_MDC    23
#define WT32_PHY_MDIO   18

// ─────────────────────────────────────────────
//  GLOBALS
// ─────────────────────────────────────────────
static void setRelays(bool k1_12v, bool k2_8v) {
  if (k1_12v && k2_8v) k1_12v = k2_8v = false;     // never both
  digitalWrite(PIN_K1_12V, k1_12v ? HIGH : LOW);
  digitalWrite(PIN_K2_8V,  k2_8v  ? HIGH : LOW);
}

static WebServer   server(80);
static Preferences prefs;
static atas::RfConfig rfCfg;
static atas::Motor    motor(setRelays, MOTOR_MAX_RUN_MS);
static atas::Tuner    tuner(motor);
static atas::RfReading lastRf = {};
static float          targetSwr = TUNE_TARGET_SWR;
static uint16_t       motorMa = 0;
static atas::FrontPanel panel;
static atas::SwrLeds    swrLeds;

enum class MotorFault : uint8_t { None, Open, Short };
static MotorFault motorFault = MotorFault::None;

static const char* faultName(MotorFault f) {
  return f == MotorFault::Open ? "open" : (f == MotorFault::Short ? "short" : "none");
}

// ─────────────────────────────────────────────
//  MEASUREMENT
// ─────────────────────────────────────────────
// FWD and REF sampled interleaved, so both see the same moment of a
// varying (SSB) signal.
static atas::RfReading measureRf(uint8_t pairs) {
  uint32_t f = 0, r = 0;
  for (uint8_t i = 0; i < pairs; i++) {
    f += analogReadMilliVolts(PIN_ADC_FWD);
    r += analogReadMilliVolts(PIN_ADC_REF);
  }
  return atas::computeRf((float)f / pairs, (float)r / pairs, rfCfg);
}

static float detectorDbm(int pin) {
  uint32_t s = 0;
  for (int i = 0; i < 64; i++) s += analogReadMilliVolts(pin);
  return atas::detMvToDbm((float)s / 64.0f, rfCfg);
}

static uint16_t measureMotorMa() {
#if HAS_MOTOR_SENSE
  uint32_t s = 0;
  for (int i = 0; i < 8; i++) s += analogReadMilliVolts(PIN_ADC_IMOT);
  return (uint16_t)((float)s / 8.0f / MOTOR_MV_PER_MA);
#else
  return 0;
#endif
}

// ─────────────────────────────────────────────
//  CALIBRATION (NVS)
// ─────────────────────────────────────────────
static void loadCal() {
  prefs.begin("boltatas", true);
  rfCfg.fwd_coupling_db = prefs.getFloat("fwd_cpl", 42.5f);
  rfCfg.ref_coupling_db = prefs.getFloat("ref_cpl", 42.5f);
  tuner.cfg.full_travel_ms = prefs.getUInt("travel_ms", 45000);
  swrLeds.cfg.green_below = prefs.getFloat("swr_g", 1.5f);
  swrLeds.cfg.red_from = prefs.getFloat("swr_r", 2.5f);
  prefs.end();
}

static void saveCal() {
  prefs.begin("boltatas", false);
  prefs.putFloat("fwd_cpl", rfCfg.fwd_coupling_db);
  prefs.putFloat("ref_cpl", rfCfg.ref_coupling_db);
  prefs.putUInt("travel_ms", tuner.cfg.full_travel_ms);
  prefs.putFloat("swr_g", swrLeds.cfg.green_below);
  prefs.putFloat("swr_r", swrLeds.cfg.red_from);
  prefs.end();
}

// ─────────────────────────────────────────────
//  NETWORK — Ethernet first, WiFi only without a cable, never both
// ─────────────────────────────────────────────
enum class Link : uint8_t { None, Eth, Wifi };
static volatile bool ethLink = false;   // set from the network event task
static volatile bool ethIp = false;
static bool     wifiOn = false;
static bool     servicesStarted = false;
static uint32_t ethLostAt = 0;
static Link     link = Link::None;

static void onNetEvent(arduino_event_id_t event) {
  // Runs in the event task: only set flags, act in loop().
  switch (event) {
    case ARDUINO_EVENT_ETH_START:        ETH.setHostname(HOSTNAME); break;
    case ARDUINO_EVENT_ETH_CONNECTED:    ethLink = true; break;
    case ARDUINO_EVENT_ETH_GOT_IP:       ethIp = true; break;
    case ARDUINO_EVENT_ETH_LOST_IP:      ethIp = false; break;
    case ARDUINO_EVENT_ETH_DISCONNECTED: ethLink = false; ethIp = false; break;
    case ARDUINO_EVENT_ETH_STOP:         ethLink = false; ethIp = false; break;
    default: break;
  }
}

static void wifiStart() {
  if (wifiOn) return;
  Serial.println("[NET] no Ethernet link -> WiFi");
  WiFi.setHostname(HOSTNAME);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  wifiOn = true;
}

static void wifiStop() {
  if (!wifiOn) return;
  Serial.println("[NET] Ethernet link -> WiFi off");
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  wifiOn = false;
}

static void startServices() {
  if (servicesStarted) return;
  servicesStarted = true;
  if (MDNS.begin(HOSTNAME)) MDNS.addService("http", "tcp", 80);
  ArduinoOTA.setHostname(HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { tuner.abort(millis()); motor.stop(millis()); });
  ArduinoOTA.begin();
}

static void netUpdate(uint32_t now) {
  static bool lastEthLink = false;
  static uint32_t ethLinkAt = 0;
  const bool el = ethLink;
  const bool eip = ethIp;
  if (el && !lastEthLink) ethLinkAt = now;        // cable just plugged in
  if (!el && lastEthLink) ethLostAt = now;        // cable just pulled
  lastEthLink = el;

  if (el && eip) {
    wifiStop();                                   // Ethernet has an address: WiFi off
  } else if (el) {
    // Link but no DHCP lease yet: keep WiFi off for a while, then give up.
    if ((uint32_t)(now - ethLinkAt) < ETH_DHCP_MS) wifiStop();
    else wifiStart();
  } else if (now >= ETH_WAIT_MS && (uint32_t)(now - ethLostAt) >= ETH_GRACE_MS) {
    wifiStart();                                  // no cable
  }

  Link l = Link::None;
  if (el && eip) l = Link::Eth;
  else if (wifiOn && WiFi.status() == WL_CONNECTED) l = Link::Wifi;
  if (l != link) {
    link = l;
    if (l == Link::Eth)  Serial.printf("[NET] Ethernet %s\n", ETH.localIP().toString().c_str());
    if (l == Link::Wifi) Serial.printf("[NET] WiFi %s\n", WiFi.localIP().toString().c_str());
    if (l != Link::None) startServices();
  }
}

// ─────────────────────────────────────────────
//  HTTP
// ─────────────────────────────────────────────
#if ARDUINOJSON_VERSION_MAJOR >= 7
#define JSON_DOC(name) JsonDocument name
#else
#define JSON_DOC(name) StaticJsonDocument<1024> name
#endif

static String num(float v, int digits) { return String(v, digits); }

static void sendJson(int code, JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Cache-Control", "no-cache");
  server.send(code, "application/json", out);
}

static void sendSimple(int code, const char* action, const char* error = nullptr) {
  JSON_DOC(doc);
  doc["ok"] = (error == nullptr);
  doc["action"] = action;
  if (error) doc["error"] = error;
  sendJson(code, doc);
}

static const char* motorStateName() {
  if (tuner.active()) return "tuning";
  switch (motor.energized()) {
    case atas::Dir::Up:   return "up";
    case atas::Dir::Down: return "down";
    default:              return "stopped";
  }
}

static void handleStatus() {
  JSON_DOC(doc);
  doc["fw"] = FW_VERSION;
  doc["hostname"] = HOSTNAME;
  doc["link"] = link == Link::Eth ? "ethernet" : (link == Link::Wifi ? "wifi" : "none");
  doc["ip"] = link == Link::Eth ? ETH.localIP().toString() : WiFi.localIP().toString();
  doc["mac"] = link == Link::Wifi ? WiFi.macAddress() : ETH.macAddress();
  if (link == Link::Wifi) doc["rssi"] = WiFi.RSSI();
  doc["uptime_s"] = millis() / 1000;

  doc["state"] = motorStateName();
  doc["rf"] = lastRf.valid;
  if (lastRf.valid) {
    doc["swr"]   = serialized(num(lastRf.swr, 2));
    doc["rl_db"] = serialized(num(lastRf.rl_db, 1));
  } else {
    doc["swr"]   = nullptr;
    doc["rl_db"] = nullptr;
  }
  doc["fwd_w"]   = serialized(num(lastRf.valid ? lastRf.fwd_w : 0.0f, 1));
  doc["ref_w"]   = serialized(num(lastRf.valid ? lastRf.ref_w : 0.0f, 2));
  doc["fwd_dbm"] = serialized(num(lastRf.fwd_dbm, 1));
  doc["ref_dbm"] = serialized(num(lastRf.ref_dbm, 1));
  doc["motor_ma"] = motorMa;
  doc["motor_fault"] = faultName(motorFault);
  doc["swr_led"] = atas::SwrLeds::name(swrLeds.level());
  JsonObject b = doc["buttons"].to<JsonObject>();
  b["up"] = panel.upPressed();
  b["down"] = panel.downPressed();
  b["tune"] = panel.tunePressed();

  JsonObject t = doc["tune"].to<JsonObject>();
  t["state"]    = atas::tuneStateName(tuner.state());
  t["result"]   = atas::tuneResultName(tuner.result());
  t["steps"]    = tuner.steps();
  t["target"]   = serialized(num(targetSwr, 2));
  t["best_swr"] = serialized(num(tuner.bestSwr(), 2));
  sendJson(200, doc);
}

static uint32_t argMs() {
  if (!server.hasArg("ms")) return 0;                 // 0 = until /stop
  long ms = server.arg("ms").toInt();
  if (ms < 10) ms = 10;
  if (ms > (long)MOTOR_MAX_RUN_MS) ms = MOTOR_MAX_RUN_MS;
  return (uint32_t)ms;
}

// Shared by HTTP and the front panel. Returns nullptr or an error name.
static const char* startManual(atas::Dir d, uint32_t ms, uint32_t now) {
  tuner.abort(now);                                   // manual overrides autotune
  if (lastRf.valid && lastRf.fwd_w > MANUAL_MAX_FWD_W) { motor.stop(now); return "power_too_high"; }
  motorFault = MotorFault::None;
  motor.run(d, ms, now);
  return nullptr;
}

static const char* startTune(float target, atas::Dir first, uint32_t now) {
  atas::RfReading r = measureRf(32);
  if (!r.valid) return "no_rf";
  if (r.fwd_w > TUNE_MAX_FWD_W) return "power_too_high";
  targetSwr = target;
  tuner.cfg.target_swr = target;
  tuner.cfg.max_fwd_w = TUNE_MAX_FWD_W;
  tuner.cfg.min_fwd_w = rfCfg.min_fwd_w;
  motorFault = MotorFault::None;
  tuner.start(now, first);
  return nullptr;
}

static void manualMove(atas::Dir d, const char* action) {
  const char* err = startManual(d, argMs(), millis());
  sendSimple(err ? 409 : 200, action, err);
}

static void handleUp()   { manualMove(atas::Dir::Up, "up"); }
static void handleDown() { manualMove(atas::Dir::Down, "down"); }

static void handleStop() {
  const uint32_t now = millis();
  tuner.abort(now);
  motor.stop(now);
  sendSimple(200, "stop");
}

static void handleTune() {
  float target = TUNE_TARGET_SWR;
  if (server.hasArg("target")) {
    target = server.arg("target").toFloat();
    if (target < 1.1f || target > 3.0f) target = TUNE_TARGET_SWR;
  }
  atas::Dir first = atas::Dir::Up;
  if (server.hasArg("dir") && server.arg("dir") == "down") first = atas::Dir::Down;

  const char* err = startTune(target, first, millis());
  if (err) { sendSimple(409, "tune", err); return; }

  JSON_DOC(doc);
  doc["ok"] = true;
  doc["action"] = "tune";
  doc["target"] = serialized(num(target, 2));
  doc["dir"] = first == atas::Dir::Down ? "down" : "up";
  sendJson(200, doc);
}

static void handleCal() {
  bool changed = false;
  if (server.hasArg("reset")) {
    rfCfg.fwd_coupling_db = rfCfg.ref_coupling_db = 42.5f;
    tuner.cfg.full_travel_ms = 45000;
    swrLeds.cfg.green_below = 1.5f;
    swrLeds.cfg.red_from = 2.5f;
    changed = true;
  }
  if (server.hasArg("fwd_w")) {      // known forward power on the line now
    float w = server.arg("fwd_w").toFloat();
    if (w > 0.1f) { rfCfg.fwd_coupling_db = atas::wToDbm(w) - detectorDbm(PIN_ADC_FWD); changed = true; }
  }
  if (server.hasArg("ref_w")) {      // coupler fed backwards with known power
    float w = server.arg("ref_w").toFloat();
    if (w > 0.1f) { rfCfg.ref_coupling_db = atas::wToDbm(w) - detectorDbm(PIN_ADC_REF); changed = true; }
  }
  if (server.hasArg("fwd_cpl")) { rfCfg.fwd_coupling_db = server.arg("fwd_cpl").toFloat(); changed = true; }
  if (server.hasArg("ref_cpl")) { rfCfg.ref_coupling_db = server.arg("ref_cpl").toFloat(); changed = true; }
  if (server.hasArg("travel_ms")) {
    long t = server.arg("travel_ms").toInt();
    if (t >= 5000 && t <= 120000) { tuner.cfg.full_travel_ms = (uint32_t)t; changed = true; }
  }
  if (server.hasArg("swr_green") || server.hasArg("swr_red")) {
    float g = server.hasArg("swr_green") ? server.arg("swr_green").toFloat() : swrLeds.cfg.green_below;
    float r = server.hasArg("swr_red") ? server.arg("swr_red").toFloat() : swrLeds.cfg.red_from;
    if (g >= 1.05f && r > g + 0.1f && r <= 10.0f) {
      swrLeds.cfg.green_below = g;
      swrLeds.cfg.red_from = r;
      changed = true;
    }
  }
  if (changed) saveCal();

  JSON_DOC(doc);
  doc["fwd_cpl"]   = serialized(num(rfCfg.fwd_coupling_db, 2));
  doc["ref_cpl"]   = serialized(num(rfCfg.ref_coupling_db, 2));
  doc["travel_ms"] = tuner.cfg.full_travel_ms;
  doc["swr_green"] = serialized(num(swrLeds.cfg.green_below, 2));
  doc["swr_red"]   = serialized(num(swrLeds.cfg.red_from, 2));
  doc["saved"]     = changed;
  sendJson(200, doc);
}

static void handleNotFound() { sendSimple(404, "none", "not_found"); }

// ─────────────────────────────────────────────
//  MOTOR SUPERVISION
// ─────────────────────────────────────────────
static void superviseMotor(uint32_t now) {
#if HAS_MOTOR_SENSE
  static uint32_t lastSample = 0, runSince = 0;
  static uint8_t overCount = 0;
  static bool wasOn = false;
  if ((uint32_t)(now - lastSample) < 20) return;
  lastSample = now;
  motorMa = measureMotorMa();

  const bool on = motor.energized() != atas::Dir::None;
  if (on && !wasOn) { runSince = now; overCount = 0; }
  wasOn = on;
  if (!on) return;

  overCount = motorMa > MOTOR_SHORT_MA ? (uint8_t)(overCount + 1) : 0;
  MotorFault f = MotorFault::None;
  if (overCount >= 3) f = MotorFault::Short;
  else if (MOTOR_OPEN_MA && (uint32_t)(now - runSince) > 400 && motorMa < MOTOR_OPEN_MA)
    f = MotorFault::Open;
  if (f != MotorFault::None) {
    motorFault = f;
    motor.stop(now);
    tuner.motorFault(now);
    Serial.printf("[MOTOR] fault: %s (%u mA)\n", faultName(f), motorMa);
  }
#else
  (void)now;
#endif
}

// ─────────────────────────────────────────────
//  STATUS LED
//   tuning: 8 Hz   ethernet: on   wifi: 1 Hz   no network: 4 Hz
//   motor fault: double blink
// ─────────────────────────────────────────────
static void ledUpdate(uint32_t now) {
  bool on;
  if (motorFault != MotorFault::None) { uint32_t p = now % 1000; on = p < 100 || (p > 200 && p < 300); }
  else if (tuner.active())             on = (now / 62) & 1;
  else if (link == Link::Eth)          on = true;
  else if (link == Link::Wifi)         on = (now / 500) & 1;
  else                                 on = (now / 125) & 1;
  digitalWrite(PIN_LED, on ? HIGH : LOW);
}

// ─────────────────────────────────────────────
//  FRONT PANEL — UP / DOWN / TUNE buttons, SWR LEDs
// ─────────────────────────────────────────────
static void panelUpdate(uint32_t now) {
  static uint32_t lastPoll = 0;
  if ((uint32_t)(now - lastPoll) < 5) return;
  lastPoll = now;

  // A move started from the panel that ended by itself (run-time limit,
  // motor fault) is forgotten, so the release does not stop anything else.
  if (panel.moving() != atas::Dir::None && !motor.busy()) panel.moveEnded();

  const atas::PanelAction a = panel.update(digitalRead(PIN_BTN_UP) == LOW,
                                           digitalRead(PIN_BTN_DOWN) == LOW,
                                           digitalRead(PIN_BTN_TUNE) == LOW, now);
  switch (a) {
    case atas::PanelAction::MoveUp:
    case atas::PanelAction::MoveDown: {
      const atas::Dir d = a == atas::PanelAction::MoveUp ? atas::Dir::Up : atas::Dir::Down;
      if (startManual(d, 0, now)) {                   // 0 = while held, max MOTOR_MAX_RUN_MS
        panel.moveEnded();
        swrLeds.flash(atas::LED_ORANGE | atas::LED_RED, 3, now);
      }
      break;
    }
    case atas::PanelAction::Stop:
      tuner.abort(now);
      motor.stop(now);
      break;
    case atas::PanelAction::Tune:
      if (tuner.active()) {
        tuner.abort(now);
      } else {
        const char* err = startTune(TUNE_TARGET_SWR, atas::Dir::Up, now);
        if (err) swrLeds.flash(strcmp(err, "no_rf") == 0 ? atas::LED_RED : atas::LED_ORANGE | atas::LED_RED, 3, now);
      }
      break;
    default:
      break;
  }
}

static void swrLedUpdate(uint32_t now) {
  // Autotune finished: show the result.
  static bool wasTuning = false;
  const bool tuning = tuner.active();
  if (wasTuning && !tuning) {
    switch (tuner.result()) {
      case atas::TuneResult::Ok:         swrLeds.flash(atas::LED_GREEN, 3, now); break;
      case atas::TuneResult::BestEffort: swrLeds.flash(atas::LED_ORANGE, 3, now); break;
      case atas::TuneResult::Aborted:    break;
      default:                           swrLeds.flash(atas::LED_RED, 3, now); break;
    }
  }
  wasTuning = tuning;

  const uint8_t m = swrLeds.update(lastRf, now);
  digitalWrite(PIN_SWR_G, (m & atas::LED_GREEN) ? HIGH : LOW);
  digitalWrite(PIN_SWR_O, (m & atas::LED_ORANGE) ? HIGH : LOW);
  digitalWrite(PIN_SWR_R, (m & atas::LED_RED) ? HIGH : LOW);
}

// ─────────────────────────────────────────────
//  SETUP / LOOP
// ─────────────────────────────────────────────
void setup() {
  // Relays off before anything else (hardware pull-downs hold them off
  // during reset as well).
  digitalWrite(PIN_K1_12V, LOW);
  digitalWrite(PIN_K2_8V, LOW);
  pinMode(PIN_K1_12V, OUTPUT);
  pinMode(PIN_K2_8V, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  for (int p : {PIN_SWR_G, PIN_SWR_O, PIN_SWR_R}) { digitalWrite(p, LOW); pinMode(p, OUTPUT); }
  for (int p : {PIN_BTN_UP, PIN_BTN_DOWN, PIN_BTN_TUNE}) pinMode(p, INPUT_PULLUP);   // 10k on the board too

  Serial.begin(115200);
  Serial.printf("\n[BoltATAS] v%s boot\n", FW_VERSION);

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_ADC_FWD, ADC_11db);     // 0.15 .. 2.45 V linear
  analogSetPinAttenuation(PIN_ADC_REF, ADC_11db);
  analogSetPinAttenuation(PIN_ADC_IMOT, ADC_11db);

  loadCal();
  motor.begin(millis());
  swrLeds.flash(atas::LED_GREEN | atas::LED_ORANGE | atas::LED_RED, 1, millis());   // lamp test

#if ESP_ARDUINO_VERSION_MAJOR >= 3
  Network.onEvent(onNetEvent);
  ETH.begin(ETH_PHY_LAN8720, WT32_PHY_ADDR, WT32_PHY_MDC, WT32_PHY_MDIO, WT32_PHY_POWER, ETH_CLOCK_GPIO0_IN);
#else
  WiFi.onEvent(onNetEvent);
  ETH.begin(WT32_PHY_ADDR, WT32_PHY_POWER, WT32_PHY_MDC, WT32_PHY_MDIO, ETH_PHY_LAN8720, ETH_CLOCK_GPIO0_IN);
#endif
  WiFi.mode(WIFI_OFF);                                // until we know there is no cable

  server.on("/status", HTTP_GET, handleStatus);
  server.on("/up",     HTTP_GET, handleUp);
  server.on("/down",   HTTP_GET, handleDown);
  server.on("/stop",   HTTP_GET, handleStop);
  server.on("/tune",   HTTP_GET, handleTune);
  server.on("/cal",    HTTP_GET, handleCal);
  server.onNotFound(handleNotFound);
  server.begin();
}

void loop() {
  const uint32_t now = millis();

  netUpdate(now);
  server.handleClient();
  if (servicesStarted) ArduinoOTA.handle();

  panelUpdate(now);
  motor.update(now);
  superviseMotor(now);

  // RF: the tuner asks for readings at its own pace; otherwise refresh
  // the displayed value every 50 ms.
  static uint32_t lastRfAt = 0;
  if (tuner.active()) {
    if (tuner.wantsReading(now)) {
      lastRf = measureRf(tuner.state() == atas::TuneState::Sweep ? 16 : 64);
      lastRfAt = now;
      tuner.update(now, &lastRf);
    } else {
      tuner.update(now, nullptr);
    }
  } else if ((uint32_t)(now - lastRfAt) >= 50) {
    lastRf = measureRf(32);
    lastRfAt = now;
    // Manual move and the power went up: stop before the whip arcs.
    if (motor.energized() != atas::Dir::None && lastRf.valid && lastRf.fwd_w > MANUAL_MAX_FWD_W) {
      motor.stop(now);
      swrLeds.flash(atas::LED_ORANGE | atas::LED_RED, 3, now);
    }
  }

  swrLedUpdate(now);
  ledUpdate(now);
  delay(1);
}
