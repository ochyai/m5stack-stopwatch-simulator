# M5Stack StopWatch / SOKKON 開発リポジトリ

M5Stack StopWatch（C152）を、Mac から再現可能な形で調査・開発するためのリポジトリです。既定アプリ **SOKKON / 即今** は、この丸い端末を「現在の文脈を物理的に支える界面」に変えます。丸形 AMOLED、タッチ、2 ボタン、6 軸 IMU、RTC、マイク、スピーカー、振動、Wi-Fi / Bluetooth LE、外部 I2C は、機能別ファームウェアからも確認できます。

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

## いま使う — SOKKON / 即今

USB Type-C でMacにつなぎ、標準ライブラリだけのcompanionを起動します。companion自身はネットワーク通信を行わず、前面アプリ名だけを現在の文脈として端末へ表示します。既定保存先の`Documents`は、macOS / iCloud設定によってOSが同期する場合があります。

```bash
# 初回だけ: 工場Flashをバックアップした後、SOKKONを書き込む
make build ENV=10_sokkon
make flash ENV=10_sokkon PORT=/dev/cu.usbmodemXXXX

# 初回だけ: 物理接続中のdevice IDをMacへpairする
make companion-pair ARGS="--port /dev/cu.usbmodemXXXX"

# pair後の日常利用: USB companionを起動する
make companion
```

pairing中はprotocol v2 handshakeだけを行い、前面アプリ名、`STATE`、actionを送信しません。device IDは既定で`~/.config/sokkon/device.json`へ保存され、以後の通常起動はbindingと一致する端末だけを受け入れます。別個体へ意図的に交換する手順やtrust boundaryは [SOKKON設計](docs/SOKKON.md) を参照してください。

| 操作 | 結果 |
| --- | --- |
| 黄色 A | `~/Documents/Sokkon Inbox.md` へ現在時刻・mode・前面アプリ・focus時間をMARK |
| 青 B | `NOW → BUILD → READ → MEET → PRESENT → REST` を循環 |
| 画面中央 | FOCUS timerを開始 / 一時停止 |

MARKはMacがMarkdownを`fsync`できた後だけ強い確定振動を返します。未接続と明示的な保存失敗は「未保存」ですが、30秒応答がない場合は、保存後の応答だけ失われた可能性もあるため`SAVE UNKNOWN`と表示します。この場合はinboxを確認してから再試行してください。任意shellは実行せず、追加アクションはJSON configに名前を明示したmacOS Shortcutだけです。設計、USB protocol v2、プライバシー境界、次の実験は [SOKKON設計](docs/SOKKON.md) を参照してください。

## Macで先に動かす — compiler-driven simulator

実機へ書き込む前に、本番`main.cpp`と`board.cpp`をMacのC++コンパイラで直接動かせます。ブラウザは別実装のモックではなく、本番C++が出した466 × 466の描画命令と状態を表示します。既定のSOKKONに加え、別の本番コード`99_stopwatch`も同じHALとCanvas経路で実行できます。

```bash
# 本番C++をコンパイルし、localhostで起動してブラウザを開く
make simulator

# 別の本番コード: A/タッチで開始・停止、Bでリセット
make simulator FIRMWARE=99_stopwatch

# ブラウザを開かず起動。追加引数も渡せる
make simulator-serve ARGS="--port 9000"

# native runner、process bridge、HTTP/static UIの回帰テスト
make simulator-test

# 共有描画レンダラー、transport、Sites packageのテスト
make workbench-test

# セッションを再生し、report.jsonと1枚のcontact sheetを書き出す
make session SCRIPT=scenarios/sokkon-face.sim

# ブラウザ無しで、画面に出ない描画だけを報告させる
make session-report SCRIPT=scenarios/sokkon-host-states.sim

# 初回だけ: 3ペインのFirmware Workbenchを準備
make workbench-install

# ファーム切替、Inspector、イベントTimeline付きWorkbenchを起動
make workbench FIRMWARE=99_stopwatch

# Pythonやlocalhost serverを使わないmacOSアプリとローカルDMGを生成
make macos-app
make macos-dmg
```

## 実機なしで画面を確かめる

文字の寸法は推定していません。`simulator/native/include/font_metrics.hpp`は実機が使うM5GFXパッケージから計測した生成物で、`textWidth`と`drawString`の幾何はLovyanGFXの実装をそのまま移植しています。だから`10_sokkon`が「300pxに収まるまで`...`で詰める」処理は、実機と同じ位置で切れます。native runnerは1文字ごとのpen位置も発行し、UIはそのグリッド上に描きます。

