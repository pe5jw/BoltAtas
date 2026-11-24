#pragma once
#include "Arduino.h"
class Preferences {
 public:
  bool begin(const char* name, bool readOnly = false, const char* partition_label = NULL);
  void end();
  size_t putUInt(const char* key, uint32_t value);
  size_t putFloat(const char* key, float value);
  uint32_t getUInt(const char* key, uint32_t defaultValue = 0);
  float getFloat(const char* key, float defaultValue = NAN);
};
