# 最小可运行骨架 · 五步跑起来

> 这套骨架是**能跑的最小版本**，不是示例片段。每一步都有「你应该看到什么」，
> 看不到就是没成，别往下走。

你需要：**Windows + Node**（其它系统看文末）。

---

## 第 1 步 · 看它能不能知道你还在不在

```powershell
# 在这个目录里执行
powershell -NoProfile -ExecutionPolicy Bypass -File .\_sense.ps1 -Out $env:TEMP\s.json
Get-Content $env:TEMP\s.json -Raw
```

**你应该看到**类似：
```json
{"ok":true,"idleSec":3.4,"proc":"chrome","title":"...","activity":"browse","at":1790...}
```

- 动一下鼠标再跑一次，`idleSec` 应该归零 → 说明它真的在读系统空闲时间。
- ⚠️ **如果你在控制台里看到中文标题是乱码**：那是**控制台显示**的问题（PowerShell 5.1 用 ANSI 显示 UTF-8 文件），**文件本身没坏**。用浏览器或 VS Code 打开就是好的。这一点本项目实测确认过。
- 如果报 `Add-Type` 相关错误：你的 PowerShell 执行策略太严，加 `-ExecutionPolicy Bypass`。

**改它**：`_sense.ps1` 里的 `$map` 是活动分类表，把你常用的软件名（小写）加进去。

---

## 第 2 步 · 起服务

```powershell
$env:PORT = "8765"; node sense-server.js
```

**你应该看到**：`[companion] listening on http://127.0.0.1:8765`

另开一个窗口验证：

```powershell
(Invoke-WebRequest http://127.0.0.1:8765/sense -UseBasicParsing).Content
```

**你应该看到**：和第 1 步一样的 JSON，而且**中文标题不乱码**（服务端显式声明了 `charset=utf-8`）。

---

## 第 3 步 · 看壁纸页

浏览器打开 <http://127.0.0.1:8765/>

**你应该看到**：一个呼吸的绿球、底部三个数字（键鼠空闲秒数 / 你在干什么 / 前台程序）、下方一排键帽。

- **30 秒不动键鼠** → 画面变暗（进入 idle）
- **5 分钟不动** → 更暗、动画停住（进入 away）——这是护屏，不是卡住了
- 动一下鼠标 → 自动回到 active，并且说一句「你回来啦」

