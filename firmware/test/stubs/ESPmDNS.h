#pragma once
#include "Arduino.h"
struct MDNSResponder { bool begin(const char*); bool addService(const char*, const char*, uint16_t); };
extern MDNSResponder MDNS;
