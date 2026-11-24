// AtasCore.h — platform-independent logic for BoltATAS
//
// Contains no Arduino/ESP32 calls, so it can be unit-tested on a PC
// (see firmware/test/sim_test.cpp). All timing is done with a millisecond
// timestamp passed in by the caller; nothing in here blocks.
//
//   RfConfig / computeRf()  AD8307 mV  ->  dBm, W, return loss, SWR
//   Motor                   relay sequencing: break-before-make, run time
//                           limit, position estimate
//   Tuner                   non-blocking autotune state machine
//
// Direction convention (ATAS-100):
//   Dir::Up   = K2 = 8 V on coax  = whip shorter = resonance UP in frequency
//   Dir::Down = K1 = 12 V on coax = whip longer  = resonance DOWN in frequency
#pragma once
#include <math.h>
#include <stdint.h>

namespace atas {

// ─────────────────────────────────────────────────────────────
//  RF measurement
// ─────────────────────────────────────────────────────────────
struct RfConfig {
  float slope_mv_per_db = 25.0f;   // AD8307, output unloaded (internal 12.5 kΩ)
  float intercept_dbm   = -84.0f;  // AD8307 typical
  // Line power = detector power + coupling.
  // Tandem match 1:30 = 29.5 dB, plus 13 dB pi-pad = 42.5 dB.
  float fwd_coupling_db = 42.5f;
  float ref_coupling_db = 42.5f;
  float min_fwd_w       = 0.5f;    // below this, SWR is not meaningful
};

struct RfReading {
  bool  valid;      // fwd_w >= min_fwd_w
  float fwd_dbm;
  float ref_dbm;
  float fwd_w;
  float ref_w;
  float rl_db;      // return loss, positive = good
  float swr;
};

inline float dbmToW(float dbm) { return powf(10.0f, (dbm - 30.0f) / 10.0f); }
inline float wToDbm(float w) { return 10.0f * log10f(w > 1e-9f ? w : 1e-9f) + 30.0f; }

inline float detMvToDbm(float mv, const RfConfig& c) {
  return mv / c.slope_mv_per_db + c.intercept_dbm;
}

inline float swrFromRl(float rl_db) {
  if (rl_db < 0.0f) rl_db = 0.0f;
  float rho = powf(10.0f, -rl_db / 20.0f);
  if (rho > 0.98f) rho = 0.98f;   // caps SWR at 99
  return (1.0f + rho) / (1.0f - rho);
}

inline RfReading computeRf(float fwd_mv, float ref_mv, const RfConfig& c) {
  RfReading r{};
  r.fwd_dbm = detMvToDbm(fwd_mv, c) + c.fwd_coupling_db;
  r.ref_dbm = detMvToDbm(ref_mv, c) + c.ref_coupling_db;
  r.fwd_w   = dbmToW(r.fwd_dbm);
  r.ref_w   = dbmToW(r.ref_dbm);
  r.rl_db   = r.fwd_dbm - r.ref_dbm;
  r.swr     = swrFromRl(r.rl_db);
  r.valid   = r.fwd_w >= c.min_fwd_w;
  return r;
}

// ─────────────────────────────────────────────────────────────
//  Motor / relay sequencing
// ─────────────────────────────────────────────────────────────
enum class Dir : int8_t { None = 0, Up = 1, Down = -1 };

class Motor {
 public:
  // k1_12v = antenna longer (Down), k2_8v = antenna shorter (Up).
  // Never called with both true.
  typedef void (*RelayFn)(bool k1_12v, bool k2_8v);

  static const uint32_t DEADTIME_MS = 30;    // relay release time + margin

  Motor(RelayFn fn, uint32_t maxRunMs) : relays_(fn), maxRun_(maxRunMs) {}

  void begin(uint32_t now) {
    st_ = St::Off;
    cur_ = pend_ = Dir::None;
    offAt_ = now - DEADTIME_MS;
    apply(Dir::None);
  }