> 这个页面就是你的壁纸本体。要装成真壁纸：装 [Lively Wallpaper](https://rocksdanister.github.io/lively/) →
> 「添加壁纸 → 浏览」→ 选这个 `wallpaper.html`。
> **注意**：文件改了要**同步到壁纸库副本**再重启 Lively 才生效——源码目录改了不等于壁纸变了。

---

## 第 4 步 · 让它跟着你打字

```powershell
# 另开一个窗口（保持运行）
powershell -NoProfile -ExecutionPolicy Bypass -File .\_keywatch.ps1
```

**你应该看到**：回到壁纸页，**敲键盘时下面的键帽会亮**。

延迟应该是**几十毫秒**（本项目实测：从按下到壁纸收到推送 11–90ms）。

**隐私说明（这是设计，别"优化"掉）**：
- 它只上报**虚拟键码**，不解析成字符，所以你打了什么**还原不出来**；
- 不记录 Shift / CapsLock 状态；
- **一个字都不落盘**。

想自己确认？跑起来后敲几下键盘，然后看这个目录：
```powershell
Get-ChildItem . -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```
**不应该有任何新建或变大的文件。**（本项目当初就是这么验证的：连发三批键码，日志文件字节数纹丝不动。）

---

## 第 5 步 · 让它自己活着

先**手动**跑一次看效果：

```powershell
$env:COMPANION_PORT = "8765"; powershell -NoProfile -ExecutionPolicy Bypass -File .\_watchdog.ps1
Get-Content .\_watchdog.log
```

**你应该看到**：如果服务/监听都在跑，日志**不新增任何行**（它只在需要修复时才说话）。

然后**故意杀掉服务**（关掉第 2 步的窗口），再跑一次看门狗 → 日志应该出现 `server restarted`，服务自己回来了。

挂成定时任务（每 10 分钟一次，**不闪黑框**）：

```powershell
schtasks /create /tn "MyCompanionWatchdog" /sc minute /mo 10 /tr "wscript.exe \"%~dp0_watchdog.vbs\"" /f
```
> 上面 `%~dp0` 在 PowerShell 里不展开，请把路径**换成这个目录的真实绝对路径**。
> 用 `wscript` 起是为了隐藏窗口——直接跑 `powershell.exe` 会每 10 分钟闪一次黑框。

开机自启：把 `autostart.bat` 的快捷方式丢进
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`，或者注册到
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`。

---

## 壁纸显示「–」怎么办：打开自检页

浏览器打开 <http://127.0.0.1:8765/_probe.html>

它会分别检测 `/sense` 与 `/keys` 两环，并给出结论：

```
/sense   正常 · 空闲 58 秒 · electron（other）
/keys    正常 · 已收到 1 个键码
结论     两环都通 —— 若壁纸仍显示「–」，问题在壁纸页本身（打开浏览器控制台看报错）
```

- **`/sense` 连不上** → `node sense-server.js` 没在跑，或端口不对
- **`/sense` 报 `sense-timeout`** → `_sense.ps1` 跑不起来：手动执行它看报错（见第 1 步）
- **`/keys` 正常但键帽不亮** → `_keywatch.ps1` 没在跑
- **两环都通但壁纸还是「–」** → 问题在壁纸页，按 F12 看控制台

> 这一页**故意用一个不可能匹配的游标**（`?since=999999`），所以服务端会立刻回答、
> 不会挂 25 秒长轮询——这也是为什么它比直接在壁纸页上排查好用。

---

## 踩过的坑（都实测过，不是理论）

| 现象 | 真因 | 怎么办 |
|---|---|---|
| 控制台里中文乱码 | PS 5.1 用 ANSI 显示 UTF-8 文件 | **只是显示问题**，用编辑器/浏览器看是好的 |
| `.ps1` 改完中文全乱 | 编辑工具把 **BOM 丢了**，PS 5.1 按 GBK 读 | 这几个骨架**故意全用 ASCII**，你也别往里写中文 |
| `.bat` 里写中文路径，自启失效**且无报错** | cmd 按 GBK 读 UTF-8 的 bat | bat 只写 ASCII；中文路径改成 ASCII 启动器 |
| 看门狗**每次运行都多起一个** keywatch | 用进程名/`tasklist` 判断"在不在"，**永远为真** | 骨架已改用 **PID 文件** |
| 看门狗还是每次多起一个 | 用 WMI/CIM 查命令行，**权限不足时静默返回空** | 同上，PID 文件不依赖任何特权接口 |
| 服务"看起来没在跑"，又起了一个 | `Get-NetTCPConnection` 权限不足时**返回空**而非报错 | 骨架用**原始 TCP 连接**探测端口 |
| `node` 起子进程报 `EPERM` | 某些受限环境禁止**管道 stdio** | 骨架的做法：子进程**自己写文件**，父进程轮询文件 |
| 看门狗误杀了别的程序的进程 | 判据 `*_keywatch.ps1*` 会匹配**任何**同名脚本 | 骨架已改成**匹配本目录的完整路径** |
| git push 一直失败 | 直连被重置 / 代理没跑 / SSH 被策略挡 | 见 `references/7-发布与脱敏.md` 的 `gh api` 方案 |

---

## 关于"两份副本"

**同一个项目不要跑两份。** 本项目真栽过：改了源码目录，屏幕上是旧目录里的另一份副本，
查了很久才发现。判断依据永远是**进程的实际命令行**，不是"我改的文件"：

```powershell
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  Where-Object { $_.CommandLine -like "*_keywatch*" } |
  Select-Object ProcessId, CommandLine
```

---

## 其它系统（macOS / Linux）

`sense-server.js`、`wallpaper.html`、`/keys` 长轮询这三块**不用改**。要换的只有取数那一段：

| 要拿什么 | macOS | Linux |
|---|---|---|
| 空闲秒数 | `CGEventSourceSecondsSinceLastEventType` | `xprintidle` |
| 前台程序 | `NSWorkspace.frontmostApplication` | `xdotool getactivewindow` |
| 键盘事件 | `CGEventTap`（**需要辅助功能授权**） | `xinput` / `evdev`（**需要权限**） |

把 `_sense.ps1` 换成对应实现、让它照样**把 JSON 写进 `-Out` 指定的文件**，其余全部通用。

> **注意**：macOS 的键盘监听必须走辅助功能授权，而且授权弹窗**必须由用户本人点**。
> 这比 Windows 的门槛高，值得先跟用户说清楚。
