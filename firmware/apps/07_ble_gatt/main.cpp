#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <M5Unified.h>

#include <string.h>

#include "board.hpp"

namespace {

constexpr char kServiceUuid[] = "7e2c0001-4c5a-4b4f-9a28-5c1520000001";
constexpr char kValueUuid[] = "7e2c0002-4c5a-4b4f-9a28-5c1520000002";

BLECharacteristic* value_characteristic = nullptr;
volatile bool connected = false;
uint32_t counter = 0;

class ConnectionCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { connected = true; }
  void onDisconnect(BLEServer* server) override {
    connected = false;
    server->getAdvertising()->start();
  }
};

void publishValue() {
  char value[32];
  snprintf(value, sizeof(value), "count=%lu",
           static_cast<unsigned long>(counter));
  value_characteristic->setValue(
      reinterpret_cast<uint8_t*>(value), strlen(value));
  if (connected) value_characteristic->notify();
  Serial.printf("ble,%s,connected=%d\n", value, connected);
}
void drawStatus() {
  M5.Display.fillRect(48, 82, 370, 302, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(connected ? TFT_GREEN : TFT_CYAN, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.drawString(connected ? "CONNECTED" : "ADVERTISING",
                        M5.Display.width() / 2, 132);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.drawString("Device: M5StopWatch-C152",
                        M5.Display.width() / 2, 205);
  M5.Display.drawString("Service: 7e2c0001...",
                        M5.Display.width() / 2, 242);
  char value[40];
  snprintf(value, sizeof(value), "GATT value: count=%lu",
           static_cast<unsigned long>(counter));
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.drawString(value, M5.Display.width() / 2, 305);
}

}  // namespace

void setup() {
  c152::begin("07 / BLE GATT");
  BLEDevice::init("M5StopWatch-C152");
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ConnectionCallbacks());
  BLEService* service = server->createService(kServiceUuid);
  value_characteristic = service->createCharacteristic(
      kValueUuid, BLECharacteristic::PROPERTY_READ |
                      BLECharacteristic::PROPERTY_NOTIFY);
  value_characteristic->addDescriptor(new BLE2902());
  publishValue();
  service->start();
  BLEAdvertising* advertising = server->getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->setScanResponse(true);
  advertising->start();
  drawStatus();
  c152::drawFooter("A / touch: update + notify", TFT_CYAN);
}

void loop() {
  c152::update();
  static bool previous_connection = false;
  if (previous_connection != connected) {
    previous_connection = connected;
    drawStatus();
  }
  if (c152::primaryWasPressed()) {
    ++counter;
    publishValue();
    drawStatus();
    c152::feedback(5000, 45, 50);
  }
  delay(10);
}
