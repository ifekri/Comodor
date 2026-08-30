# 从终端使用

每条命令与每个参数，附上可以直接粘贴的内容。

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## 安装与更新

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` 不指定任何文件：它会识别请求方是谁，并返回该客户端能运行的安装器。同一行命令也可以更新已有的安装。或者，装好之后：

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

[快速上手](getting-started.md#1-install) 有其余内容——包管理器，以及安装器接受的选项。

---

## 启动它

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### 参数

| | |
|---|---|
| `--provider NAME` | `openrouter`、`anthropic`、`openai`、`ollama`…… |
| `--model ID` | 覆盖本次运行的模型 |
| `--mode act\|plan\|chat` | plan 为只读；chat 无工具 |
| `--no-loop` | 只回答一次，而不是工作到完成 |
| `--cwd PATH` | 它可以触碰的文件夹 |
| `--theme NAME` | `ember`、`midnight`、`matrix`、`mono` |
| `--ascii` | ASCII 边框 |
| `--no-mouse` | 把鼠标留给终端 |
| `--resume [ID]` | 上一次会话，或按 id 指定的某次会话 |
| `--demo` | 脚本化的离线提供商 |
| `--version` | 当前是哪个版本 |
| `-h`、`--help` | 书面帮助页 |

这些都不会写入你的配置。它们只作用于这一次运行。要让改动长期生效，请在界面中使用 `/save`，或直接编辑配置文件——[配置](configuration.md)。

---

## `comodor run` — 单个任务，无界面

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | 自动批准写入和命令 |
| `--json` | 在 stdout 上输出机器可读的结果 |
| `--max-steps N` | 覆盖本次运行的步数上限 |

不带 `--yes` 时，它会在 stderr 上询问；如果没有任何东西可以回答，它会拒绝而不是擅自假设。这是刻意为之：一个静默自我批准的脚本，就是一个会在凌晨三点做出你预料之外的事情的脚本。

`--json` 给出：

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped` 说明它为何结束——取值如下：

| | |
|---|---|
| `done` | 它认为自己完成了 |
| `max_steps` | 它触及了 `agent.max_steps` |
| `budget` | 它触及了 `agent.max_cost_usd` 或 `agent.max_seconds` |
| `cancelled` | 你打断了它 |
| `error` | 出了问题；`error` 说明是什么 |

`ok` 对 `done` 和 `max_steps` 都为 true——步数用尽不是失败，而是上限在正常发挥作用——所以如果你需要区分二者，请同时检查 `stopped`：

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

无界面运行同样会学习。之后你做出的纠正，与交互式运行中的纠正教给它的东西完全一样。

---

## `comodor setup` — 选择提供商和模型

```bash
comodor setup
```

六个问题；如果检测到另一个智能体并且提议导入，则是七个。首次运行时自动执行；之后用它来改变主意。

回答写入 `~/.comodor/config.json`。

---

## `comodor import` — 从 OpenClaw 或 Hermes 导入

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

不会移动任何东西，也不会替换这里已设置的任何内容。参见[从其他智能体迁移](migrating.md)。

---