  // Run in direction d for ms milliseconds. ms == 0 means "until stop()",
  // always limited to maxRunMs. Calling again in the same direction
  // restarts the timer; the opposite direction goes through dead time.
  void run(Dir d, uint32_t ms, uint32_t now) {
    if (d == Dir::None) { stop(now); return; }
    if (ms == 0 || ms > maxRun_) ms = maxRun_;
    if (st_ == St::Run && cur_ == d) {
      accumulate(now);
      start_ = now;
      runFor_ = ms;
      return;
    }
    if (st_ == St::Run) deenergize(now);
    pend_ = d;
    pendMs_ = ms;
    st_ = St::Dead;
    update(now);
  }

  void stop(uint32_t now) {
    if (st_ == St::Run) deenergize(now);
    st_ = St::Off;
    pend_ = Dir::None;
  }

  void update(uint32_t now) {
    if (st_ == St::Dead && (uint32_t)(now - offAt_) >= DEADTIME_MS) {
      cur_ = pend_;
      pend_ = Dir::None;
      start_ = now;
      lastAcc_ = now;
      runFor_ = pendMs_;
      st_ = St::Run;
      apply(cur_);
    }
    if (st_ == St::Run && (uint32_t)(now - start_) >= runFor_) {
      deenergize(now);
      st_ = St::Off;
    }
  }

  bool busy() const { return st_ != St::Off; }
  Dir energized() const { return st_ == St::Run ? cur_ : Dir::None; }
  uint32_t totalRunMs() const { return total_; }
  void resetTotal() { total_ = 0; }
  int32_t positionMs(uint32_t now) const {   // +Up / -Down, relative estimate
    if (st_ != St::Run) return pos_;
    return pos_ + (int32_t)cur_ * (int32_t)(now - lastAcc_);
  }

 private:
  enum class St { Off, Dead, Run };

  void apply(Dir d) {
    if (relays_) relays_(d == Dir::Down, d == Dir::Up);
  }
  void accumulate(uint32_t now) {
    uint32_t dt = now - lastAcc_;
    pos_ += (int32_t)cur_ * (int32_t)dt;
    total_ += dt;
    lastAcc_ = now;
  }
  void deenergize(uint32_t now) {
    accumulate(now);
    apply(Dir::None);
    cur_ = Dir::None;
    offAt_ = now;
  }

