#pragma once
typedef enum {
  ARDUINO_EVENT_ETH_START, ARDUINO_EVENT_ETH_STOP, ARDUINO_EVENT_ETH_CONNECTED,
  ARDUINO_EVENT_ETH_DISCONNECTED, ARDUINO_EVENT_ETH_GOT_IP, ARDUINO_EVENT_ETH_LOST_IP,
  ARDUINO_EVENT_WIFI_STA_GOT_IP, ARDUINO_EVENT_MAX
} arduino_event_id_t;
typedef void (*NetworkEventCb)(arduino_event_id_t event);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
struct NetworkManager { int onEvent(NetworkEventCb cb, arduino_event_id_t e = ARDUINO_EVENT_MAX); };
extern NetworkManager Network;
#endif
