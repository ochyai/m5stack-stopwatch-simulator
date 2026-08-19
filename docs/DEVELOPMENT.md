# 開発環境とプログラミング手順

## 推奨構成

このリポジトリでは PlatformIO CLI と `platformio.ini` を正本にします。ビルド、依存ライブラリ、ボード設定をリポジトリ内で共有でき、VS Code からも CLI からも同じ結果を得やすいためです。

| 方法 | 位置づけ | 向いている用途 |
| --- | --- | --- |
| PlatformIO + Arduino framework | **推奨・本リポジトリの正本** | 日常開発、CI、機能別サンプル、再現可能なビルド |
| Arduino IDE | 代替 | 公式サンプルをそのまま試す、初学者向け GUI |
| UiFlow2 | 代替 | Blockly / MicroPython 系の短い試作 |
| ESP-IDF 5.5.4 | 上級・別プロジェクト | 公式工場デモの解析、低レベル機能、IDF 固有 API |

どの方法でも Flash を共有するため、方式を切り替えると現在のファームウェアは上書きされます。最初に [バックアップ手順](FLASHING.md) を実施してください。

## この Mac の確認済み状態

2026-08-19 に確認した状態です。将来の状態は各コマンドで再確認してください。

| 項目 | 状態 |
| --- | --- |
| Visual Studio Code | `/Applications/Visual Studio Code.app` に導入済み |
| `code` CLI | PATH 未登録。アプリを直接開くか VS Code から Shell Command を追加 |
| Arduino IDE | `/Applications/Arduino IDE.app` に導入済み |
| PlatformIO CLI | 6.1.19 |
| [`uv` / `uvx`](https://docs.astral.sh/uv/) | 導入済み。工場 Flash バックアップ用の esptool 4.9 を隔離実行 |
| `arduino-cli` | 1.5.1 |
| Python | 3.14.7 |
| Arduino ESP32 core | 3.3.3 |
| M5Stack Board Manager | 未導入。Arduino IDE 経路を使う場合だけ追加が必要 |

日常作業では次を確認すれば十分です。

```bash
cd /path/to/m5stack-stopwatch
pio --version
uvx --version
pio project config
make help
```

## PlatformIO

### 依存関係

`platformio.ini` は M5Stack 公式 StopWatch 設定を基礎に、次を固定しています。

- `espressif32 @ 6.12.0`
- Arduino framework
- 16 MB Flash partition
- QIO / OPI memory mode、8 MB PSRAM
- USB CDC on boot
- `10_sokkon`だけは継承した`CORE_DEBUG_LEVEL=5`を解除し、libraryのverbose logがUSB protocol frameへ混入しない構成
- 安定性を優先した 460800 baud の初期書き込み
- M5Unified、M5GFX、M5PM1、M5IOE1

初回ビルド時に PlatformIO がツールチェーンとライブラリを取得します。依存バージョンを変える場合は、全環境のビルドと実機の smoke test を行います。

工場 Flash の読み取りだけは `uvx` で `esptool==4.9.0` を Python 3.11 上に隔離して実行します。ESP32-S3 の ROM ローダーで 2 MB 以降を読むには Flash サイズの明示が必要で、PlatformIO のビルド用に固定した古い esptool とは役割を分けています。初回だけ `uvx` が専用環境を取得します。

### ビルド

```bash
# 既定の 10_sokkon
make build

# 1 機能だけ
make build ENV=00_smoke

# 宣言済みの全環境
make build-all

# ハードウェア非依存ロジックだけ
make test

# PlatformIO を直接使う場合
pio run -e 02_imu
```

### 実機へ書き込む

1. データ対応 USB Type-C ケーブルで接続する。
2. 電源ボタンを約 2 秒長押しし、緑 LED が点灯したら離す。
3. `./scripts/detect-port.sh` で `/dev/cu.usbmodem...` を確認する。
4. 初回だけは `make device-info` と `make backup` を先に実行する。
5. 環境名とポートを明示して書き込む。

```bash
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
```

シリアルモニターは `Ctrl-C` で終了します。詳しくは [FLASHING.md](FLASHING.md) を参照してください。

### 機能別環境

| 環境 | 目的 | 主な確認点 |
| --- | --- | --- |
| `00_smoke` | 最小診断 | ボード識別、表示、基本入力 |
| `01_display_input` | UI 入力 | AMOLED、タッチ座標、Button A / B |
| `02_imu` | モーション | 加速度、角速度、更新周期 |
| `03_rtc_power` | 時刻・電源 | RTC、バッテリー状態、電源 API |
| `04_audio_haptics` | 音・触覚 | マイク / スピーカー切替、振動 |
| `05_wifi_scan` | Wi-Fi | 2.4 GHz AP スキャン。認証情報不要 |
| `07_ble_gatt` | Bluetooth LE | Advertising、GATT 接続 |
| `08_external_i2c` | 外部拡張 | Port A の G10 SDA / G11 SCL スキャン |
| `10_sokkon` | Mac連携 | MARK、mode、focus、USB companion、確定feedback |
| `99_stopwatch` | 統合アプリ | 開始・一時停止・リセット、UI、RTC |
| `native` | PC テスト | ハードウェア非依存の状態遷移 |

安全な導入順は `00_smoke` → `01_display_input` → `02_imu` → `03_rtc_power` → 必要な単機能 → `10_sokkon` です。純粋なストップウォッチだけを使う場合は `99_stopwatch` を選びます。

## Mac companion

SOKKONはmacOS標準のPython 3機能とPOSIX serial APIだけで動き、`pyserial`を必要としません。

```bash
# 初回だけ: handshakeのみで接続中の端末をpairする
make companion-pair

# 自動検出した /dev/cu.usbmodem* へ接続し続ける
make companion

# 接続とSTATE送信だけを短く確認
make companion-once

# configやportを明示する
make companion ARGS="--port /dev/cu.usbmodemXXXX --config companion/config.example.json"

# 単体・擬似端末（PTY）統合テスト
make companion-test
```

初回の`make companion-pair`は`PING`とREADY / PONG handshakeだけを行い、`STATE`、前面アプリ名、actionを一切送らずに終了します。確認した12桁hex device IDは既定で`~/.config/sokkon/device.json`へ、mode `0600`、fileとdirectoryの`fsync`、atomic replaceで保存します。通常の`make companion`はbindingを必須とし、期待したdevice IDと一致しない端末を拒否します。同じprocess内のserial reconnectでもdevice IDをpinし続けます。

保存先を変える場合はpair時と通常起動の両方へ`--binding /absolute/path/device.json`を渡します。別個体へbindingを交換するときだけ、物理的に対象を確認したうえで`make companion-pair ARGS="--replace-binding"`を使います。`--replace-binding`はpair時以外には使えません。実機のdevice IDやbinding fileはrepositoryへ記載・commitしません。

これは暗号認証ではなく、初回の物理USB接続を信頼起点にしたpersistent pairingです。選択したserial port、protocol version、保存済みdevice ID、起動ごとのsession IDを検査しますが、IDを知るdeviceによるなりすましをcryptographicに防ぐものではありません。

前面アプリ名の取得には固定したJXA / AppKitスクリプトを`/usr/bin/osascript`へ引数配列で渡します。ウィンドウタイトル、本文、キー入力、画面は読みません。任意shell commandは実行せず、Shortcutもconfigに明記した名前だけを`/usr/bin/shortcuts run`で非同期起動します。serial loopは完了を待たず、background reaperが30秒上限でprocessを回収します。Shortcut workflowの最終成功はprotocol RESULTの保証に含みません。companion自身はnetwork connectionを開きませんが、`Documents`配下の保存fileはmacOS / iCloud設定によりOSが同期する場合があります。詳細は [SOKKON.md](SOKKON.md) を参照してください。

## 最小コードの考え方

M5Unified を直接使う最小形は次の通りです。

```cpp
#include <M5Unified.h>

void setup() {
  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  M5.begin(cfg);

  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString("Hello StopWatch",
                        M5.Display.width() / 2,
                        M5.Display.height() / 2);
}

void loop() {
  M5.update();

  if (M5.BtnA.wasPressed()) {
    M5.Power.setVibration(100);
    delay(60);
    M5.Power.setVibration(0);
  }
}
```

このリポジトリのアプリでは `firmware/shared/board.hpp` の `c152::begin()` と `c152::update()` を使い、初期化、明るさ、シリアル、短い非ブロッキング振動などを共通化します。

## コーディング上の注意

### 入力更新

`M5.update()` が呼ばれないとボタンやタッチのイベントを取り逃がします。UI ループを長時間ブロックせず、時刻差による状態機械で処理します。

### AMOLED とメモリ

- 固定した高輝度表示を長時間続けず、輝度低下、画面消灯、要素移動を検討する。
- 466 × 466 のフル画面 16-bit バッファは約 424 KiB。複数バッファや画像資産には PSRAM を使う。
- 描画中のちらつき対策には sprite / canvas が有効だが、確保失敗を確認する。

### オーディオ

内蔵マイクとスピーカーを同時に開始しません。録音と再生の境界で `end()` / `begin()` を明示し、録音 DMA の完了を待ちます。大音量を長時間鳴らさず、最初は低い音量で試します。

### RTC と時刻

RTC は時刻を保持しますが、タイムゾーンや夏時間は自動ではありません。ネット同期する場合は NTP の UTC とローカル表示を分け、毎起動時に RTC を無条件上書きしない設計にします。

### Wi-Fi と Bluetooth LE

- SSID / パスワードをソースへコミットしない。ローカルの ignored header、provisioning、シリアル入力などを使う。
- ESP32-S3 の Bluetooth は LE のみ。Bluetooth Classic 前提のライブラリを選ばない。
- Wi-Fi と BLE は 2.4 GHz 無線を共用するため、同時利用では遅延と消費電力を実測する。

### 外部 I2C

Port A は G10 = SDA、G11 = SCL として使います。外部機器を挿す前に電源電圧、I2C アドレス、pull-up 電圧を確認し、内部システム I2C の G47 / G48 と混同しないでください。

## Arduino IDE を使う場合

公式 StopWatch Arduino 例の要件は次の通りです。

- M5Stack Board Manager `>= 3.3.7`
- Board: `M5StopWatch`
- M5Unified `>= 0.2.15`
- M5GFX `>= 0.2.21`

現在この Mac には Arduino IDE と Arduino ESP32 core はありますが、M5Stack Board Manager は未導入です。公式の [Arduino 開発環境手順](https://docs.m5stack.com/ja/arduino/arduino_ide) に従って追加し、ボードを `M5StopWatch` にします。本リポジトリの再現性確認は引き続き PlatformIO で行います。

## UiFlow2 を使う場合

UiFlow2 は Blockly で短い試作を行う経路です。M5Burner から StopWatch 用 UiFlow2 ファームウェアを書き込み、[UiFlow2 Web IDE](https://uiflow2.m5stack.com/) で StopWatch を選択します。

- `Run Once`: 一度だけ実行して試す
- `Run Always`: 端末へ保存して起動時に実行する

UiFlow2 ファームウェアの書き込みも既存 Flash を上書きします。先にバックアップしてください。

## ESP-IDF を使う場合

M5Stack の公式工場デモ [`M5StopWatch-UserDemo`](https://github.com/m5stack/M5StopWatch-UserDemo) は ESP-IDF **v5.5.4** を指定しています。公式デモを解析・再ビルドするときは、そのリポジトリの `fetch_repos.py` と IDF バージョンを使い、本リポジトリの Arduino / PlatformIO ビルドへ無理に混在させません。

## トラブルシュート

### ポートが見えない

- 充電専用ではなくデータ対応ケーブルか確認する。
- ダウンロードモードへ入り直す。
- `ls /dev/cu.usbmodem*` と `pio device list` を確認する。
- Arduino IDE や別のシリアルモニターを閉じる。

### ビルドできない

```bash
pio --version
pio run -e 00_smoke -v
pio run -e 00_smoke -t clean
pio run -e 00_smoke
```

Python 3.14 と一部の古い補助ツールに互換問題が出る場合があります。PlatformIO が管理する環境を優先し、グローバル Python へ無計画に依存を追加しません。

### 画面やセンサーが初期化されない

- PlatformIO の environment と 16 MB / OPI PSRAM 設定を確認する。
- `00_smoke` へ戻して切り分ける。
- 外付け機器をすべて外す。
- 工場ファームウェアを M5Burner で復元し、ハードウェア故障か自作コードかを切り分ける。
