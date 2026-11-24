#pragma once
#include "Arduino.h"
class ArduinoOTAClass {
 public:
  typedef std::function<void(void)> THandlerFunction;
  ArduinoOTAClass& setHostname(const char*);
  ArduinoOTAClass& setPassword(const char*);
  ArduinoOTAClass& onStart(THandlerFunction fn);
  void begin();
  void handle();
};
extern ArduinoOTAClass ArduinoOTA;