  RelayFn relays_;
  uint32_t maxRun_;
  St st_ = St::Off;
  Dir cur_ = Dir::None, pend_ = Dir::None;
  uint32_t pendMs_ = 0, start_ = 0, runFor_ = 0, offAt_ = 0, lastAcc_ = 0;
  uint32_t total_ = 0;
  int32_t pos_ = 0;
};

// ─────────────────────────────────────────────────────────────
//  Autotune
//
//  Works on return loss (log domain), which still has a usable slope at
//  high SWR where the SWR curve itself looks flat.
//
//  Phase 1 SWEEP: motor runs continuously (kept alive per reading, so it
//    stops by itself if the loop ever hangs) while the RF is sampled every
//    sample_ms. Ends when the dip has been passed, when SWR <= target, or
//    reverses at the end stop / when clearly moving away from a dip.
//  Phase 2 FINE: stepped search around the dip with settle time, step
//    halving on every reversal, then return to the best position seen.
//
//  Aborts on loss of RF, too much power, motor fault, total motor time.
// ─────────────────────────────────────────────────────────────
struct TuneConfig {
  float    target_swr     = 1.5f;
  float    accept_swr     = 2.0f;   // best-effort result at or below this
  float    min_fwd_w      = 0.5f;
  float    max_fwd_w      = 25.0f;  // never move the whip under high power
  uint32_t sample_ms      = 40;     // RF sample interval while sweeping
  uint32_t keepalive_ms   = 400;    // sweep motor stops if not re-armed
  uint32_t step_ms        = 160;    // first fine step
  uint32_t step_ms_min    = 30;
  uint32_t settle_ms      = 150;    // after a fine step, before measuring
  uint32_t full_travel_ms = 45000;  // end-to-end run time of the whip (measure!)
  uint32_t max_motor_ms   = 120000;
  uint16_t max_steps      = 200;    // fine steps
  uint8_t  stall_steps    = 12;     // fine steps without a new best -> stop
  float    hyst_db        = 0.15f;  // fine phase: change treated as noise
  float    pass_db        = 0.50f;  // sweep: drop below best that means "dip passed"
  float    away_db        = 1.20f;  // sweep, no dip yet: drop that means "wrong way"
  float    bracket_swr    = 4.0f;   // a dip must get below this to count
  float    dip_db         = 2.0f;   // ...and be this much deeper than the worst seen
};

enum class TuneState : uint8_t { Idle, Sweep, Fine, Done, Failed };
enum class TuneResult : uint8_t {
  None, Ok, BestEffort, NoRf, PowerTooHigh, Timeout, Aborted, MotorFault, NotReached
};

inline const char* tuneResultName(TuneResult r) {
  switch (r) {
    case TuneResult::None:         return "none";
    case TuneResult::Ok:           return "ok";
    case TuneResult::BestEffort:   return "best_effort";
    case TuneResult::NoRf:         return "no_rf";
    case TuneResult::PowerTooHigh: return "power_too_high";
    case TuneResult::Timeout:      return "timeout";
    case TuneResult::Aborted:      return "aborted";
    case TuneResult::MotorFault:   return "motor_fault";
    case TuneResult::NotReached:   return "not_reached";
  }
  return "?";
}

inline const char* tuneStateName(TuneState s) {
  switch (s) {
    case TuneState::Idle:   return "idle";
    case TuneState::Sweep:  return "sweep";
    case TuneState::Fine:   return "fine";
    case TuneState::Done:   return "done";
    case TuneState::Failed: return "failed";
  }
  return "?";
}

class Tuner {
 public:
  explicit Tuner(Motor& m) : m_(m) {}

  TuneConfig cfg;

  // firstDir: hint from the client (frequency went up -> Dir::Up).
  void start(uint32_t now, Dir firstDir = Dir::Up) {
    m_.stop(now);
    m_.resetTotal();
    st_ = TuneState::Sweep;
    sub_ = Sub::SweepRun;
    res_ = TuneResult::None;
    dir_ = (firstDir == Dir::Down) ? Dir::Down : Dir::Up;
    lastSample_ = now - cfg.sample_ms;
    steps_ = 0;
    sweepRev_ = 0;
    revAtMin_ = 0;
    sinceBest_ = 0;
    fine_ = cfg.step_ms;
    firstFine_ = true;
    bestRl_ = bestRlDir_ = -1.0f;
    minRl_ = 99.0f;
    nBuf_ = 0;
    bestSwr_ = 99.0f;
    lastSwr_ = 99.0f;
    bestPos_ = posAtRev_ = m_.positionMs(now);
  }

  void abort(uint32_t now) { if (active()) finish(now, TuneState::Failed, TuneResult::Aborted); }
  void motorFault(uint32_t now) { if (active()) finish(now, TuneState::Failed, TuneResult::MotorFault); }
  bool active() const { return st_ == TuneState::Sweep || st_ == TuneState::Fine; }

  // True when update() should be given a fresh RF reading this loop.
  bool wantsReading(uint32_t now) const {
    if (sub_ == Sub::SweepRun) return (uint32_t)(now - lastSample_) >= cfg.sample_ms;
    if (sub_ == Sub::Settle) return !m_.busy() && (int32_t)(now - settleUntil_) >= 0;
    return false;
  }

