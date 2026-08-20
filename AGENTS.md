# AGENTS.md

このファイルは、このリポジトリを編集する人間およびコーディングエージェント向けの作業規約です。

## 目的

M5Stack StopWatch（C152）のハードウェアを、安全かつ再現可能に調査・開発する。PlatformIO / Arduino を主経路とし、機能ごとの小さなファームウェア、共通コード、Mac companion、ホストテスト、実機手順を保守する。

## 作業前に読むもの

1. `README.md`
2. `docs/HARDWARE.md`
3. `docs/DEVELOPMENT.md`
4. 書き込みを伴う場合は `docs/FLASHING.md`

ハードウェアの事実は `docs/REFERENCES.md` にある M5Stack、Espressif、公式 GitHub の一次資料を優先する。推測、SoC 一般の能力、StopWatch 製品として確認済みの能力を混同しない。

## 開発規約

- PlatformIO の `platformio.ini` を再現可能な開発環境の正本とする。
- アプリ固有コードは `firmware/apps/<番号_名前>/`、共有コードは `firmware/shared/` に置く。
- 新しい機能は、既存の総合アプリへ直書きする前に、単機能の実験環境で確認する。
- メインループでは毎回 `M5.update()` または `c152::update()` を呼ぶ。長い `delay()` や無期限ブロックを避ける。
- シリアル速度は原則 115200 bps。Wi-Fi パスワード、API キー、個人情報をコードやログへ保存しない。
- Mac companionの通常起動はpersistent device bindingを必須とし、実機device IDやbinding fileをcommitしない。
- Mac companionは任意shell commandを実行しない。外部アクションはconfigで名前を明示したmacOS Shortcutだけに限定する。CAPTUREのRESULT OKはMarkdown `fsync`を保証し、Shortcutはlauncher起動時点でprotocol RESULTを返す。workflowの後発結果はTerminal logで扱う。
- Mac simulatorは`firmware/apps/10_sokkon/main.cpp`と`firmware/shared/board.cpp`そのものをホストC++コンパイラでビルドする。画面・入力・protocolの状態機械をPythonやJavaScriptへ複製しない。ファームウェアのUI、タイマー、protocolを変えたらnative simulatorとparity testも同時に確認する。
- native runnerの共通部分（NDJSON、log ring、scenario、wall clock、コマンドループ）は`simulator/native/include/sim_host.hpp`に置く。runnerには1つの本番ファームウェア固有の意味論だけを書く。新しいfirmwareを足すときは`sim_host::Host`を継承し、`FirmwareIdentity`と`screen`ブロックだけを実装する。
- 描画命令(`frame.commands`)の解釈は`simulator/static/frame-renderer.js`だけが行う。従来UI(`simulator/static/app.js`)とWorkbench(`simulator/workbench/src/App.jsx`)はこれをimportする。UI側に2つ目のcanvas解釈を書かない。font familyのような純粋な見た目の差はtypography optionで渡す。
- 文字の寸法は推定しない。`simulator/native/include/font_metrics.hpp`は実機が使うM5GFXから計測した生成物で、手で編集しない。フォントを増減したら`make font-metrics`で再生成する。`textWidth`と`drawString`の幾何は`sim_text.hpp`（LovyanGFXの`text_width`/`draw_string`の移植）だけが持つ。
- 文字位置はnative runnerが`layout`として発行する。UIはそのpen gridに従って1文字ずつ描く。ブラウザのフォント計測でレイアウトを決め直さない。
- 画面の変更を伴う作業は、`scenarios/*.sim`のセッションで確認し、意図した変更なら`make golden-update`でゴールデンを更新して差分をレビューする。ゴールデンを無検査で上書きしない。
- ビルド生成物、`.pio/`、工場 Flash バックアップ、秘密情報をコミットしない。
- ファイル編集は既存のユーザー変更を保持し、依頼範囲外の整形・置換をしない。

## ハードウェア安全規約

- 背面の `BAT` 印字は誤りで、実体は **5V IN**。リチウム電池を接続しない。
- Port A の赤線は 5 V 電源だが、ESP32-S3 の GPIO 信号を 5 V ロジックへ直結しない。
- 防水等級は確認されていない。液体、導電物、金属面での短絡を避ける。
- マイクとスピーカーは同時に有効化しない。録音と再生を明示的に切り替える。
- BMI270 は加速度 + ジャイロのみ。磁気方位、心拍、SpO2、GPS などの値が内蔵されているように表現しない。
- 初回書き込み前に `make device-info` と `make backup` を実施する。Secure Boot / Flash Encryption が有効なら作業を止めて確認する。
- `erase_flash`、eFuse 書き込み、Secure Boot / Flash Encryption の有効化は、明示的な承認なしに実行しない。

## 検証コマンド

変更範囲に応じて、少なくとも次を実行する。

```bash
# 対象だけをビルド
make build ENV=00_smoke

# 全ファームウェアを確認
make build-all

# ハードウェア非依存ロジック
make test

# Mac companionの単体・PTY統合テスト
make companion-test

# 本番SOKKON C++をMac/CI向けHALでコンパイルし、simulatorを統合テスト
make simulator-test

# 共有描画レンダラー、transport、Sites packageのnodeテスト
make workbench-test
```

## 実機なしで画面を確かめる

シミュレータは本番C++をそのまま動かし、文字寸法も実機のフォント計測を使う。したがって画面の判断はここでできる。

```bash
# セッションを再生し、report.jsonと1枚のcontact sheetを書き出す
make session SCRIPT=scenarios/sokkon-face.sim

# ブラウザ無しで、はみ出し・円外・重なり・遮蔽だけを報告させる
make session-report SCRIPT=scenarios/sokkon-host-states.sim
```

出力は`.simulator/sessions/`（gitignore済み）。`contact-sheet.png`を実際に見ること。`report.json`のfindingsは幾何的事実で、`severity: error`（画面に出ない）と`notice`（人が判断する）に分かれる。

セッションの時間は凍結されるので、同じスクリプトは常に同じフレームを出す。ブラウザで触った操作は`python3 -m simulator --record path.sim`でそのままスクリプトになる。

画面の判断が要る変更では、次を守る。

1. まず`scenarios/`に再現スクリプトを書く（無ければ足す）。
2. `make session`で描画結果を見る。推測で直さない。
3. 直したら再度セッションを見て、`make simulator-test`でゴールデン差分を確認する。
4. 意図した変更なら`make golden-update`、意図しない差分ならコードを直す。

実機書き込みは副作用がある。端末、環境名、シリアルポートを確認してから実行する。

```bash
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
```

## 文書化

- 実機でだけ確認した事項は「実機確認」と明記し、公式製品仕様と区別する。
- ピン、電圧、Flash サイズ、書き込み手順を変更するときは一次資料を示す。
- 新しい環境を追加したら README の環境一覧と `docs/DEVELOPMENT.md` を更新する。
- 破壊的・不可逆な操作には、直前に警告と復旧方法を記す。

## ライセンス

このリポジトリは現時点でライセンス未設定。ライセンスが決まるまで、外部コードを安易にコピーせず、必要なら出典・ライセンス互換性を確認する。