`scenarios/*.sim`は、UIが送るのと同じコマンド（ボタン、仮想時間、シナリオ、SHOT）だけで書かれた再生スクリプトです。再生中は時間が凍結されるので、同じスクリプトはどのマシンでも同じフレームを出します。

```bash
make session SCRIPT=scenarios/sokkon-face.sim
```

`.simulator/sessions/`に、全SHOTを並べた`contact-sheet.png`と`report.json`が出ます。report内のfindingsは好みではなく幾何的事実です。

- `severity: error` — 466×466の外、**丸い**AMOLEDの可視円の外、文字同士の重なり（画面に出ない）
- `severity: notice` — 後から描いた塗りに文字が隠れている（トーストなど、人が判断する）

ブラウザで触った操作は`python3 -m simulator --record path.sim`でそのまま再生スクリプトになります。`test_simulator/golden/`は各シナリオが描いたフレームを固定していて、意図しないレイアウト変更はテストで落ちます。意図した変更なら`make golden-update`で更新し、差分をレビューしてからコミットします。

どのUIも描画命令を自前で解釈しません。native runnerが出した`frame.commands`は`simulator/static/frame-renderer.js`という1つのESモジュールだけが解釈し、従来UIとWorkbenchの両方がそれをimportします。同様にnative runner側の共通処理（NDJSON、シナリオ、時間スケール、コマンドループ）は`simulator/native/include/sim_host.hpp`にあり、各runnerは1つの本番ファームウェアの意味論だけを持ちます。

Workbenchの既定URLは`http://127.0.0.1:4173/`、従来UI/APIは`http://127.0.0.1:8765/`です。`FIRMWARE=10_sokkon`と`FIRMWARE=99_stopwatch`は固定レジストリからだけ選べ、選択値からファイルパスやコンパイラ引数を組み立てません。外部サービスや実機は不要です。

`M5Stack Simulator.app`はWorkbench、Swiftの型付きbridge、両方のnative runnerを自己完結で内包します。生成物は`macos/M5StackSimulator/dist/`です。現在のDMGはこのMac向けのad-hoc署名版で、一般公開にはリポジトリlicenseの決定、Developer ID署名、notarizationが別途必要です。仕組みと操作は [Mac Simulator](docs/SIMULATOR.md)、アプリの信頼境界と配布手順は [macOS app](macos/M5StackSimulator/README.md) を参照してください。

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
| `10_sokkon` | Mac連携の即今インターフェース（既定） |
| `99_stopwatch` | ストップウォッチ本体 |
| `native` | ホスト上でのロジック単体テスト |

既定環境は `10_sokkon` です。全ファームウェアとロジックテストは `make build-all`、端末非依存の純粋ロジックは `make test`、Mac companionは `make companion-test`、本番SOKKON全体をhost compilerで動かす統合テストは`make simulator-test`で確認できます。

## 開発方法

このリポジトリでは **PlatformIO CLI を正本**にします。VS Code + PlatformIO 拡張からも同じ `platformio.ini` を利用できます。Arduino IDE、UiFlow2、ESP-IDF も選択肢ですが、同じ端末へ別方式のファームウェアを書けば現在の内容は上書きされます。

- [開発環境とコーディング手順](docs/DEVELOPMENT.md)
- [本番C++を動かすMac Simulator](docs/SIMULATOR.md)
- [書き込み、バックアップ、工場ファーム復元](docs/FLASHING.md)
- [公式一次資料](docs/REFERENCES.md)

## リポジトリ構成

```text
firmware/apps/       機能別ファームウェア
firmware/shared/     共通のボード初期化とロジック
companion/           追加依存なしの macOS USB companion
simulator/native/    本番C++を動かすnative HALと、共有host framework(sim_host.hpp)上のrunner
simulator/static/    従来UIと、両UIが共有する描画レンダラー(frame-renderer.js)
simulator/workbench/ 3ペインのFirmware Workbench (React)
scenarios/            再生可能なセッションスクリプト
test_simulator/golden/ 各シナリオが描いたフレームの正本
macos/               自己完結型M5Stack Simulator.appとDMGのbuild定義
scripts/             ビルド、ポート検出、バックアップ、書き込み
test/                PC 上で動かす単体テスト
test_companion/      companion の単体・PTY統合テスト
test_simulator/      compiler-driven simulatorの統合・HTTPテスト
docs/                ハードウェア、開発、復旧、アイデア、参照資料
platformio.ini       固定したビルド環境と依存ライブラリ
```

## ライセンス

このリポジトリのライセンスは現時点で未設定です。`LICENSE` が追加されるまで、コードや文書の再配布・派生利用条件は確定していません。依存ライブラリと公式サンプルには、それぞれのライセンスが適用されます。
