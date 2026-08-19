# 公式参照資料

2026-08-19 に確認した一次資料です。仕様やツールは更新されるため、ピン接続、電源、依存バージョンを変更するときはリンク先の最新版と照合してください。

## M5Stack StopWatch

- [StopWatch C152 製品資料（日本語）](https://docs.m5stack.com/ja/core/StopWatch)
- [StopWatch C152 product document（英語）](https://docs.m5stack.com/en/core/StopWatch) — 仕様、`BAT` 誤印字訂正、回路図、ピンマップ、PlatformIO 設定への入口
- [Arduino example compile / upload](https://docs.m5stack.com/en/arduino/stopwatch/program)
- [Button API / example](https://docs.m5stack.com/en/arduino/stopwatch/button)
- [Touch API / example](https://docs.m5stack.com/en/arduino/stopwatch/touch)
- [IMU API / example](https://docs.m5stack.com/en/arduino/stopwatch/imu)
- [Microphone API / example](https://docs.m5stack.com/en/arduino/stopwatch/mic) — マイクとスピーカーの切替例
- [Speaker API / example](https://docs.m5stack.com/en/arduino/stopwatch/speaker)
- [RTC API / example](https://docs.m5stack.com/en/arduino/stopwatch/rtc)
- [Vibration API / example](https://docs.m5stack.com/en/arduino/stopwatch/vibration)
- [M5PM1 / M5IOE1 power management example](https://docs.m5stack.com/en/arduino/stopwatch/m5pm1_m5ioe1)
- [Factory firmware usage](https://docs.m5stack.com/en/guide/display_device/stopwatch/usage)
- [Restore factory firmware](https://docs.m5stack.com/en/guide/restore_factory/stopwatch)
- [UiFlow2 StopWatch quick start](https://docs.m5stack.com/en/uiflow2/stopwatch/program)
- [M5Burner](https://docs.m5stack.com/en/uiflow/m5burner/intro)

## M5Stack 公式 GitHub

- [M5StopWatch-UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo) — 工場デモ、ESP-IDF v5.5.4
- [M5Unified](https://github.com/m5stack/M5Unified) — display、touch、buttons、IMU、RTC、audio、power の統合 API
- [M5GFX](https://github.com/m5stack/M5GFX) — 描画ライブラリ
- [M5PM1](https://github.com/m5stack/M5PM1) — 電源管理ドライバ
- [M5IOE1](https://github.com/m5stack/M5IOE1) — IO expander ドライバ

## Espressif

- [ESP32-S3 product page](https://www.espressif.com/en/products/socs/esp32-s3) — Wi-Fi、Bluetooth 5（LE）、CPU 概要
- [ESP32-S3 datasheet](https://documentation.espressif.com/esp32-s3_datasheet_en.pdf)
- [ESP-IDF v5.5.4 Programming Guide for ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html)
- [ESP32-S3 Bluetooth LE overview](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/ble/overview.html) — ESP32-S3 は LE のみ。Bluedroid / NimBLE の概要
- [esptool](https://github.com/espressif/esptool) — Flash 読み書きツール
- [esptool: Read Flash Contents](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/basic-commands.html#read-flash-contents-read-flash) — `--no-stub` 時の Flash サイズ明示
- [Arduino core for ESP32](https://github.com/espressif/arduino-esp32)

## 開発ツール

- [PlatformIO Espressif 32 platform](https://docs.platformio.org/en/latest/platforms/espressif32.html)
- [PlatformIO Core CLI](https://docs.platformio.org/en/latest/core/index.html)
- [M5Stack Arduino 開発環境](https://docs.m5stack.com/ja/arduino/arduino_ide)
- [UiFlow2 Web IDE](https://uiflow2.m5stack.com/)

## 情報の区別

### 公式 StopWatch 製品仕様に明記

- ESP32-S3R8、16 MB Flash、8 MB PSRAM
- 2.4 GHz Wi-Fi
- 466 × 466 AMOLED / CST820B touch
- BMI270 6 軸 IMU
- ES8311、MEMS mic、speaker
- RX8130CE、buttons、vibration、M5PM1、450 mAh battery
- Port A G10 / G11、rear expansion bus
- `BAT` 印字が実際は 5V IN であるという訂正

### SoC 公式仕様 + この個体のチップ情報

- Bluetooth 5（LE）

M5Stack の StopWatch 製品仕様表は wireless connectivity として Wi-Fi だけを列挙しています。一方、Espressif は ESP32-S3 の Bluetooth 5（LE）対応を明記し、この StopWatch 個体のブートローダー情報も BLE capability を報告しました。GATT サンプルはビルド済みですが、advertising・接続・notify の実機 runtime test は未実施です。文書ではこの違いを維持します。

### 公式仕様で確認できないため「ない / 不明」と扱う

- 心拍、SpO2、GPS/GNSS、環境センサー、カメラ、microSD は内蔵一覧にない
- BMI270 は加速度・ジャイロであり、磁気センサーではない
- IP 防水・防滴等級は記載を確認できない

## ライセンスについて

このリポジトリ自体のライセンスは現時点で未設定です。リンク先のコード、データシート、画像、サンプルは各権利者のライセンス・利用条件に従います。公式サンプルを取り込む場合も、出典だけでなくライセンス互換性を確認してください。
