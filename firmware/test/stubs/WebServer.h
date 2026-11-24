#pragma once
#include "Arduino.h"
typedef enum { HTTP_GET, HTTP_POST } HTTPMethod;
class WebServer {
 public:
  typedef std::function<void(void)> THandlerFunction;
  explicit WebServer(int port);
  void on(const char* uri, HTTPMethod m, THandlerFunction fn);
  void onNotFound(THandlerFunction fn);
  void begin();
  void handleClient();
  String arg(const String& name) const;
  bool hasArg(const String& name) const;
  void sendHeader(const String& name, const String& value, bool first = false);
  void send(int code, const char* content_type, const String& content);
};