  // Call every loop; r = fresh reading when wantsReading() was true, else nullptr.
  void update(uint32_t now, const RfReading* r) {
    if (!active()) return;
    if (sub_ == Sub::StepMove) {                 // waiting for a fine step to finish
      if (!m_.busy()) { sub_ = Sub::Settle; settleUntil_ = now + cfg.settle_ms; }
      return;
    }
    if (r == nullptr || !wantsReading(now)) return;

    if (!r->valid || r->fwd_w < cfg.min_fwd_w) { finish(now, TuneState::Failed, TuneResult::NoRf); return; }
    if (r->fwd_w > cfg.max_fwd_w) { finish(now, TuneState::Failed, TuneResult::PowerTooHigh); return; }
    if (m_.totalRunMs() >= cfg.max_motor_ms) { finish(now, TuneState::Failed, TuneResult::Timeout); return; }

    lastSwr_ = r->swr;
    const int32_t posNow = m_.positionMs(now);
    float rl = r->rl_db;
    int32_t pos = posNow;
    if (sub_ == Sub::SweepRun) {
      // 3-sample moving average while sweeping; position of the middle sample
      rlBuf_[nBuf_ % 3] = rl;
      posBuf_[nBuf_ % 3] = posNow;
      nBuf_++;
      if (r->swr <= cfg.target_swr) { lastSample_ = now; stopAndSettle(now, After::Verify); return; }
      if (nBuf_ < 3) { lastSample_ = now; m_.run(dir_, cfg.keepalive_ms, now); return; }
      rl = (rlBuf_[0] + rlBuf_[1] + rlBuf_[2]) / 3.0f;
      pos = posBuf_[(nBuf_ - 2) % 3];
    }
    const float swr = swrFromRl(rl);
    const bool newBest = rl > bestRl_ + (st_ == TuneState::Fine ? cfg.hyst_db * 0.5f : 0.0f);
    if (rl > bestRl_) { bestRl_ = rl; bestSwr_ = swr; bestPos_ = pos; }
    if (rl < minRl_) minRl_ = rl;

    if (sub_ == Sub::SweepRun) { sweepSample(now, swr, rl, posNow); return; }
    settled(now, r->swr, rl, posNow, newBest);
  }

  // Optional: end stop detected another way (motor current).
  void endStop(uint32_t now) {
    if (sub_ == Sub::SweepRun) { reverseSweep(now, m_.positionMs(now), bestRlDir_); }
  }

  TuneState state() const { return st_; }
  TuneResult result() const { return res_; }
  uint16_t steps() const { return steps_; }
  float bestSwr() const { return bestSwr_; }
  float lastSwr() const { return lastSwr_; }

 private:
  enum class Sub : uint8_t { None, SweepRun, StepMove, Settle };
  enum class After : uint8_t { Fine, Verify, Return };

  static Dir flip(Dir d) { return d == Dir::Up ? Dir::Down : Dir::Up; }
  static int32_t iabs(int32_t v) { return v < 0 ? -v : v; }

  void sweepSample(uint32_t now, float swr, float rl, int32_t pos) {
    lastSample_ = now;
    (void)swr;
    // A real dip: below bracket_swr AND clearly deeper than the worst seen
    // (with lossy coax the far-off SWR can itself be only 4..5).
    const bool nearDip = bestSwr_ <= cfg.bracket_swr && bestRl_ - minRl_ >= cfg.dip_db;
    if (nearDip && rl < bestRl_ - cfg.pass_db) {  // went through the dip
      dir_ = flip(dir_);
      fine_ = cfg.step_ms;
      stopAndSettle(now, After::Fine);
      return;
    }
    if (rl > bestRlDir_) bestRlDir_ = rl;
    if (!nearDip && rl < bestRlDir_ - cfg.away_db) reverseSweep(now, pos, rl);   // wrong way
    else if ((uint32_t)iabs(pos - posAtRev_) >= cfg.full_travel_ms) reverseSweep(now, pos, rl);  // end stop
    if (sweepRev_ >= 3) { goBest(now, pos); return; }   // swept everything, no dip
    m_.run(dir_, cfg.keepalive_ms, now);       // (re)arm: stops by itself if not renewed
  }

