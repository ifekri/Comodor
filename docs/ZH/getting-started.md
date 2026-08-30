# 快速上手

五分钟，结束时智能体会做成一件有用的事。

---

## 1. 安装

一行命令。剩下的交给它。

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**一个地址，两者通用。** `get.comodor.ai` 不指定任何文件。它会识别请求方是谁：把 `curl` 和 `wget` 引向 shell 安装脚本，把 PowerShell 引向 Windows 安装脚本，把浏览器引向本页面——因此你在每个系统上粘贴的都是同一行命令，无需自行挑选。

**它会善始善终。** 从网页上照抄一行命令的人并没有答应去调试任何东西，所以脚本会自行安装所需的一切——隔离环境、包管理器、Python——而不是停下来解释你本该提前准备什么。已在完全没有 Python 的纯净 `debian:bookworm-slim` 上验证通过。

### 之后几乎无需手动输入

在可能的情况下，它会把 `comodor` 放到你的 shell 已经在查找的位置，因此它在你运行命令的终端里直接可用——无需 `export`，无需新开窗口。这涵盖了 root、容器、CI，以及任何装有 Homebrew 的 Mac。

在无法做到的地方——普通 Linux 账户，`PATH` 上没有任何可写目录——任何安装器都无能为力，因为子进程无法修改启动它的 shell 的环境。所以它会明说：

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

新开一个终端，它就能直接使用。这一行会同时写入你的 shell rc 文件和登录配置文件，因此任何类型的 shell 都能找到它——交互式、登录式、非交互式，以及桌面会话。

### 如果你不愿把脚本直接管道给 shell

完全可以理解。两个脚本都是可以先阅读的纯文本——这里用完整文件名，因为短地址会把所有非抓取工具的请求都引到页面上：

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

或者使用你已有的包管理器：

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor 只需要 **Python 3.11 或更新版本**，此外别无要求。

### 确认它已就位

```bash
comodor --version
```

如果 shell 找不到它，说明安装器向你的 `PATH` 添加了一个当前终端尚未感知的目录。新开一个终端，或者运行安装器打印的那行 `export` 命令。

### 安装器支持的选项

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | 指定安装方式：`uv`、`pipx`、`venv` 或 `pip` |
| `COMODOR_NO_BOOTSTRAP` | 绝不下载工具；改为直接失败 |
| `COMODOR_NO_MODIFY_PATH` | 不改动你的 shell 配置文件 |
| `COMODOR_INSTALL_REF` | 从 git ref 或本地路径安装，而不是从 PyPI |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **还想先试用？** `comodor --demo` 会在一个脚本化的离线提供商之上运行完整界面。无需密钥、无需账户、无需联网。

---

## 2. 选择模型

运行它。第一次它会问六个问题，之后绝不再问。

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

方向键选择，或者输入文字过滤。**Tab** 会在同一帧内展开当前光标所在项的完整描述——列表每行只显示一行文字以适应屏幕，而有些描述足有一段话。

通过管道或脚本运行时，同样的问题会以编号列表的形式出现，因此可以自动化处理。

**没有密钥也不想花钱？** 选择 **Ollama** 或 **LM Studio**。它们在你的机器上运行，无需密钥，分文不花。除明确说明例外的部分外，本文档中的一切都适用于它们。

**已经在用 OpenClaw 或 Hermes？** 首个界面会提议把你的密钥、模型和技能迁移过来。不会移动任何东西，也不会替换这里已设置的任何内容。参见[从其他智能体迁移](migrating.md)。

你的回答会写入 `~/.comodor/config.json`，只有你本人可读。以后改变主意可以用 `comodor setup`，或逐项修改设置——参见[配置](configuration.md)。

### 最后一个问题是你的手机

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram** 只需要从 [@BotFather](https://t.me/botfather) 取一个 token，当场向 Telegram 验证，然后显示一段要发给机器人的代码，让它知道该响应哪个账户——从头到尾一分钟。参见[从手机使用](telegram.md)。

**Slack** 大约需要五分钟。应用由 Comodor 打印的 manifest 创建，只需粘贴一次而无需逐项勾选整页复选框，而且 Socket Mode 意味着完全不需要公网地址——参见[从 Slack 使用](slack.md)。

**WhatsApp** 做同样的事但大约需要二十分钟：一个 Meta 应用、一个企业号码、一个应用密钥和一个公网 HTTPS 地址，这些都无法在终端里完成。只有在不得不用 WhatsApp 时才值得——参见[从 WhatsApp 使用](whatsapp.md)。

无论选哪种，在你另行表态之前它只做读取和规划，而拒绝只需按一个键。

### 然后它会提议启动

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

安装流程过去到此为止——回到 shell 提示符，什么也没有运行。现在，每条已连接并完成配对的通道都会对应一个带名称的选项——设置过 WhatsApp 的人不会被提供"Telegram 机器人"这个选项。

---

## 3. 它会询问在哪个文件夹

```
  Work in  /home/you/projects/api-server ?
```

每个文件夹只询问一次。智能体可能触碰的一切都在该文件夹之下——除非你刻意关闭这一限制，否则它无法在其之外读取或写入。已批准的文件夹会被记住。

---

## 4. 提出请求

输入内容并按回车。

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

它会读取文件、运行测试，然后做出修改。在写入文件之前，你会看到 diff 和选项：

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

回答 `a` 允许一次，或者回答 `A` 让它在本次会话内不再就此询问。无论如何，每次写入都有检查点：`/undo` 可恢复上一次。

---

## 5. 纠正它——这是最重要的部分

当它出错时，告诉它。两种方式，教给它的是同样的东西：

**自己动手改文件。** Comodor 会注意到你对其输出所做的修改。

**直接说出来。**

```
> no — we use single quotes in this codebase, not double
```

无论哪种方式，它都会成为一条经验：下次遇到相似情境时被召回，置信度在成立时上升、不成立时衰减。

几个会话之后：

```
> /progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

这是证据，不是口号。如果纠正率没有下降，说明学习没有生效，面板会如实呈现而不是将其掩盖。

[它如何学习](learning.md) 说明了机制。

---

## 6. 第一天值得知道的事

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## 接下来去哪里

| 你想 | 阅读 |
|---|---|
| 在脚本中不使用界面运行它 | [命令行使用](cli.md) |
| 确切了解它能对你的机器做什么 | [安全与权限](safety.md) |
| 花更少的钱 | [成本](cost.md) |
| 让它使用浏览器 | [真实浏览器](browser.md) |
| 让它使用你的鼠标和键盘 | [操控你的屏幕](computer.md) |
| 编写它每次都遵循的操作流程 | [技能](skills.md) |
| 在服务器或 Docker 中运行 | [通过浏览器使用](web.md)、[在 Docker 中](docker.md) |

---

## 如果出了问题

```bash
comodor doctor
```

它会检查所有能检查的项目，并告诉你对发现的问题该怎么做。`comodor doctor --fix` 会修复可修复的部分。参见[故障排查](troubleshooting.md)。
