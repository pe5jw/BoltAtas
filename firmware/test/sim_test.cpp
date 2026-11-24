// Host-side tests for AtasCore.h
//   g++ -std=c++17 -O2 -Wall -Wextra -I../BoltATAS sim_test.cpp -o sim_test && ./sim_test
//
// 1. RF math against hand-calculated values
// 2. Motor: interlock, dead time, timed runs, run-time limit
// 3. Autotune against a simulated ATAS-100 (random resonance, start
//    position, feed-point resistance, coax loss, motor coast, detector noise)
#include <cassert>
#include <cmath>
#include <complex>
#include <cstdio>
#include <random>
#include <vector>

#include "AtasCore.h"

using namespace atas;

static int failures = 0;
#define CHECK(c, ...) do { if (!(c)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

// ── relay recorder ──────────────────────────────────────────
struct RelayLog { uint32_t t; bool k1, k2; };
static std::vector<RelayLog> g_log;
static uint32_t g_now = 0;
static bool g_k1 = false, g_k2 = false;
static void relays(bool k1, bool k2) {
  g_k1 = k1; g_k2 = k2;
  g_log.push_back({g_now, k1, k2});
}

static void checkRelayLog(const char* tag) {
  uint32_t lastOff = 0;
  bool wasOn = false, hadOff = false;
  for (auto& e : g_log) {
    CHECK(!(e.k1 && e.k2), "%s: both relays on at t=%u", tag, e.t);
    bool on = e.k1 || e.k2;
    if (on && !wasOn && hadOff)
      CHECK(e.t - lastOff >= Motor::DEADTIME_MS, "%s: dead time violated at t=%u (off at %u)", tag, e.t, lastOff);
    if (!on && wasOn) { lastOff = e.t; hadOff = true; }
    wasOn = on;
  }
}

// ── 1. RF math ──────────────────────────────────────────────
static void testRf() {
  RfConfig c;
  // 100 W = 50 dBm on the line -> detector 7.5 dBm -> 25*(7.5+84) = 2287.5 mV
  float mvF = 25.0f * (50.0f - 42.5f + 84.0f);
  // SWR 2.0 -> |rho| = 1/3 -> RL = 9.54 dB -> ref = 40.46 dBm
  float mvR = 25.0f * (50.0f - 9.5424f - 42.5f + 84.0f);
  RfReading r = computeRf(mvF, mvR, c);
  CHECK(fabsf(r.fwd_w - 100.0f) < 0.5f, "fwd_w=%f", r.fwd_w);
  CHECK(fabsf(r.swr - 2.0f) < 0.01f, "swr=%f", r.swr);
  CHECK(fabsf(r.ref_w - 11.11f) < 0.1f, "ref_w=%f", r.ref_w);
  CHECK(r.valid, "valid");
  // 120 W must stay below 2.45 V (ESP32 ADC upper limit at 11 dB attenuation)
  float mv120 = 25.0f * (wToDbm(120.0f) - 42.5f + 84.0f);
  CHECK(mv120 < 2450.0f, "120 W gives %f mV", mv120);
  float mv200 = 25.0f * (wToDbm(200.0f) - 42.5f + 84.0f);
  CHECK(mv200 < 2450.0f, "200 W gives %f mV", mv200);
  // detector input at 200 W must be below AD8307 linear limit (+16 dBm)
  CHECK(wToDbm(200.0f) - 42.5f < 16.0f, "detector overdriven at 200 W");
  // no RF
  RfReading n = computeRf(250.0f, 250.0f, c);
  CHECK(!n.valid, "no-RF reading flagged valid (fwd_w=%f)", n.fwd_w);
  printf("RF math: 120 W -> %.0f mV, 200 W -> %.0f mV at the ADC\n", mv120, mv200);
}

