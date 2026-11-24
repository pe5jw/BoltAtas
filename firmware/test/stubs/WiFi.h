#pragma once
#include "Arduino.h"
#include "NetworkStub.h"
typedef enum { WIFI_OFF, WIFI_STA } wifi_mode_t;
typedef enum { WL_IDLE_STATUS, WL_CONNECTED } wl_status_t;
class WiFiClass {
 public:
  static bool mode(wifi_mode_t);
  static bool setHostname(const char*);
  int begin(const char* ssid, const char* pass);
  bool disconnect(bool wifioff = false, bool eraseap = false, unsigned long timeoutLength = 100);
  bool setAutoReconnect(bool);
  wl_status_t status();
  IPAddress localIP();
  String macAddress();
  int8_t RSSI();
#if ESP_ARDUINO_VERSION_MAJOR < 3
  int onEvent(NetworkEventCb cb, arduino_event_id_t e = ARDUINO_EVENT_MAX);
#endif
};
extern WiFiClass WiFi;