## `comodor doctor` — 一切正常吗？

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix` 修复可修复的部分——过时的提供商名称、缺失的目录、损坏的搜索索引。它绝不改动任何没有事先报告的东西。

只要有任何检查失败，退出码就非零，因此它可用于健康检查。

---

## `comodor web` — 通过浏览器

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

完整指南：[通过浏览器使用](web.md)。

---

## `comodor telegram` — 从手机使用

```bash
comodor telegram connect <token>  # a bot from @BotFather
comodor telegram pair             # a one-time code that adds your account
comodor telegram start            # here, holding this terminal
comodor telegram start -b         # detached; survives closing the terminal
comodor telegram stop             # end a background one
comodor telegram service install  # start it at login, so a reboot brings it back
comodor telegram service show     # read the unit before trusting it
comodor telegram status           # what is configured, who may talk, is it up
comodor telegram writes on        # let a phone turn edit files
comodor telegram writes off
comodor telegram forget 12345     # revoke one account
comodor telegram forget all
comodor telegram off              # stop without forgetting anything
```

首次运行的设置会把这一切作为最后一个问题提供；这些命令用于事后修改，或用于一台已经配置好的机器。

完整指南：[从手机使用](telegram.md)。

---

## `comodor slack` — 从 Slack 工作区使用

```bash
comodor slack manifest            # the app definition to paste into Slack
comodor slack connect             # the two tokens, checked as you paste them
comodor slack pair                # a one-time code that adds your account
comodor slack start               # here, holding this terminal
comodor slack start -b            # detached
comodor slack stop
comodor slack service install     # start it at login
comodor slack status              # what is set, who may talk, is it running
comodor slack writes on           # let a Slack turn edit files
comodor slack forget U01234567
comodor slack off
```

大约五分钟，而且无需公网地址：Socket Mode 让应用主动向外打开一条 websocket，而不是被动接受投递。

完整指南：[从 Slack 使用](slack.md)。

---

## `comodor whatsapp` — 从 WhatsApp 号码使用

```bash
comodor whatsapp connect          # guided: links each page, checks each value
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # what to paste into Meta's dashboard
comodor whatsapp pair             # a one-time code that adds your number
comodor whatsapp start            # here, holding this terminal
comodor whatsapp start --tunnel   # and bring a Cloudflare tunnel up with it
comodor whatsapp start -b         # detached
comodor whatsapp stop
comodor whatsapp service install  # start it at login
comodor whatsapp status           # what is set, who may talk, is it running
comodor whatsapp writes on        # let a phone turn edit files
comodor whatsapp forget 15551234567
comodor whatsapp off
```

Meta 把消息投递到一个 URL，而不是让你轮询，所以这一条需要公网 HTTPS 地址。不带参数的 `connect` 会走完整个设置流程并自行启动隧道；第一次大约二十分钟，大部分时间花在 Meta 的控制台上。无需真实号码，无需银行卡，无需企业认证。

完整指南：[从 WhatsApp 使用](whatsapp.md)。

---

## `comodor skills` — 它会遵循的操作流程

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

完整指南：[技能](skills.md)。

---

## `comodor mcp` — Model Context Protocol 服务器

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

完整指南：[MCP 服务器](mcp.md)。

---

## `comodor update` — 升级到最新版本

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

它会判断这份副本是如何安装的——`uv`、`pipx`、`pip`，还是源码检出——然后采用正确的方式。源码检出保持原样不动：那一份是你自己的。

---

## `comodor uninstall` — 彻底移除

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

它在删除任何东西之前会先列出一切，并说明它找不到什么——一个你用过、但其会话历史已被清空的项目，其中的 `.comodor` 文件夹无法被列出来，它会如实告知，而不是装作不存在。

---

## `comodor preview` — 指定尺寸的界面

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

渲染一帧然后退出。适合检查窄终端下的效果，或用来截图。

---

## 环境变量

| | |
|---|---|
| `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`…… | 每个提供商一个密钥 |
| `COMODOR_PROVIDER`、`COMODOR_MODEL` | 强制指定提供商或模型 |
| `COMODOR_HOME` | 配置、大脑和会话的存放位置 |
| `COMODOR_BANNER=0` | 本次运行不显示字标 |
| `COMODOR_NO_IMPORT=1` | 不提议从另一个智能体导入 |
| `COMODOR_WEB_TOKEN` | Web 界面的固定 token |
| `NO_COLOR` | 无颜色，处处遵循 |

环境中的密钥**绝不会写入你的配置文件**。用导出代替保存是一种明确的决定，`/save` 会尊重它。参见[配置](configuration.md)。

---

## 退出码

| | |
|---|---|
| `0` | 成功 |
| `1` | 失败 |
| `130` | 你打断了它 |

---

## 另请参阅

- [终端界面](interface.md) — 同样的能力，以交互方式进行
- [配置](configuration.md) — 让某个参数永久生效
- [故障排查](troubleshooting.md) — 当命令没有照它说的做时