// ── 2. Motor ────────────────────────────────────────────────
static void testMotor() {
  g_log.clear(); g_now = 1000;
  Motor m(relays, 15000);
  m.begin(g_now);
  m.run(Dir::Up, 200, g_now);
  CHECK(g_k2 && !g_k1, "up should energize K2 only");
  for (int i = 0; i < 199; i++) { g_now++; m.update(g_now); }
  CHECK(g_k2, "still running at 199 ms");
  g_now++; m.update(g_now);
  CHECK(!g_k1 && !g_k2, "stopped after 200 ms");
  // immediate reversal must wait dead time
  m.run(Dir::Down, 100, g_now);
  CHECK(!g_k1, "K1 must not close inside dead time");
  for (uint32_t i = 0; i < Motor::DEADTIME_MS; i++) { g_now++; m.update(g_now); }
  CHECK(g_k1 && !g_k2, "K1 after dead time");
  // reverse while running
  g_now += 10; m.update(g_now);
  m.run(Dir::Up, 0, g_now);
  CHECK(!g_k1 && !g_k2, "both off during direction change");
  for (uint32_t i = 0; i < Motor::DEADTIME_MS; i++) { g_now++; m.update(g_now); }
  CHECK(g_k2, "K2 after reversal dead time");
  // continuous run limited to max run time
  uint32_t t0 = g_now;
  while (m.busy() && g_now - t0 < 20000) { g_now++; m.update(g_now); }
  CHECK(g_now - t0 >= 14999 && g_now - t0 <= 15001, "max run limit: ran %u ms", g_now - t0);
  // stop works at any time
  m.run(Dir::Down, 0, g_now);
  for (int i = 0; i < 100; i++) { g_now++; m.update(g_now); }
  m.stop(g_now);
  CHECK(!g_k1 && !g_k2 && !m.busy(), "stop()");
  checkRelayLog("motor");
}

// ── 3. Antenna simulation ───────────────────────────────────
struct SimAntenna {
  double pos, travel, p0, R, k, lossDb, speedUp, speedDown, coast;
  double reflAt(double p) const {
    std::complex<double> z(R, k * (p - p0));
    double g = std::abs((z - 50.0) / (z + 50.0));
    return g * pow(10.0, -2.0 * lossDb / 20.0);      // seen through the coax
  }
  double bestSwr() const {
    double g = reflAt(p0);
    return (1 + g) / (1 - g);
  }
};

static double g_noise = 1.2, g_travel = 40000;
static bool g_hint = false;

struct TrialResult { TuneResult res; float swr, best; uint32_t ms; uint16_t steps; };

static TrialResult runTrial(std::mt19937& rng, bool verbose) {
  std::uniform_real_distribution<double> U(0, 1);
  SimAntenna a;
  a.travel = g_travel;
  a.p0 = 0.05 * g_travel + U(rng) * 0.9 * g_travel;
  a.pos = U(rng) * a.travel;
  a.R = 30 + U(rng) * 30;            // 30..60 ohm at resonance
  a.k = 0.06 + U(rng) * 0.10;        // ohm per ms of travel
  a.lossDb = 0.3 + U(rng) * 1.5;     // coax loss one way
  a.speedUp = 0.9 + U(rng) * 0.2;
  a.speedDown = 0.9 + U(rng) * 0.2;
  a.coast = 3 + U(rng) * 10;
  const double txW = 5 + U(rng) * 15;
  std::normal_distribution<double> noise(0.0, 1.0);

  RfConfig rc;
  g_log.clear(); g_now = 5000; g_k1 = g_k2 = false;
  Motor m(relays, 15000);
  m.begin(g_now);
  Tuner t(m);
  t.start(g_now, g_hint ? (a.p0 > a.pos ? Dir::Up : Dir::Down) : Dir::Up);
  bool wasOn = false; int lastDir = 0;

  while (t.active() && g_now < 5000 + 300000) {
    g_now++;
    m.update(g_now);
    int d = g_k2 ? +1 : (g_k1 ? -1 : 0);
    if (d) {
      a.pos += d * (d > 0 ? a.speedUp : a.speedDown);
      lastDir = d;
    } else if (wasOn) {
      a.pos += lastDir * a.coast;    // coast after the relay opens
    }
    if (a.pos < 0) a.pos = 0;
    if (a.pos > a.travel) a.pos = a.travel;
    wasOn = d != 0;

    RfReading r{};
    const RfReading* rp = nullptr;
    if (t.wantsReading(g_now)) {
      double g = a.reflAt(a.pos);
      double fwdDbm = 10 * log10(txW) + 30;
      double refW = txW * g * g + txW * pow(10.0, -3.5);   // 35 dB directivity floor
      double refDbm = 10 * log10(refW) + 30;
      double mvF = 25.0 * (fwdDbm - rc.fwd_coupling_db - rc.intercept_dbm) + noise(rng) * g_noise;
      double mvR = 25.0 * (refDbm - rc.ref_coupling_db - rc.intercept_dbm) + noise(rng) * g_noise;
      r = computeRf((float)mvF, (float)mvR, rc);
      rp = &r;
    }
    t.update(g_now, rp);
  }
  double g = a.reflAt(a.pos);
  TrialResult tr{t.result(), (float)((1 + g) / (1 - g)), (float)a.bestSwr(), g_now - 5000, t.steps()};
  if (verbose)
    printf("  p0=%6.0f start=%6.0f R=%4.1f -> %-12s swr=%.2f (best possible %.2f) %5.1f s %3u steps\n",
           a.p0, 0.0, a.R, tuneResultName(tr.res), tr.swr, tr.best, tr.ms / 1000.0, tr.steps);
  checkRelayLog("tune");
  return tr;
}