  void reverseSweep(uint32_t now, int32_t pos, float rl) {
    (void)now;
    dir_ = flip(dir_);
    posAtRev_ = pos;
    bestRlDir_ = rl;
    sweepRev_++;
  }

  void stopAndSettle(uint32_t now, After next) {
    m_.stop(now);
    st_ = TuneState::Fine;
    sub_ = Sub::Settle;
    after_ = next;
    settleUntil_ = now + cfg.settle_ms;
    firstFine_ = true;
    sinceBest_ = 0;
    nBuf_ = 0;
  }

  void settled(uint32_t now, float swr, float rl, int32_t pos, bool newBest) {
    if (after_ == After::Return) {
      finish(now, TuneState::Done,
             swr <= cfg.target_swr ? TuneResult::Ok
             : (bestSwr_ <= cfg.accept_swr ? TuneResult::BestEffort : TuneResult::NotReached));
      return;
    }
    if (swr <= cfg.target_swr) { finish(now, TuneState::Done, TuneResult::Ok); return; }
    if (after_ == After::Verify) {              // coasted out of band: search back slowly
      after_ = After::Fine;
      dir_ = flip(dir_);
      fine_ = cfg.step_ms / 2;
    }
    if (steps_ >= cfg.max_steps) { goBest(now, pos); return; }

    if (firstFine_) {
      firstFine_ = false;
    } else {
      sinceBest_ = newBest ? 0 : (uint8_t)(sinceBest_ + 1);
      const bool worse = rl < prevRl_ - cfg.hyst_db * 0.5f;
      if (worse && rl < bestRl_ - cfg.hyst_db) {   // past the minimum
        if (fine_ > cfg.step_ms_min) fine_ /= 2;
        if (fine_ <= cfg.step_ms_min) { fine_ = cfg.step_ms_min; revAtMin_++; }
        dir_ = flip(dir_);
      }
      if (revAtMin_ >= 2 || sinceBest_ >= cfg.stall_steps) { goBest(now, pos); return; }
    }
    prevRl_ = rl;
    step(now, dir_, fine_);
  }

  void goBest(uint32_t now, int32_t pos) {
    const int32_t delta = bestPos_ - pos;
    if (iabs(delta) < (int32_t)cfg.step_ms_min / 2) {
      finish(now, TuneState::Done,
             bestSwr_ <= cfg.target_swr ? TuneResult::Ok
             : (bestSwr_ <= cfg.accept_swr ? TuneResult::BestEffort : TuneResult::NotReached));
      return;
    }
    m_.stop(now);
    st_ = TuneState::Fine;
    after_ = After::Return;
    step(now, delta > 0 ? Dir::Up : Dir::Down, (uint32_t)iabs(delta));
  }

  void step(uint32_t now, Dir d, uint32_t ms) {
    steps_++;
    m_.run(d, ms, now);
    sub_ = Sub::StepMove;
  }

  void finish(uint32_t now, TuneState s, TuneResult r) {
    m_.stop(now);
    st_ = s;
    sub_ = Sub::None;
    res_ = r;
  }

  Motor& m_;
  TuneState st_ = TuneState::Idle;
  Sub sub_ = Sub::None;
  After after_ = After::Fine;
  TuneResult res_ = TuneResult::None;
  Dir dir_ = Dir::Up;
  uint32_t lastSample_ = 0, settleUntil_ = 0, fine_ = 160;
  uint16_t steps_ = 0;
  uint8_t sweepRev_ = 0, revAtMin_ = 0, sinceBest_ = 0;
  bool firstFine_ = true;
  float prevRl_ = 0.0f, bestRl_ = -1.0f, bestRlDir_ = -1.0f, bestSwr_ = 99.0f, lastSwr_ = 99.0f;
  int32_t bestPos_ = 0, posAtRev_ = 0;
  float minRl_ = 99.0f;
  float rlBuf_[3] = {0, 0, 0};
  int32_t posBuf_[3] = {0, 0, 0};
  uint8_t nBuf_ = 0;
};

}  // namespace atas
