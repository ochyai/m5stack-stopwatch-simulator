# M5Stack StopWatch Mac Simulator

このsimulatorは、ブラウザ上の見た目だけを模倣するモックではありません。製品ファームウェアの
`main.cpp`と`firmware/shared/board.cpp`を、MacまたはLinuxのC++コンパイラで直接ビルドして実行する
**compiler-driven digital twin** です。現在はSOKKONと独立ストップウォッチの2本を選べます。

```bash
# ビルド、native統合テスト、HTTP/static UIテスト
make simulator-test

# localhostで起動して既定ブラウザを開く
make simulator

# 別の本番main.cppを同じnative HALでコンパイルして起動
make simulator FIRMWARE=99_stopwatch

# ブラウザを自動で開かず起動
make simulator-serve

# Xcode Simulator風のFirmware Workbench
make workbench-install
make workbench FIRMWARE=99_stopwatch

# 自己完結するmacOSアプリとローカルDMG
make macos-app
make macos-dmg
```

従来のHTTP simulatorの既定URLは `http://127.0.0.1:8765/` です。外部サービス、CDN、クラウド、
実機は使いません。このHTTP simulator単体はApple ClangまたはGCC系のC++ compilerとPython 3だけで
動作し、追加のPython packageも不要です。

Firmware Workbenchの準備とbuildにはNode.js 22 / npmが必要です。自己完結する`.app` / DMGの作成は
macOS上でSwift toolchainとAppleの`plutil`、`sips`、`iconutil`、`codesign`、`hdiutil`を使います。
公開配布時はこれらに加えてDeveloper ID証明書とnotarization用の認証情報が必要です。

## Firmware WorkbenchとmacOSアプリ

`simulator/workbench/`は、firmware一覧、Build & Run、実機比率のC152、Inputs / Display / System
Inspector、Event Timelineを1つのdesktop UIへまとめます。`make workbench`ではViteが`4173`、Python bridgeが
`8765`で動き、画面上から`10_sokkon`と`99_stopwatch`を安全に切り替えられます。新しいrunnerが起動し、
firmware IDと最初のsnapshotを検証できるまで現在のrunnerを停止しません。

`macos/M5StackSimulator/`は同じWorkbenchをSwiftUI + WKWebViewへ内包します。HTTPやPythonを起動せず、
allowlistされたPromise APIからSwiftのProcess bridgeへ接続し、bundle内の2本のnative runnerだけを実行します。
macOSのtraffic-light controlsを使うためHTML側に偽のtitle barは置きません。詳しいbridge contract、child process
lifecycle、resource traversal防止、local app / DMG、Developer ID配布準備は
[M5Stack Simulator for macOS](../macos/M5StackSimulator/README.md)を参照してください。

## 対応ファームウェア

| `FIRMWARE` | コンパイルする正本 | A / B / touch |
| --- | --- | --- |
| `10_sokkon`（既定） | `firmware/apps/10_sokkon/main.cpp` | MARK / MODE / FOCUS |
| `99_stopwatch` | `firmware/apps/99_stopwatch/main.cpp` | start-pause / reset / start-pause |

各ファームウェアは別native binaryと専用adapterを持ちます。adapterは本番の匿名namespaceにある状態を
観測可能なsnapshotへ投影しますが、stopwatchやSOKKONの状態機械を複製しません。選択値は固定allowlist
へ完全一致したIDだけで、選択値から任意パスやcompiler optionを組み立てられない設計です。

## なぜコードから動くのか

```text
firmware/apps/10_sokkon/main.cpp ─┐
firmware/shared/board.cpp ─────────┼─ host C++ compiler ─ native runner
Arduino / M5Unified / ESP32 HAL ───┘                         │
                                                            ├─ framebuffer draw commands
browser canvas ◀─ localhost HTTP API ◀─ Python process bridge┼─ protocol / haptic log
                                                            └─ screen / pending state
```

`simulator/native/include/`にある薄いHALが、実機のArduino、M5Unified、ESP32 APIだけを置き換えます。
以下はSOKKON adapterが実行する範囲です。
`setup()`と`loop()`、ボタン分岐、タッチ判定、mode循環、focus timer、USB protocol v2、pending queue、
5秒のhost切断、30秒の結果不明、2分のdim、10分のsleep、画面レイアウトは本番C++が実行します。
ブラウザはC++から受け取った`fillScreen`、`drawCircle`、`drawArc`、`drawString`、`fillCircle`、
`fillRoundRect`を466×466 Canvasへ描くだけです。

したがって、ファームウェアの文字列、座標、色、制御フローを変えると、再ビルド後のsimulatorにも
そのまま現れます。Python/JavaScriptにはSOKKONの状態機械を複製しません。

描画命令を解釈する実装も1つだけです。`simulator/static/frame-renderer.js`が唯一のinterpreterで、
従来UI(`simulator/static/app.js`)とWorkbench(`simulator/workbench/src/App.jsx`)がこれをimportします。
これによって「どちらのUIで見たか」で画素が変わることがありません。font familyのような純粋な見た目
だけをtypography optionで渡します。回帰は`make workbench-test`が記録用canvas contextで検証します。

