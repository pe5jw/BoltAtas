// Minimal host stubs, only for syntax/type checking BoltATAS.ino on a PC.
// Signatures follow arduino-esp32 (2.x / 3.x).
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <string>
#include <functional>
#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 3
#endif
#define HIGH 1
#define LOW 0
#define INPUT 1
#define OUTPUT 3
#define INPUT_PULLUP 5
typedef float float_t_;
class String {
 public:
  String(const char* s = "") : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  String(float v, unsigned char d) { char b[32]; snprintf(b, sizeof b, "%.*f", d, v); s_ = b; }
  String(int v) : s_(std::to_string(v)) {}
  const char* c_str() const { return s_.c_str(); }
  size_t length() const { return s_.size(); }  // unsigned int == size_t on ESP32
  bool reserve(unsigned int n) { s_.reserve(n); return true; }
  bool concat(const char* c) { s_ += c; return true; }
  bool concat(const char* c, unsigned int n) { s_.append(c, n); return true; }
  bool concat(char c) { s_ += c; return true; }
  String& operator+=(const char* c) { s_ += c; return *this; }
  String& operator+=(char c) { s_ += c; return *this; }
  bool operator==(const char* c) const { return s_ == c; }
  long toInt() const { return atol(s_.c_str()); }
  float toFloat() const { return (float)atof(s_.c_str()); }
  char operator[](unsigned int i) const { return s_[i]; }
 private:
  std::string s_;
};
class StringSumHelper : public String { public: using String::String; };
class IPAddress { public: String toString() const { return String("0.0.0.0"); } };
struct HardwareSerial {
  void begin(unsigned long) {}
  void println(const char*) {}
  int printf(const char*, ...) { return 0; }
};
extern HardwareSerial Serial;
typedef enum { ADC_0db, ADC_2_5db, ADC_6db, ADC_11db } adc_attenuation_t;
void pinMode(uint8_t, uint8_t);
void digitalWrite(uint8_t, uint8_t);
int digitalRead(uint8_t);
int32_t analogReadMilliVolts(uint8_t pin);
void analogReadResolution(uint8_t bits);
void analogSetPinAttenuation(uint8_t pin, adc_attenuation_t a);
unsigned long millis();
void delay(uint32_t);
