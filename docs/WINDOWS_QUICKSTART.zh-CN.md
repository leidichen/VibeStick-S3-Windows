# Windows 快速上手

[English](WINDOWS_QUICKSTART.md) · [这个 fork 改了什么](FORK_CHANGES.zh-CN.md)

从一份全新克隆到"按住蓝色键说话,文字出现在你正在输入的窗口里"。上游的指南(`docs/USAGE.zh-CN.md`)是按 macOS 写的;
这一份面向 Windows 10/11,只在一台 Windows 10 电脑上核对过——哪一步和你的机器对不上,欢迎提 issue。

**为什么必须自己编译固件:** 你的 Wi-Fi 名称和密码、电脑的地址、共享 token 都是编译进固件的(`vibe_stick_secrets.h`),
没有一份通用的预编译固件可以下载。

## 需要准备

| | |
|---|---|
| M5Stack **StickS3** + 一根 USB-C **数据线** | 只能充电的线识别不到设备 |
| **2.4 GHz** Wi-Fi | ESP32-S3 连不上 5 GHz。把双频合并成同一个名字的路由器通常没问题 |
| 同一**局域网**里的 Windows 10/11 电脑 | 电脑和设备要能互相访问(不能开"客户端隔离",见末尾) |
| 给 bridge 用的 Python **3.11+** | `py -3 --version` |
| Git,以及约 3 GB 磁盘装 ESP-IDF | |
| 语音识别 | 云端 API Key(默认是 [SiliconFlow](https://cloud.siliconflow.cn))**或**离线模型([FORK_CHANGES §5](FORK_CHANGES.zh-CN.md#5-语音输入)) |

## 1. 取代码,建两个私有文件

```powershell
git clone <本仓库地址> VibeStick
cd VibeStick
Copy-Item firmware\sticks3\include\vibe_stick_secrets.example.h firmware\sticks3\include\vibe_stick_secrets.h
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"      # 你的 token:复制输出
ipconfig                                                       # 记下这台电脑在 Wi-Fi/局域网网卡上的 IPv4 地址
```

这两个新文件都被 git 忽略了。不要提交,也不要发给别人。

编辑 `firmware\sticks3\include\vibe_stick_secrets.h`:

```c
#define VIBE_STICK_WIFI_SSID "你的 2.4 GHz 网络名"
#define VIBE_STICK_WIFI_PASSWORD "它的密码"
#define VIBE_STICK_BRIDGE_HOST "192.168.1.23"      // 这台电脑的 IPv4 地址
#define VIBE_STICK_BRIDGE_PORT 8765
#define VIBE_STICK_BRIDGE_TOKEN "刚才生成的 token"
```

编辑 `.env`(至少这些;token 要和上面**一模一样**):

```ini
VIBE_STICK_BRIDGE_TOKEN=刚才生成的 token
VIBE_STICK_RECORDING_USE_MAC_MIC=0        # Windows 上必须设为 0
VIBE_STICK_ASR_API_KEY=你的 SiliconFlow Key   # 或者改用本地识别
VIBE_STICK_COMPUTER_NAME=MyPC             # 显示在设备上(只能用英文/数字)
```

## 2. 安装 ESP-IDF 5.5(只做一次)

```powershell
git clone -b v5.5.1 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git C:\esp\esp-idf
cd C:\esp\esp-idf
# 可选:如果访问 github.com 下载很慢或被拦,可以先设置:
# $env:IDF_GITHUB_ASSETS = 'dl.espressif.cn/github_assets'
.\install.ps1 esp32s3
```

安装器会用 `PATH` 里排在最前面的 Python 建自己的环境。我们用的是 **Python 3.12**(没有试过 3.14);如果安装时抱怨你的 Python,
把 3.12 / 3.13 放到 `PATH` 最前面。

## 3. 编译并刷入

每次新开 PowerShell,先加载环境:

```powershell
. C:\esp\esp-idf\export.ps1
cd <你的克隆目录>\firmware\sticks3
idf.py build                       # 第一次会下载组件,需要联网
```

插上 StickS3,在设备管理器 → *端口* 里找到它的串口("USB 串行设备 (COMx)" / "USB JTAG/serial debug unit"),然后:

```powershell
idf.py -p COM4 flash
```

- 通常工具会自己让芯片进入下载模式。如果卡在 `Connecting...`,按住电源键直到蓝灯双闪、屏幕变暗,再重新执行命令。
- 刷完后拔掉重插(或按一下电源键)。首页会出现;bridge 没运行之前显示"离线"。
- 以后改 Wi-Fi、地址或 token,都要重新编译、重新刷入。

## 4. 安装并运行 bridge

在仓库根目录(含 `.env` 的那一层;bridge 从当前目录读取 `.env`):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install .\bridge
# 离线识别(可选):.\.venv\Scripts\python -m pip install "./bridge[local-asr]"
.\.venv\Scripts\python -m vibe_stick --host 0.0.0.0 --port 8765
```

它会打印 `VibeStick Bridge listening on http://0.0.0.0:8765` 和设备的请求。窗口保持打开。

### 放行 Windows 防火墙

第一次运行可能会弹出放行提示;没有弹,或者设备一直离线,就在**管理员** PowerShell 里加规则(把网段换成你自己的,比如
`192.168.1.0/24`):

```powershell
New-NetFirewallRule -DisplayName "VibeStick TCP 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Any -RemoteAddress 192.168.1.0/24
New-NetFirewallRule -DisplayName "VibeStick UDP 8766" -Direction Inbound -Protocol UDP -LocalPort 8766 -Action Allow -Profile Any -RemoteAddress 192.168.1.0/24
```

我们踩过的坑:*公用*网络配置上残留的 `python.exe` **阻止**规则(以前某次防火墙弹窗点了"取消"留下的)优先级高于所有放行规则。
用 `Get-NetFirewallRule -Direction Inbound | ? DisplayName -eq 'python.exe' | select DisplayName,Profile,Action,Enabled`
列出来,把阻止的那条禁用。

不用设备就能做的快速检查:在同一个 Wi-Fi 的手机浏览器里打开 `http://<这台电脑的IP>:8765/health`。手机打不开,设备也一定连不上。

## 5. 试一下

1. 设备屏幕大约 10 秒内应该从"离线"变成正常状态。
2. 点进任意文本框,**按住蓝色键**,等两声提示音,说话,松开。
3. 文字会被粘贴进去。bridge 窗口里的 `timing …` 一行会显示时间花在哪里。

按键、电池行为,以及其它与上游的不同之处,见 [FORK_CHANGES.zh-CN.md](FORK_CHANGES.zh-CN.md)。

## 6. 后台运行

- 上游的 `scripts\install_windows.ps1` 会建一个隐藏的当前用户计划任务,并在 `%APPDATA%\VibeStick` 下建 venv(而且**每次运行都会把仓库里的
  `.env` 覆盖到 `%APPDATA%\VibeStick\.env`**)。在这个 fork 作者的电脑上这些任务启动不起来(错误 `0x80070002`),原因没查清;你的机器上可能没问题。
- 如果不行:就让 bridge 留在一个终端里,或者用启动文件夹快捷方式 / 计划任务运行
  `pythonw.exe -m vibe_stick --host 0.0.0.0 --port 8765`,"起始于"设为含 `.env` 的文件夹(我们没有测过)。
- 记住:电脑睡眠,设备就断连。

## 排错

| 现象 | 检查 |
|---|---|
| 设备一直"离线" | 电脑 IP 变了吗?(`ipconfig`,给它固定 IP)· 防火墙规则 / `python.exe` 阻止规则 · 上面的手机测试 · 是否 2.4 GHz · 路由器的"AP / 客户端隔离"或访客网络 · 有些网络对 ESP32 设备不支持纯 WPA3(未验证) |
| 刷机卡在 `Connecting...` | 是数据线吗?进下载模式(电源键,蓝灯双闪)· 是否有别的程序占着这个 COM 口 |
| 说话后没有文字 | bridge 窗口里的 `local ASR …` / `recording stop result …` 行 · `VIBE_STICK_RECORDING_USE_MAC_MIC=0` · API Key · 光标是否在文本框里 |
| 额度显示 `--%` 或 `Upd 15h ago` | Claude Code 登录过期 → [FORK_CHANGES §6](FORK_CHANGES.zh-CN.md#6-claude-额度数据新旧与登录自动续期) |
| 改了 `.env` 没效果 | bridge **先**读 `%APPDATA%\VibeStick\.env`,再读 `.\.env`;删掉那份旧副本 |
| 电脑睡眠后设备不见了 | 正常;唤醒电脑后会重新连上(IP 变了就长按右侧键重新搜索) |
