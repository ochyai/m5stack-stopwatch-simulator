#pragma once

#include "sim_runtime.hpp"

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

inline uint32_t millis() { return sokkon_sim::millis32(); }

inline void delay(uint32_t milliseconds) {
  sokkon_sim::advanceMs(milliseconds);
}

class HardwareSerial {
 public:
  int available() const {
    return static_cast<int>(sokkon_sim::runtime().serial_rx.size());
  }

  int read() {
    auto& queue = sokkon_sim::runtime().serial_rx;
    if (queue.empty()) return -1;
    const unsigned char value = static_cast<unsigned char>(queue.front());
    queue.pop_front();
    return value;
  }

  size_t write(const uint8_t* data, size_t size) {
    sokkon_sim::serialWrite(reinterpret_cast<const char*>(data), size);
    return size;
  }

  size_t write(const char* data) {
    if (data == nullptr) return 0;
    const size_t size = std::strlen(data);
    sokkon_sim::serialWrite(data, size);
    return size;
  }

  size_t print(const char* value) { return write(value == nullptr ? "" : value); }

  size_t println(const char* value = "") {
    const size_t size = print(value);
    sokkon_sim::serialWrite("\n", 1);
    return size + 1;
  }

  int printf(const char* format, ...) {
    va_list arguments;
    va_start(arguments, format);
    va_list copied;
    va_copy(copied, arguments);
    const int required = std::vsnprintf(nullptr, 0, format, copied);
    va_end(copied);
    if (required < 0) {
      va_end(arguments);
      return required;
    }
    std::vector<char> buffer(static_cast<size_t>(required) + 1U);
    std::vsnprintf(buffer.data(), buffer.size(), format, arguments);
    va_end(arguments);
    sokkon_sim::serialWrite(buffer.data(), static_cast<size_t>(required));
    return required;
  }
};

inline HardwareSerial Serial;