native側も同じ考え方です。NDJSONの組み立て、log ring、scenario、時間スケール、コマンドループは
`simulator/native/include/sim_host.hpp`にあり、`simulator/native/runner.cpp`と
`simulator/native/stopwatch_runner.cpp`は担当ファームウェア固有の意味論だけを持ちます。3本目の
firmwareを足すときは`sim_host::Host`を継承し、`FirmwareIdentity`と`screen`ブロックを書けば足ります。

## 筐体のリファレンスとアセット

筐体、円形ベゼル、上側の物理ボタン配置は、M5Stackの
[StopWatch C152公式資料](https://docs.m5stack.com/en/core/StopWatch)にある正面・上面・側面写真を
基準にしています。画面を正立させたとき、操作ボタンはストップウォッチらしく上側に置き、黄色Aは
左上、青Bは右上です。クリック領域も見えているボタンへ重ねています。

`simulator/static/device-shell.png`は公式写真そのものを収録したものではなく、2026-08-19に画像生成で
作成したこのsimulator固有のアセットです。最終編集では「右の青ボタンと筐体を維持し、左の黄色ボタン
だけをC152の上面リファレンスに沿って上へ寄せ、小型の矩形ボタンにする。表示開口は純黒で、文字、
ロゴ、追加ボタン、端子を入れない」と指定しました。Canvasはその純黒開口へ本番C++の描画だけを重ねます。

## SOKKONの操作

| Simulator | 実機相当 | 確認できること |
| --- | --- | --- |
| 黄色 A / `A` | BtnA | MARK送信、ACK、OK/ERROR/TIMEOUT |
| 青 B / `B` | BtnB | mode循環とMODE_NEXT event |
| 画面中央 / `Space` | 中央touch | focus開始・停止と経過時間 |
| Mac connection | USB heartbeat | 接続/未接続、5秒timeout |
| Result outcome | companion処理結果 | `MARK SAVED` / `MAC ERROR` / 応答欠落 |
| Host latency | USB/host遅延 | ACK/RESULT待機中の表示 |
| Context / Detail / Mode | `STATE` frame | Macからの表示文脈 |
| Battery / Charging | 電源HAL | 状態表示 |
| +6s / +30s / +2m / +10m | 仮想`millis()` | 本番定数のhost lost、result timeout、dim、sleep |
| RESET | 再起動 | C++ processとstatic stateの初期化 |

仮想時間はwall clockを待たずに進められます。たとえば`TIMEOUT`を選びMARKしたあと`+30s`を押すと、
本番の`kResultTimeoutMs`を通って`SAVE UNKNOWN`になります。定数自体をsimulator向けに短縮してはいません。

## 99_stopwatchの操作

| Simulator | 実機相当 | 確認できること |
| --- | --- | --- |
| 黄色 A / `A` | BtnA | 計測の開始・一時停止 |
| 青 B / `B` | BtnB | 経過時間を0へ戻し、停止 |
| 画面中央 / `Space` | 中央touch | 計測の開始・一時停止 |
| Battery / Charging | 電源HAL | 500ms周期で読む本番の電源表示 |
| +6s / +30s / +2m / +10m | 仮想`millis()` | 本番loop、経過表示、外周arc、RTCの時間進行 |
| RESET | 再起動 | C++ processと`StopwatchCore`の初期化 |

`99_stopwatch`にMac host protocol、保存結果、mode、dim、sleepはありません。そのため右側パネルでは
Mac連携専用のconnection、outcome、latency、host mode、context、detailを無効化し、時間、電池、充電だけを
操作可能にします。`WAKE`もtouchへ読み替えずno-opです。

## 内部インターフェース

native runnerはstdinで1行のコマンドを受け、stdoutへ1行のNDJSON snapshotを返します。これは
Python process bridge用の内部protocolで、通常はbrowser UIまたはHTTP APIを使います。

```text
SNAPSHOT
ACTION<TAB>MARK|MODE|FOCUS|WAKE
CONFIGURE<TAB>CONNECTED|OUTCOME|LATENCY_MS|CONTEXT|DETAIL|HOST_MODE|BATTERY_PERCENT|CHARGING|TIME_SCALE<TAB>value
ADVANCE<TAB>milliseconds
```

HTTP bridgeは既定でloopbackだけに公開します。APIはsnapshotを直接返すため、画面、scenario、protocol log、
haptic、draw commandを同じrevisionで観測できます。

```bash
curl http://127.0.0.1:8765/healthz
curl http://127.0.0.1:8765/api/state
curl http://127.0.0.1:8765/api/firmwares
curl -H 'Content-Type: application/json' \
  -d '{"firmware":"99_stopwatch"}' \
  http://127.0.0.1:8765/api/firmware
curl -H 'Content-Type: application/json' \
  -d '{"action":"mark"}' http://127.0.0.1:8765/api/action
curl -H 'Content-Type: application/json' \
  -d '{"connected":true,"outcome":"ERROR","latency_ms":400}' \
  http://127.0.0.1:8765/api/scenario
```

`GET /api/firmwares`は固定レジストリの`id` / `label`一覧と現在の`active` IDを返します。
`POST /api/firmware`は本文が`{"firmware":"10_sokkon"}`または
`{"firmware":"99_stopwatch"}`の完全一致だけを受け付け、新しいnative processの起動、firmware ID検証、
最初のsnapshot取得がすべて成功してから切り替えます。失敗時は現在のprocessを維持し、成功時は旧processを
終了します。同じIDを再選択した場合も、編集された本番sourceを再ビルドできるよう新しいcandidateを検証して
入れ替えます。state、action、scenario、切り替えは同じlockで直列化され、入力値からpathやcompiler optionを
組み立てません。

server CLIは`--firmware`、`--host`、`--port`、`--open` / `--no-open`を受け取ります。loopback以外へbindするときは
`--allow-remote`も必要です。このserverに認証やTLSはないため、信頼できないnetworkへ公開しません。

native runnerは生成物なのでSOKKONは`.simulator/sokkon-native`、独立ストップウォッチは
`.simulator/stopwatch-native`へ置かれ、Gitには保存しません。選択した本番`main.cpp` / `board.cpp`、
対応adapter、HAL、runtime、build scriptのどれかが新しくなれば、serverは起動前に再ビルドします。

## 文字の寸法と、セッション再生

`simulator/native/include/font_metrics.hpp`は、実機が使うM5GFXの`Font2`、`FreeSansBold18pt7b`、
`FreeSansBold24pt7b`から**計測値だけ**を取り出した生成ファイルです（グリフのビットマップは複製して
いません）。再生成は`make font-metrics`、CIは`10_sokkon`ビルドジョブで
`scripts/generate-font-metrics.py --check`が陳腐化を検出します。

`simulator/native/include/sim_text.hpp`はLovyanGFXの`text_width`と`draw_string`の幾何をそのまま
移植したものです。固定小数点と切り捨ての位置まで同じにしてあるのは、`10_sokkon`の省略処理が
`textWidth`の値そのもので分岐するからです。近似すると、simulatorだけが自分と整合して実機と
食い違います。

native runnerはdrawStringごとに`layout`（left / top / baseline / width / height / 1文字ごとのpen位置）
を発行します。ブラウザはそのグリッドの上に字形を置くだけなので、折り返し・切れ・はみ出しは実機と
同じ位置で起きます。字形そのものはホストのフォントで、実機のラスタライズとは異なります。

セッションは`scenarios/*.sim`にある行指向のスクリプトです。

```text
CONFIGURE detail BUILDING SOKKON
ACTION focus
ADVANCE 65000
SHOT focus-running
```

再生中は仮想時間が凍結され（protocolの`FREEZE`）、壁時計は進みません。したがって同じスクリプトは
同じフレームを出し、`test_simulator/golden/`のゴールデンが成立します。`make session`は全SHOTを
1枚の`contact-sheet.png`にまとめます。ブラウザ起動は描画より高価なので、セッション1回につき1起動です。

`report.json`のfindingsは幾何的事実だけです。`error`は画面に出ないもの（フレームバッファ外、
丸いパネルの可視円の外、文字同士の重なり、寸法未発行）、`notice`は後から描いた塗りに文字が隠れて
いるもの。トーストのように意図的な遮蔽もここに出るので、判断は人が行います。

## 保証する範囲と実機確認が残る範囲

simulator/CIが直接確認するもの:

- 本番`main.cpp`と`board.cpp`がhost C++ compilerでコンパイルできること
- 実際の`setup()`/`loop()`によるボタン、タッチ、timer、pending/result、protocol parserの挙動
- 本番の描画呼び出し、文字列、座標、色がbrowser frameへ届くこと
- 実機のフォント計測による文字幅と、それに依存する省略・折り返しの分岐
- 各シナリオが描くフレームがゴールデンから動いていないこと
- native process異常、timeout、巨大/不正入力をHTTP bridgeが安全に扱うこと
- browser UIがC++ snapshot以外の画面状態を作らないこと

実機が最終確認になるもの:

- AMOLEDの実グリフ形状のラスタライズ、色味、残像、輝度（送り幅と配置は一致、字形は近似）
- CST820Bの座標精度や指の当たり判定、物理ボタンの感触
- 振動の強さ、モーター波形、スピーカー、電源・充電計測
- USB CDCの実遅延、切断・再接続、ESP32-S3固有の起動とメモリ制約

simulatorは書き込み回数を大幅に減らし、日常の開発と回帰確認を高速化します。ただしHALが代替する電気的・
物理的性質まで保証するものではないため、release候補は最後に実機でも受け入れ確認します。

## 変更時のルール

1. UIやprotocolのロジックはproduction C++だけに書く。
2. 新しく使うM5Unified/Arduino APIがあれば、HALはそのAPIの観測可能な効果だけを実装する。
3. `make simulator-test`でcompiler/native/API/UI parityとゴールデンフレームを、
   `make workbench-test`で共有レンダラーとtransportを確認する。
   画面が変わる変更は`make session SCRIPT=scenarios/<name>.sim`で実際に見る。
4. 重要な触覚・電源・USB変更は実機でも確認し、結果を文書に残す。
