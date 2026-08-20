<div align="center">

# M5Stack StopWatch Simulator

[日本語](README.md) · [English](README.en.md) · **中文**

把量产固件的 C++ 原样跑在 Mac 上的模拟器。<br>
文字尺寸取自真机字体的实测值，因此关于画面的判断可以在这里完成。

[![CI](https://github.com/ochyai/m5stack-stopwatch-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/ochyai/m5stack-stopwatch-simulator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)](macos/M5StackSimulator/README.md)

<img src="docs/images/workbench.png" alt="Firmware Workbench：左侧是固件列表与构建，中间是真机画面，右侧是输入与传感器 Inspector，下方是事件时间线" width="900">

</div>

这是一个用于在 Mac 上以可复现的方式研究和开发 M5Stack StopWatch（C152）的仓库。圆形 AMOLED、触摸、两个按键、六轴 IMU、RTC、麦克风、扬声器、振动、Wi-Fi / Bluetooth LE 与外部 I2C，都由按功能拆分的固件和同一个模拟器覆盖。默认应用 **SOKKON / 即今** 把这块圆形设备变成一个用实体承托当下情境的界面。

> [!CAUTION]
> 部分批次背面端子的 `BAT` 丝印是错的，实际是外部供电用的 **5V IN**。请不要接锂电池。这是 M5Stack 官方的更正事项。

## 与普通模拟器的区别

- **不是模型。** 浏览器里显示的，是用主机 C++ 编译器构建并运行量产 `main.cpp` 与 `board.cpp` 的结果。没有把 UI 状态机在 JavaScript 里重写一遍。
- **不估算字宽。** `font_metrics.hpp` 由固件实际链接的 M5GFX 生成，`sim_text.hpp` 则把 LovyanGFX 的 `text_width` 与 `draw_string` 连定点运算一并移植。`10_sokkon` 那段「用 `...` 收缩到 300 px 以内」的逻辑，现在会在与真机相同的位置截断。
- **绘制指令只有一份解释器。** 两个前端都 import `frame-renderer.js`，所以像素不会因为你打开的是哪个界面而改变。
- **触摸带坐标。** 点击画面任意位置，该设备坐标都会送进量产 `loop()`。因此可以直接验证「中心半径 145 px 之外不响应」这一真机判定。
- **可以精确重放。** 重放期间虚拟时间被冻结，同一份脚本在任何机器上都画出同样的帧。golden frame 因此才能成立。

## 30 秒跑起来

不需要真机，只需要 Python 3 和一个 C++ 编译器。

```bash
# 编译量产 C++，在 localhost 启动并打开浏览器
make simulator

# 另一份量产代码：A / 触摸开始与暂停，B 复位
make simulator FIRMWARE=99_stopwatch

# native runner、进程桥、golden frame 与 UI 的回归测试
make simulator-test
```

<img src="docs/images/simulator-ui.png" alt="浏览器版模拟器：左侧是圆形设备，右侧是场景控制与协议日志" width="820">

另外还有三栏式桌面版 Workbench，以及既不需要 Python 也不需要 localhost 服务的 macOS 应用。

```bash
make workbench-install     # 仅首次
make workbench             # 固件切换、Inspector、事件时间线
make macos-app             # 自包含的 M5Stack Simulator.app
```

## 没有真机也能确认画面

`scenarios/*.sim` 是重放脚本，只用界面本身会发送的那些命令写成：按键、触摸坐标、虚拟时间、场景、SHOT。

```text
# scenarios/sokkon-touch-ring.sim
TOUCH 233 60      # 环外，固件应当忽略
SHOT outside-ring
TOUCH 233 233     # 正中心，FOCUS 计时开始
ADVANCE 3000
SHOT inside-ring
```

```bash
make session SCRIPT=scenarios/sokkon-face.sim
```

<img src="docs/images/session-contact-sheet.png" alt="一次运行拍下的五张设备画面拼成的一张样片" width="900">

`.simulator/sessions/` 会得到 `report.json`，以及把全部 SHOT 排在一起的 `contact-sheet.png`。启动浏览器的开销远大于绘制本身，所以一次会话只启动一次。

`report.json` 里的 findings 是几何事实，不是偏好。

| severity | 含义 |
| --- | --- |
| `error` | 超出 466 × 466 画面缓冲、落在**圆形** AMOLED 可视圆之外、两段文字互相重叠、未发布尺寸 |
| `notice` | 文字被之后绘制的填充盖住（例如 toast，需要人来判断） |

`test_simulator/golden/` 固定了每个场景实际绘制的帧，因此非预期的布局变化会让测试失败。若是有意的改动，执行 `make golden-update` 更新，并在提交前审阅差异。在浏览器里做的操作可以用 `python3 -m simulator --record path.sim` 直接记录成可重放的脚本。

传感器走同一条路径。下面三张图改变了倾斜角，显示的正是 `99_stopwatch` 实际读到的加速度。

<img src="docs/images/session-stopwatch-tilt.png" alt="三种倾斜下的画面，IMU 读数依次为 X+0.12 Y-0.08、X+0.60 Y-0.30、X-0.75 Y+0.40" width="900">

## 原理

```text
firmware/apps/10_sokkon/main.cpp ─┐
firmware/shared/board.cpp ─────────┼─ host C++ compiler ─ native runner
Arduino / M5Unified / ESP32 HAL ───┘                         │
                                                            ├─ framebuffer draw commands
browser canvas ◀─ localhost HTTP API ◀─ Python process bridge┼─ protocol / haptic log
                                                            └─ screen / pending state
```

`simulator/native/include/` 下的薄 HAL 只替换真机的 Arduino、M5Unified 与 ESP32 API。`setup()` 与 `loop()`、按键分支、触摸判定、mode 循环、focus timer、USB protocol v2、pending queue、5 秒主机断开、30 秒结果未知、2 分钟变暗、10 分钟休眠以及画面布局，全部由量产 C++ 执行。

native runner 的共通部分（NDJSON、log ring、场景、时间倍率、命令循环）位于 `sim_host.hpp`，每个 runner 只保留某一份量产固件特有的语义。要加第三份固件，继承 `sim_host::Host` 并写出 `FirmwareIdentity` 与 `screen` 块即可。

详见 [Mac Simulator](docs/SIMULATOR.md)。

## 在真机上使用 — SOKKON / 即今

用 USB Type-C 连接 Mac，启动仅依赖标准库的 companion。companion 本身不进行任何网络通信，只把最前台的应用名作为当下情境显示在设备上。默认保存位置 `Documents` 可能会因 macOS / iCloud 设置而被系统同步。

```bash
# 仅首次：先备份出厂 Flash，再写入 SOKKON
make build ENV=10_sokkon
make flash ENV=10_sokkon PORT=/dev/cu.usbmodemXXXX

# 仅首次：把物理连接中的 device ID 与这台 Mac 配对
make companion-pair ARGS="--port /dev/cu.usbmodemXXXX"

# 配对后的日常使用
make companion
```

| 操作 | 结果 |
| --- | --- |
| 黄色 A | 把当前时间、mode、前台应用与 focus 时长 MARK 进 `~/Documents/Sokkon Inbox.md` |
| 蓝色 B | 循环切换 `NOW → BUILD → READ → MEET → PRESENT → REST` |
| 画面中心 | 开始 / 暂停 FOCUS 计时 |

只有当 Mac 完成 Markdown 的 `fsync` 之后，MARK 才会返回强确认振动。未连接与明确的保存失败都算「未保存」；但若 30 秒内没有任何响应，设备显示 `SAVE UNKNOWN`，因为有可能只是保存后的回复丢失了。不执行任意 shell，额外动作仅限在 JSON 配置中明确写出名称的 macOS Shortcut。设计、USB protocol v2 与隐私边界见 [SOKKON 设计](docs/SOKKON.md)。

## 最初的 10 分钟（真机）

请使用支持数据传输的 USB Type-C 线。**在第一次写入之前，先备份出厂固件。**

```bash
# 让设备进入下载模式，并使用打印出的端口
./scripts/detect-port.sh
make device-info PORT=/dev/cu.usbmodemXXXX
make backup PORT=/dev/cu.usbmodemXXXX

# 构建并写入最小诊断固件
make build ENV=00_smoke
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
```

下载模式：连接 USB 后长按电源键约 2 秒，看到内部绿色 LED 亮起后松开。详见 [写入与恢复步骤](docs/FLASHING.md)。

## 硬件

| 项目 | 内容 |
| --- | --- |
| MCU | ESP32-S3R8，双核 LX7，最高 240 MHz |
| 内存 | 16 MB Flash，8 MB PSRAM |
| 屏幕 | 1.75 英寸，466 × 466，圆形 AMOLED（CO5300） |
| 输入 | CST820B 触摸、两个可编程按键、电源键 |
| 运动 | BMI270（三轴加速度 + 三轴陀螺仪，无磁力计） |
| 音频 | MEMS 麦克风、ES8311 Codec、1 W / 8 Ω 扬声器 |
| 其他 | RX8130CE RTC、振动马达、M5PM1 电源管理、450 mAh 电池 |
| 无线 | 2.4 GHz Wi-Fi。Bluetooth LE 仅从芯片信息确认为 ESP32-S3 的 SoC 能力，本产品上的 GATT 实际行为未验证 |
| 扩展 | Port A（G10 / G11）与背面 2.54 mm 扩展总线 |

不内置心率、SpO2、GPS/GNSS、环境传感器、摄像头与 microSD。官方规格未确认防水等级，请按不可沾水来对待。详见 [硬件信息](docs/HARDWARE.md)。

## 固件环境

| PlatformIO 环境 | 验证内容 |
| --- | --- |
| `00_smoke` | 板级、屏幕与输入的最小启动确认 |
| `01_display_input` | AMOLED、触摸、两个按键 |
| `02_imu` | BMI270 加速度与陀螺仪 |
| `03_rtc_power` | RTC、电池、电源信息 |
| `04_audio_haptics` | 麦克风、扬声器、振动 |
| `05_wifi_scan` | 2.4 GHz Wi-Fi 扫描 |
| `07_ble_gatt` | Bluetooth LE GATT |
| `08_external_i2c` | Port A 的 I2C 扫描 |
| `10_sokkon` | 与 Mac 联动的即今界面（默认） |
| `99_stopwatch` | 秒表本体 |
| `native` | 主机侧的逻辑单元测试 |

## 命令

| 命令 | 说明 |
| --- | --- |
| `make simulator` | 编译量产 C++ 并打开浏览器版模拟器 |
| `make workbench` | 启动三栏式 Firmware Workbench |
| `make session SCRIPT=…` | 重放会话，输出 `report.json` 与样片 |
| `make session-report SCRIPT=…` | 不启动浏览器，只报告画面上显示不出来的绘制 |
| `make golden-update` | 有意改动布局后更新 golden frame |
| `make font-metrics` | 重新生成真机字体的实测值 |
| `make simulator-test` | native runner、桥接、golden frame 与 UI 的回归测试 |
| `make workbench-test` | 共享渲染器、transport 与 Sites package 的测试 |
| `make companion-test` | Mac companion 的单元与 PTY 集成测试 |
| `make build-all` / `make test` | 构建全部固件 / 运行与设备无关的逻辑测试 |
| `make macos-app` / `make macos-dmg` | 自包含的 .app / 本地 DMG |
| `make backup` / `make flash` / `make monitor` | 真机的备份、写入与串口 |

## 分发

`M5Stack Simulator.app` 自包含 Workbench、Swift 类型化桥接以及两个 native runner。要签名分发，按以下顺序：

```bash
# 用 Developer ID Application 证书签名并生成 DMG
make macos-release IDENTITY="Developer ID Application: NAME (TEAMID)"

# 仅需一次，把凭据保存到钥匙串（这条命令请自己执行）
#   xcrun notarytool store-credentials m5stack-simulator --apple-id ... --team-id ... --password ...
make macos-notarize PROFILE=m5stack-simulator
```

`macos-notarize` 先对 app 做公证并 staple，再用这个已 staple 的 app 重新生成 DMG，然后对 DMG 做公证。贴在 DMG 上的 ticket 不会跟着被拖出来的 app 走，所以顺序反了会导致离线首次启动被 Gatekeeper 拦下。脚本最后还会按下载后的状态（带 quarantine 属性）确认判定结果。

只用 `make macos-dmg` 生成的 DMG 是 ad-hoc 签名，在别人的 Mac 上会被 Gatekeeper 拦下。信任边界见 [macOS app](macos/M5StackSimulator/README.md)。

## 仓库结构

```text
firmware/apps/          按功能拆分的固件
firmware/shared/        共通的板级初始化与逻辑
simulator/native/       运行量产 C++ 的 native HAL 与共享 host framework 上的 runner
simulator/static/       浏览器 UI 与两个界面共享的渲染器
simulator/workbench/    三栏式 Firmware Workbench（React）
scenarios/              可重放的会话脚本
test_simulator/golden/  各场景实际绘制帧的基准
companion/              无额外依赖的 macOS USB companion
macos/                  自包含 M5Stack Simulator.app 与 DMG 的构建定义
scripts/                构建、字体实测、端口检测、备份、写入
docs/                   硬件、开发、模拟器、恢复与参考资料
platformio.ini          固定的构建环境与依赖库
```

## 文档

- [Mac Simulator 的原理与保证范围](docs/SIMULATOR.md)
- [SOKKON 设计与 USB protocol v2](docs/SOKKON.md)
- [开发环境与编码流程](docs/DEVELOPMENT.md)
- [写入、备份与出厂固件恢复](docs/FLASHING.md)
- [硬件信息](docs/HARDWARE.md) / [项目构想](docs/PROJECT_IDEAS.md) / [官方一手资料](docs/REFERENCES.md)
- [面向 agent 的工作约定](AGENTS.md)

`docs/` 下的文档大多以日语写成。

## 许可证

MIT License（见 [LICENSE](LICENSE)）。依赖库以及生成的字体实测值的出处记录在 [NOTICE.md](NOTICE.md)。本仓库不复制任何字形位图。