static void testTuner(const char* name) {
  std::mt19937 rng(73);
  const int N = 3000;
  int ok = 0, okPossible = 0, missed = 0, fails = 0; int hist[16]={0};
  double tMax = 0, tSum = 0;
  for (int i = 0; i < N; i++) {
    TrialResult r = runTrial(rng, false);
    bool possible = r.best <= 1.45f;   // target 1.5 with a little margin
    if (possible) okPossible++;
    hist[(int)r.res]++;
    if (r.res == TuneResult::Ok) { ok++; CHECK(r.swr <= 1.6f, "Ok but swr %.2f", r.swr); }
    if (possible && r.res != TuneResult::Ok) missed++;
    if (r.res == TuneResult::Timeout || r.res == TuneResult::NoRf) fails++;
    if (!possible && r.res != TuneResult::Ok)
      CHECK(r.swr <= r.best * 1.25f + 0.1f, "best effort far from optimum: %.2f vs %.2f", r.swr, r.best);
    tMax = std::max(tMax, r.ms / 1000.0); tSum += r.ms / 1000.0;
  }
  printf("Tuner [%s]: %d trials, target reachable in %d, reached in %d, missed %d, timeouts %d, "
         "avg %.1f s, max %.1f s\n", name, N, okPossible, ok, missed, fails, tSum / N, tMax);
  for(int i=0;i<9;i++) if(hist[i]) printf("  %-14s %d\n", tuneResultName((TuneResult)i), hist[i]);
  CHECK(missed <= okPossible / 200, "too many misses: %d", missed);
  CHECK(fails == 0, "timeouts: %d", fails);
}

static void testTunerSafety() {
  RfConfig rc;
  g_log.clear(); g_now = 100;
  Motor m(relays, 15000);
  m.begin(g_now);
  Tuner t(m);
  // no RF
  t.start(g_now);
  RfReading none = computeRf(300, 300, rc);
  while (t.active()) { g_now++; m.update(g_now); t.update(g_now, t.wantsReading(g_now) ? &none : nullptr); }
  CHECK(t.result() == TuneResult::NoRf, "no RF -> %s", tuneResultName(t.result()));
  // too much power (100 W)
  t.start(g_now);
  float mv = 25.0f * (50.0f - 42.5f + 84.0f);
  RfReading hot = computeRf(mv, mv - 200, rc);
  while (t.active()) { g_now++; m.update(g_now); t.update(g_now, t.wantsReading(g_now) ? &hot : nullptr); }
  CHECK(t.result() == TuneResult::PowerTooHigh, "100 W -> %s", tuneResultName(t.result()));
  CHECK(!g_k1 && !g_k2, "relays must be off after refusing");
  // abort while moving
  RfReading bad = computeRf(25.0f * (40.0f - 42.5f + 84.0f), 25.0f * (39.0f - 42.5f + 84.0f), rc);
  t.start(g_now);
  for (int i = 0; i < 400; i++) { g_now++; m.update(g_now); t.update(g_now, t.wantsReading(g_now) ? &bad : nullptr); }
  CHECK(m.busy(), "should be moving");
  t.abort(g_now);
  CHECK(!g_k1 && !g_k2 && t.result() == TuneResult::Aborted, "abort");
  checkRelayLog("safety");
}

int main() {
  testRf();
  testMotor();
  testTunerSafety();
  testTuner("nominal noise, 40 s travel");
  g_noise = 3.0; g_travel = 30000;
  testTuner("2.5x noise, 30 s travel");
  g_noise = 1.2; g_travel = 40000; g_hint = true;
  testTuner("with direction hint");
  printf(failures ? "\n%d FAILURES\n" : "\nALL TESTS PASSED\n", failures);
  return failures ? 1 : 0;
}
