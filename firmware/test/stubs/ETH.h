#pragma once
#include "Arduino.h"
#include "NetworkStub.h"
typedef enum { ETH_PHY_LAN8720, ETH_PHY_TLK110 } eth_phy_type_t;
typedef enum { ETH_CLOCK_GPIO0_IN, ETH_CLOCK_GPIO0_OUT } eth_clock_mode_t;
class ETHClass {
 public:
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  bool begin(eth_phy_type_t type, int32_t phy_addr, int mdc, int mdio, int power, eth_clock_mode_t clk_mode);
#else
  bool begin(uint8_t phy_addr, int power, int mdc, int mdio, eth_phy_type_t type, eth_clock_mode_t clock_mode);
#endif
  bool setHostname(const char*);
  IPAddress localIP();
  String macAddress();
};
extern ETHClass ETH;
