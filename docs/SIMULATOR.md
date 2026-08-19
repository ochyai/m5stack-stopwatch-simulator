# SOKKON Mac Simulator

SOKKON simulatorは、ブラウザ上の見た目だけを模倣するモックではありません。製品ファームウェアの
`firmware/apps/10_sokkon/main.cpp`と`firmware/shared/board.cpp`を、MacまたはLinuxのC++コンパイラで
直接ビルドして実行する **compiler-driven digital twin** です。

```bash
# ビルド、native統合テスト、HTTP/static UIテスト
make simulator-test

# localhostで起動して既定ブラウザを開く
make simulator

# ブラウザを自動で開かず起動
make simulator-serve
```

既定URLは `http://127.0.0.1:8765/` です。外部サービス、CDN、クラウド、実機は使いません。
Apple ClangまたはGCC系のC++ compilerとPython 3だけで動作し、追加のPython packageも不要です。

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
`setup()`と`loop()`、ボタン分岐、タッチ判定、mode循環、focus timer、USB protocol v2、pending queue、
5秒のhost切断、30秒の結果不明、2分のdim、10分のsleep、画面レイアウトは本番C++が実行します。
ブラウザはC++から受け取った`fillScreen`、`drawCircle`、`drawArc`、`drawString`、`fillCircle`、
`fillRoundRect`を466×466 Canvasへ描くだけです。

したがって、ファームウェアの文字列、座標、色、制御フローを変えると、再ビルド後のsimulatorにも
そのまま現れます。Python/JavaScriptにはSOKKONの状態機械を複製しません。

## 筐体のリファレンスとアセット

筐体、円形ベゼル、上側の物理ボタン配置は、M5Stackの
[StopWatch C152公式資料](https://docs.m5stack.com/en/core/StopWatch)にある正面・上面・側面写真を
基準にしています。画面を正立させたとき、操作ボタンはストップウォッチらしく上側に置き、黄色Aは
左上、青Bは右上です。クリック領域も見えているボタンへ重ねています。

`simulator/static/device-shell.png`は公式写真そのものを収録したものではなく、2026-08-19に画像生成で
作成したこのsimulator固有のアセットです。最終編集では「右の青ボタンと筐体を維持し、左の黄色ボタン
だけをC152の上面リファレンスに沿って上へ寄せ、小型の矩形ボタンにする。表示開口は純黒で、文字、
ロゴ、追加ボタン、端子を入れない」と指定しました。Canvasはその純黒開口へ本番C++の描画だけを重ねます。

## 操作

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
curl -H 'Content-Type: application/json' \
  -d '{"action":"mark"}' http://127.0.0.1:8765/api/action
curl -H 'Content-Type: application/json' \
  -d '{"connected":true,"outcome":"ERROR","latency_ms":400}' \
  http://127.0.0.1:8765/api/scenario
```

server CLIは`--host`、`--port`、`--open` / `--no-open`を受け取ります。loopback以外へbindするときは
`--allow-remote`も必要です。このserverに認証やTLSはないため、信頼できないnetworkへ公開しません。

native runnerは生成物なので`.simulator/sokkon-native`へ置かれ、Gitには保存しません。本番
`main.cpp` / `board.cpp`、HAL、runtime、build scriptのどれかが新しくなれば、serverは起動前に
再ビルドします。

## 保証する範囲と実機確認が残る範囲

simulator/CIが直接確認するもの:

- 本番`main.cpp`と`board.cpp`がhost C++ compilerでコンパイルできること
- 実際の`setup()`/`loop()`によるボタン、タッチ、timer、pending/result、protocol parserの挙動
- 本番の描画呼び出し、文字列、座標、色がbrowser frameへ届くこと
- native process異常、timeout、巨大/不正入力をHTTP bridgeが安全に扱うこと
- browser UIがC++ snapshot以外の画面状態を作らないこと

実機が最終確認になるもの:

- AMOLEDの実フォントラスタライズ、色味、残像、輝度
- CST820Bの座標精度や指の当たり判定、物理ボタンの感触
- 振動の強さ、モーター波形、スピーカー、電源・充電計測
- USB CDCの実遅延、切断・再接続、ESP32-S3固有の起動とメモリ制約

simulatorは書き込み回数を大幅に減らし、日常の開発と回帰確認を高速化します。ただしHALが代替する電気的・
物理的性質まで保証するものではないため、release候補は最後に実機でも受け入れ確認します。

## 変更時のルール

1. UIやprotocolのロジックはproduction C++だけに書く。
2. 新しく使うM5Unified/Arduino APIがあれば、HALはそのAPIの観測可能な効果だけを実装する。
3. `make simulator-test`でcompiler/native/API/UI parityを確認する。
4. 重要な触覚・電源・USB変更は実機でも確認し、結果を文書に残す。
