# 書き込み、バックアップ、復旧

Flash 書き込みは端末の現在のファームウェアを変更します。最初の書き込み前に、チップ情報を読み、工場出荷状態の 16 MiB Flash を丸ごとバックアップしてください。

> [!CAUTION]
> `erase_flash`、eFuse 書き込み、Secure Boot / Flash Encryption の有効化は、この手順には不要です。不可逆または復旧を難しくするため実行しないでください。

## 用意するもの

- M5Stack StopWatch C152
- データ通信対応 USB Type-C ケーブル
- PlatformIO CLI (`pio`)
- [`uv` / `uvx`](https://docs.astral.sh/uv/)（固定版 esptool の隔離実行）
- このリポジトリ
- 工場ファーム復元用として M5Burner

## 電源ボタン操作

- 電源オン / リセット: 1 回短押し
- 電源オフ: 素早く 2 回押す
- ダウンロードモード: USB 接続中に約 2 秒長押しし、内部の緑 LED が点灯したら離す

M5Stack の Arduino / 工場復元チュートリアルでは、電源ボタンを reset button と表現している箇所がありますが、C152 の同じ操作を指します。

## 1. ポートを確認する

```bash
cd /path/to/m5stack-stopwatch
./scripts/detect-port.sh
pio device list
```

macOS では通常 `/dev/cu.usbmodem...` です。複数ある場合は、抜き差しして対象を確認し、以降は `PORT=` で明示します。

ポートが見えなければ、次を順に確認します。

1. 充電専用ではなくデータ対応ケーブルか
2. USB ハブを外して Mac へ直接接続できるか
3. ダウンロードモードへ入り直したか
4. Arduino IDE、PlatformIO monitor、screen などがポートを占有していないか

## 2. 読み取り専用の端末情報

```bash
make device-info PORT=/dev/cu.usbmodemXXXX
```

このコマンドは chip ID、Flash ID、security information を読みます。Secure Boot または Flash Encryption が有効と表示された場合は、バックアップや復元の前提が変わるため、その場で停止して出力を保存してください。

## 3. 工場 Flash をバックアップする

```bash
make backup PORT=/dev/cu.usbmodemXXXX
```

スクリプトは `esptool==4.9.0` を Python 3.11 上で隔離実行し、Flash サイズを 16 MB と明示します。16 MiB (`0x1000000`) を 1 MiB ずつ読み、通信エラーの区画だけ最大 3 回再試行してから、次を `backups/` に作ります。

- `factory-flash-<UTC timestamp>.bin`
- 同じイメージの `.sha256`

`backups/` は Git 管理対象外です。別の安全なストレージにもコピーします。バックアップが 16,777,216 bytes で、SHA-256 が再検証できることを確認します。
スクリプトは `backups/` と一時区画を所有者だけが読める権限で作成します。raw Flash には保存済み設定や認証情報が含まれ得るため、公開共有しません。

```bash
ls -lh backups/
cd backups
shasum -a 256 -c factory-flash-YYYYMMDDTHHMMSSZ.bin.sha256
```

### esptool を直接使う場合

リポジトリの `make backup` を推奨します。ESP-IDF などで `esptool.py` を利用できる場合の同等処理は次です。`PORT` と出力名を実物に置き換えます。

```bash
umask 077
esptool.py --chip esp32s3 --port /dev/cu.usbmodemXXXX \
  --baud 460800 --no-stub read_flash --flash_size 16MB \
  0x0 0x1000000 factory-flash.bin
shasum -a 256 factory-flash.bin > factory-flash.bin.sha256
```

ESP32-S3 の ROM ローダーでは、`--no-stub` と組み合わせる際に `--flash_size 16MB` を省略すると 2 MB 以降で読み取りエラーになることがあります。高い baud rate で通信エラーになる場合は 115200 まで下げます。

## 4. ビルドする

最初は `00_smoke` を使います。

```bash
make build ENV=00_smoke

# PlatformIO 直接なら
pio run -e 00_smoke
```

既定の統合アプリは `99_stopwatch` です。利用可能な環境は `pio project config` または `platformio.ini` で確認できます。

## 5. 書き込む

環境名とポートを再確認して実行します。

```bash
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX

# PlatformIO 直接なら
pio run -e 00_smoke -t upload --upload-port /dev/cu.usbmodemXXXX
```

書き込み後に自動起動しなければ、電源ボタンを 1 回短押しします。

## 6. シリアルログを見る

```bash
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX

# PlatformIO 直接なら
pio device monitor -e 00_smoke --port /dev/cu.usbmodemXXXX
```

既定は 115200 bps です。`Ctrl-C` で終了します。モニターを開いたままでは次の書き込みがポートを取得できないことがあります。

## 機能別の安全な書き込み順

1. `00_smoke`: 最小起動
2. `01_display_input`: 画面、タッチ、ボタン
3. `02_imu`: IMU
4. `03_rtc_power`: RTC と電源
5. `04_audio_haptics`: 低音量で audio / vibration
6. `05_wifi_scan`: 認証情報なしの Wi-Fi scan
7. `07_ble_gatt`: BLE GATT
8. `08_external_i2c`: 外付け機器を確認してから Port A
9. `99_stopwatch`: 統合アプリ

問題が起きたら、外付け機器を外して一段前の環境か `00_smoke` へ戻します。

## 工場ファームウェアへ戻す

### 方法 A: M5Burner（推奨）

M5Stack 公式の復元方法です。

1. 公式 [M5Burner](https://docs.m5stack.com/en/uiflow/m5burner/intro) を導入する。
2. M5Burner で StopWatch の factory firmware / User Demo をダウンロードする。
3. StopWatch を USB 接続し、ダウンロードモードへ入れる。
4. `Burn` を押し、正しいシリアルポートを選んで開始する。
5. 成功表示後、電源ボタンを短押しして再起動する。

工場ファームで画面、タッチ、IMU、音声などが正常なら、自作ファーム側の問題である可能性が高くなります。公式手順は [StopWatch Restore Factory Firmware](https://docs.m5stack.com/en/guide/restore_factory/stopwatch) を参照してください。

### 方法 B: 自分の raw backup

自分で取得し、SHA-256 を確認済みの 16 MiB イメージだけを使います。書き込み先の個体と backup の対応を確認してください。

```bash
cd /path/to/safe/backup-directory
shasum -a 256 -c factory-flash.bin.sha256

esptool.py --chip esp32s3 --port /dev/cu.usbmodemXXXX \
  --baud 460800 write_flash 0x0 factory-flash.bin
```

復元後に電源ボタンを短押しします。Flash Encryption が有効な個体の raw image は別個体へ移植できない場合があります。security information が不明なら M5Burner の公式イメージを使います。

## 公式工場デモをソースからビルドする

M5Stack の [`M5StopWatch-UserDemo`](https://github.com/m5stack/M5StopWatch-UserDemo) は hardware evaluation 用の公式デモで、ESP-IDF **v5.5.4** を指定しています。

```bash
python3 ./fetch_repos.py
idf.py build
idf.py flash
```

これは本リポジトリの PlatformIO / Arduino 環境とは別に構築します。依存リポジトリ、partition table、IDF バージョンを公式 README のまま揃えてください。

## よくある復旧パターン

### 画面が真っ暗だがポートは見える

`00_smoke` を再ビルドして書き込みます。改善しなければ M5Burner で工場ファームへ戻します。

### 書き込み途中で切れる

- baud rate を下げる
- USB ハブを外す
- 別のデータケーブルを使う
- ダウンロードモードへ入り直す
- monitor や IDE を閉じる

### Port A 接続後に起動しない

すぐに外付け機器を外します。電源極性、5 V、GND、G10 / G11、pull-up 電圧、I2C アドレスを再確認し、`00_smoke` 単体へ戻します。

### 工場ファームでも異常

外付け機器をすべて外し、別の USB ケーブルと電源で再確認します。それでも同じならハードウェア故障の可能性があるため、症状、工場ファーム版、写真、シリアルログを保存して M5Stack support へ相談します。
