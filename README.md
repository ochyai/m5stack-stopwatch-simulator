# M5Stack StopWatch 開発リポジトリ

M5Stack StopWatch（C152）を、Mac から再現可能な形で調査・開発するためのリポジトリです。丸形 AMOLED、タッチ、2 ボタン、6 軸 IMU、RTC、マイク、スピーカー、振動、Wi-Fi / Bluetooth LE、外部 I2C を、機能ごとの小さなファームウェアで確認できます。

> [!CAUTION]
> 一部ロットでは背面端子の `BAT` 印字が誤っています。実際は外部電源用の **5V IN** です。リチウム電池を接続しないでください。M5Stack 公式の訂正事項です。

## まず分かっていること

| 項目 | 内容 |
| --- | --- |
| MCU | ESP32-S3R8、デュアルコア LX7 最大 240 MHz |
| メモリ | 16 MB Flash、8 MB PSRAM |
| 画面 | 1.75 インチ、466 × 466、丸形 AMOLED（CO5300） |
| 入力 | CST820B タッチ、プログラマブルボタン × 2、電源ボタン |
| モーション | BMI270（3 軸加速度 + 3 軸ジャイロ、磁気センサーなし） |
| 音声 | MEMS マイク、ES8311 Codec、1 W / 8 Ω スピーカー |
| その他 | RX8130CE RTC、振動モーター、M5PM1 電源管理、450 mAh バッテリー |
| 無線 | 2.4 GHz Wi-Fi。Bluetooth LE は ESP32-S3 の SoC 機能としてチップ情報で確認。GATT 実動作は未検証 |
| 拡張 | Port A（G10 / G11）と背面 2.54 mm 拡張バス |

心拍、SpO2、GPS/GNSS、温湿度・気圧などの環境センサー、カメラ、microSD は内蔵していません。必要なら Port A または背面バスへ外付けします。防水・防滴等級は公式仕様で確認できないため、水に濡らさない前提で扱います。

詳細は [ハードウェア情報](docs/HARDWARE.md) を参照してください。

## できること

- ストップウォッチ、ラップタイマー、ポモドーロ、アラーム、独自ウォッチフェイス
- タッチ、物理ボタン、傾き、振動を組み合わせたウェアラブル UI
- Wi-Fi ダッシュボード、HTTP / MQTT リモコン、時刻同期端末
- Bluetooth LE の GATT リモコン、近接インタラクション、センサーテレメトリー
- 録音・音声再生・通知音の実験。ただし内蔵マイクとスピーカーは同時使用不可
- Port A の I2C センサーや背面バスを使った機能拡張

具体案は [プロジェクト案](docs/PROJECT_IDEAS.md) にまとめています。

## 最初の 10 分

書き込みにはデータ通信対応の USB Type-C ケーブルを使います。**最初の書き込みより先に工場出荷ファームウェアをバックアップ**してください。

```bash
cd /path/to/m5stack-stopwatch
pio --version
uvx --version

# 端末をダウンロードモードにして、表示されたポートを指定する
./scripts/detect-port.sh
make device-info PORT=/dev/cu.usbmodemXXXX
make backup PORT=/dev/cu.usbmodemXXXX

# 最小診断をビルドして書き込む
make build ENV=00_smoke
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
```

ダウンロードモードは、USB 接続後に電源ボタンを約 2 秒長押しし、内部の緑 LED が点灯したら離します。詳しくは [書き込み・復旧手順](docs/FLASHING.md) を参照してください。

PlatformIO を直接使う場合の同等コマンドです。

```bash
pio run -e 00_smoke
pio run -e 00_smoke -t upload --upload-port /dev/cu.usbmodemXXXX
pio device monitor -e 00_smoke --port /dev/cu.usbmodemXXXX
```

## サンプル環境

| PlatformIO 環境 | 確認内容 |
| --- | --- |
| `00_smoke` | ボード、画面、入力の最小起動確認 |
| `01_display_input` | AMOLED、タッチ、2 ボタン |
| `02_imu` | BMI270 加速度・ジャイロ |
| `03_rtc_power` | RTC、バッテリー、電源情報 |
| `04_audio_haptics` | マイク、スピーカー、振動 |
| `05_wifi_scan` | 2.4 GHz Wi-Fi スキャン |
| `07_ble_gatt` | Bluetooth LE GATT |
| `08_external_i2c` | Port A の I2C スキャン |
| `99_stopwatch` | ストップウォッチ本体 |
| `native` | ホスト上でのロジック単体テスト |

既定環境は `99_stopwatch` です。全ファームウェアとロジックテストは `make build-all`、テストだけなら `make test` で確認できます。

## 開発方法

このリポジトリでは **PlatformIO CLI を正本**にします。VS Code + PlatformIO 拡張からも同じ `platformio.ini` を利用できます。Arduino IDE、UiFlow2、ESP-IDF も選択肢ですが、同じ端末へ別方式のファームウェアを書けば現在の内容は上書きされます。

- [開発環境とコーディング手順](docs/DEVELOPMENT.md)
- [書き込み、バックアップ、工場ファーム復元](docs/FLASHING.md)
- [公式一次資料](docs/REFERENCES.md)

## リポジトリ構成

```text
firmware/apps/       機能別ファームウェア
firmware/shared/     共通のボード初期化とロジック
scripts/             ビルド、ポート検出、バックアップ、書き込み
test/                PC 上で動かす単体テスト
docs/                ハードウェア、開発、復旧、アイデア、参照資料
platformio.ini       固定したビルド環境と依存ライブラリ
```

## ライセンス

このリポジトリのライセンスは現時点で未設定です。`LICENSE` が追加されるまで、コードや文書の再配布・派生利用条件は確定していません。依存ライブラリと公式サンプルには、それぞれのライセンスが適用されます。
