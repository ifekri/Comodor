# 配置

一个你几乎从不需要手动编辑的 JSON 文件——但这里是其中的一切。

---

## 各项内容存放位置

| | |
|---|---|
| `~/.comodor/config.json` | 你的。由向导写入；仅所有者可读的权限 |
| `~/.comodor/brain.db` | 它已经学到的东西 |
| `~/.comodor/sessions/` | 每一段对话 |
| `~/.comodor/skills/` | 你安装或编写的技能 |
| `./.comodor/config.json` | 项目的。可以安全提交——参见[它可设置的范围](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | 它改动过的每个文件的先前内容 |

在 Windows 上，`~/.comodor` 是 `%APPDATA%\Comodor`。`COMODOR_HOME` 在任何地方都优先于它。

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## 什么优先

四个层次。靠后的胜过靠前的。

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### `/save` 写入什么

**只写入你选择的内容。** 这件事比听起来更重要。

智能体实际运行所依据的配置，是全部四个层次合并后的结果。若把这份合并结果原样写回你的文件，会让一个克隆仓库的花费上限变成你永久性的全局默认值，也会把你刻意留在环境中的 API 密钥写到磁盘上。

因此 `/save` 会记住每个值的来源。凡仍由借来的层次所提供的值，会退回到*你的*文件原先的说法；凡你在会话中修改过的值，就归你所有，会被写入。

- `/model x` 然后 `/save` → 持久化 `x`
- 在一个把 `max_cost_usd` 固定为 `500` 的仓库中执行 `/save` → 这类内容什么都不会持久化
- 在导出了 `ANTHROPIC_API_KEY` 的情况下执行 `/save` → 密钥留在你的环境中

---

## 每一项设置

### `provider` 与 `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

参见[选择模型](models.md)。

### `agent` — 它如何工作

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`、`plan`（只读）、`chat`（无工具） |
| `loop` | 持续工作直到完成，或只回答一次 |
| `max_steps` | **`0`——无上限，而这正是默认值。** 一个横跨十几个文件的重构曾在思考进行到一半时用尽了二十四步，而步数与危害之间并无对应关系。设置一个数字可恢复上限 |
| `max_seconds` | 一小时。`0` 表示无上限 |
| `max_cost_usd` | 与出错代价相对应的天花板——前提是[模型有公开的费率](cost.md#when-the-limit-cannot-fire)。`0` 表示无上限 |
| `context_limit` | 仪表读数。切换模型时自动跟随模型 |
| `compact_at` | 历史超过该比例后进行摘要压缩 |
| `max_tool_chars` | 单个工具结果有多少会到达模型。其余部分写入一个文件，并告知模型如何读取——而不是直接截断 |
| `keep_screenshots` | 会话中保留多少张截图。[原因](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | 你自己的长期指示 |
| `prompt_cache` | 允许提供商重复提供不变的前缀。[成本](cost.md) |
| `prompt_cache_ttl` | `5m` 或 `1h`。写入一小时档的成本更高 |

### `safety` — 它可以做什么

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

完整说明：[安全与权限](safety.md)。

### `learning` — 它记住什么

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | 每轮召回多少条经验 |
| `max_playbook_tokens` | 召回可注入内容的硬上限 |
| `reflect` | 在任务之后提炼经验——这一项要消耗一次模型调用 |
| `reflect_model` | 用于此事的更便宜的模型，随你所愿 |
| `half_life_days` | 一条未使用的经验多久消退 |
| `share_scope` | `project` 或 `global` |
| `corrections`、`rules`、`announce`、`prefetch` | 快速通道——免费，不消耗模型调用，即使 `reflect` 关闭也保持开启 |

完整说明：[它如何学习](learning.md)。

### `ui` — 它的外观

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` 永久关闭字标；`COMODOR_BANNER=0` 只在一次运行中生效。

### `skills` — 操作流程

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

完整说明：[技能](skills.md)。

### `telegram` — 从手机使用

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | `comodor telegram start` 是否运行机器人 |
| `token` | 来自 [@BotFather](https://t.me/botfather)。首次运行的设置会询问，或用 `comodor telegram connect` |
| `allowed` | 它响应的 Telegram 数字用户 id，除这些之外无人可唤。由 `comodor telegram pair` 填入，绝不来自 Telegram 本身 |
| `allow_writes` | 由手机发起的一轮是否可以编辑文件、运行命令。关闭时，无论终端如何设置，它都保持在计划模式 |
| `pair_window` | 配对码有效的秒数 |

**项目的 `.comodor/config.json` 不得设置其中任何一项。** 一个能向 `allowed` 添加账户的仓库就是一个后门，而且与浏览器或屏幕不同，它发生时没有任何可见的痕迹。

完整说明：[从手机使用](telegram.md)。

### `slack` — 从 Slack 工作区使用

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | 来自 OAuth & Permissions 的 `xoxb-…`。机器人做的一切都靠它 |
| `app_token` | 来自 Basic Information 的 `xapp-…`，作用域 `connections:write`。只用于打开 Socket Mode 的 websocket，此外什么也做不了 |
| `allowed` | 它响应的 Slack 用户 id。不是显示名称：显示名称可以被持有它的人随时更改 |
| `allow_writes` | Slack 的一轮是否可以编辑文件、运行命令 |
| `pair_window` | 配对码有效的秒数 |
| `team` | 连接时所在的工作区，被记住以便 `status` 能说出它的名字而不必往返查询 |

**项目的 `.comodor/config.json` 不得设置其中任何一项**，理由与其他几项相同：一个能向 `allowed` 添加账户的仓库就是一个后门。

完整说明：[从 Slack 使用](slack.md)。

### `whatsapp` — 从 WhatsApp 号码使用

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | 一个 Meta 访问令牌。System User 的令牌不会过期；控制台自己生成的只有 24 小时 |
| `phone_number_id` | Meta 显示在号码旁边的数字 id，而不是号码本身 |
| `app_secret` | 每个 webhook 都用它签名。没有它，什么都无法验证 |
| `verify_token` | 在 Meta 的一次性握手中被回显。是生成的，不是自选的 |
| `allowed` | 它响应的号码，按数字比较。其他人得到的是沉默 |
| `allow_writes` | WhatsApp 的一轮是否可以编辑文件、运行命令 |
| `host`、`port`、`path` | webhook 的监听位置。本机地址，藏在某个终结 TLS 的服务之后 |
| `public_url` | Meta 投递到的地址，被记住以便 `whatsapp webhook` 能打印它 |
| `api_version` | 固定不变，因为 Meta 按照它自己的日历而非你的日历弃用版本 |

**项目的 `.comodor/config.json` 不得设置其中任何一项**，理由与 `telegram` 相同：一个能向 `allowed` 添加号码的仓库就是一个后门，而且屏幕上没有任何东西显示它正在发生。

完整说明：[从 WhatsApp 使用](whatsapp.md)。

### `browser` — 真实浏览器

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

`headless: false` 就是你观看它工作的方式。`port` 用于连接你自己启动的浏览器，这样它可以复用你已登录的会话，而不是被交出你的整个用户配置。

完整说明：[真实浏览器](browser.md)。

### `computer` — 你的屏幕

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

完整说明：[操控你的屏幕](computer.md)。

### `gateway` — 跨提供商路由

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` 是 `cost`、`speed` 或 `quality`。设为 `enabled: true` 时，它会从 `chain` 中挑选，并跳过持续失败的提供商。界面中使用 `F5` 或 `/gw`。

### `mcp` — Model Context Protocol 服务器

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

用 `comodor mcp` 管理，而不是手动。[MCP 服务器](mcp.md)。

---

## 环境变量

| | |
|---|---|
| `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`OPENROUTER_API_KEY`…… | 每个提供商一个 |
| `<PROVIDER>_BASE_URL`、`<PROVIDER>_MODEL` | 覆盖端点或模型 |
| `COMODOR_PROVIDER`、`COMODOR_MODEL` | 强制指定其中之一 |
| `COMODOR_HOME` | 一切的存放位置 |
| `COMODOR_BANNER=0` | 不显示字标 |
| `COMODOR_NO_IMPORT=1` | 不提议从另一个智能体导入 |
| `COMODOR_WEB_TOKEN` | Web 界面的固定 token |
| `NO_COLOR` | 无颜色 |

---

## 当某项设置没有生效时

Comodor 会明说，而不是无视你：

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

类型错误的值，在转换无歧义时会被转换，在有歧义时会被拒绝，并且拒绝时会指出键名和期望的类型。`null` 不会悄悄把一个字符串替换成 `None`。

如果某项设置看起来仍然毫无作用：

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
