# 终端界面

你看到什么、按什么，以及全部 29 条命令。

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## 界面布局

```
┌────────────────────────────────────────────────────────────────────────┐
│  Comodor                              Anthropic · claude-sonnet-5      │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                        │
│  TASKS                    > fix the failing parser test                │
│  ● read the test          ▸ read_file  tests/test_parser.py     0.1s   │
│  ◐ find the cause         ▸ run_shell  pytest tests/test_pa…    2.3s   │
│  ○ fix it                                                              │
│                           The test expects `parse("")` to raise, but…  │
│                                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  ▌Type a task, or / for commands                                       │
│                                                                        │
│  act · loop on · 12% of 1M · $0.03      ⏎ send  ^O attach  F3 mode     │
└────────────────────────────────────────────────────────────────────────┘
```

**侧边栏** 显示计划（如果有的话）。`F2` 可隐藏它——在狭窄的终端上值得这么做。

**状态行** 显示当前模式、是否在迭代、上下文的占用程度，以及本次会话的花费。上下文数字是真实的：它随模型变化，因此从百万 token 模型切换到 128k 模型会立刻改变它。

它从约 60 列起即可正常工作。低于该宽度时侧边栏会自动收起。`comodor preview 80x24` 可以在不启动会话的情况下以任意尺寸渲染界面。

---

## 模式

| 模式 | 智能体可以做什么 | |
|---|---|---|
| **act** | 一切操作，写入和命令前先询问 | 默认模式 |
| **plan** | 只读。不写入、不运行命令、不联网 | 用于"你会怎么做？" |
| **chat** | 完全不使用工具 | 用于询问你粘贴的代码 |

`F3` 循环切换。`/mode plan` 直接设置某一种。

计划模式是真正的只读——它在权限层强制执行，而不是礼貌地请求模型配合。风险等级高于"safe"的工具在运行之前就会被拒绝。

---

## 按键

| | |
|---|---|
| `Enter` | 发送 |
| `Ctrl+J` | 在消息内换行 |
| `Esc` | 停下它正在做的事 |
| `Ctrl+C` | 停止；按两次退出 |
| `F1` | 帮助 |
| `F2` | 侧边栏 |
| `F3` | 模式 |
| `F4` | 循环开关 |
| `F5` | 网关 |
| `Ctrl+O` | 附加文件 |
| `Ctrl+L` | 清空对话 |
| `PgUp` `PgDn` | 滚动 |
| `Ctrl+↑` `Ctrl+↓` | 更早和更晚的消息 |
| `!command` | 直接运行 shell 命令，不经模型 |

`!` 值得记住。`!git status` 直接运行并显示输出；模型永远不会看到这个问题。比向它提问更便宜也更快捷。

---

## 命令

输入 `/`，列表会随输入过滤。

### 让它改变正在做的事

| | |
|---|---|
| `/mode [act\|plan\|chat]` | 允许它做什么 |
| `/loop` | 持续工作直到完成，或只回答一次 |
| `/model [id]` | 选择模型——给出列表，或直接指定一个 |
| `/provider [name]` | 选择提供商 |
| `/gw` | 网关：按成本、速度或质量在多个提供商之间路由 |

### 教它

| | |
|---|---|
| `/good` | 那个答案是对的 |
| `/bad` | 那个答案是错的 |
| `/teach <text>` | 记住这条 |
| `/memory` | 它已经学到的东西 |
| `/rules` | 它从你的代码和你的修改中总结出的家规 |
| `/progress` | 它正在进步的证据 |
| `/skills` | 当工作匹配时它会遵循的操作流程 |

`/good` 和 `/bad` 是你能为它做的最省力的事。参见[它如何学习](learning.md)。

### 撤销与回看

| | |
|---|---|
| `/undo` | 恢复它修改的最后一个文件 |
| `/clear` | 开始一段全新的对话 |
| `/resume [id]` | 重新打开更早的会话 |
| `/search <text>` | 在更早的对话中查找 |
| `/export [path]` | 把本次会话写入文件 |

### 让它触及更远

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | 让它使用你的屏幕——[指南](computer.md) |
| `/mcp` | MCP 服务器及其工具——[指南](mcp.md) |
| `/attach <path>` | 在下一条消息中附加一个文件 |

### 调整设置

| | |
|---|---|
| `/settings` | 当前配置了什么 |
| `/approve [writes\|shell\|all]` | 这些操作之前不再询问 |
| `/theme [name]` | ember、midnight、matrix、mono |
| `/save` | 把当前设置写入你的配置文件 |
| `/cost` | token 数、花费，以及缓存省下了多少 |
| `/copy [all\|task]` | 把最后一个回答，或全部内容，复制到剪贴板 |
| `/mouse [on\|off]` | 鼠标追踪，让你可以自己选择文本 |
| `/help` | 以上全部，在界面之内 |
| `/quit` | 离开 |

**`/save` 只写入你选择的内容。** 不包括仓库的设置，不包括你保存在环境中的密钥，也不包括只为一次运行传入的 `--model`。参见[配置](configuration.md#what-save-writes)。

---

## 审批

当智能体想写入文件或运行命令时：

```
  Write  src/parser.py
  ────────────────────────────────────────────
   - def parse(text):
   -     return text.split(",")
   + def parse(text):
   +     if not text:
   +         raise ValueError("nothing to parse")
   +     return text.split(",")

  [a] allow   [A] allow always this session   [d] deny
```

`A` 在本次会话内按类别记忆——允许写入并不意味着允许运行命令。

拒绝不会白费。拒绝是界面能收集到的最明确的偏好信号，它会进入学习引擎：智能体之后再次提出同样做法的可能性会降低。

想彻底停止被询问：

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

一切仍然有检查点。`/undo` 照常可用。

---

## 把文本复制出去

当鼠标被追踪时，拖选归 Comodor 所有，终端根本看不到——所以常规的选中复制不再起作用。三种绕过方式：

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy` 在 Windows 或 macOS 上无需安装任何东西。在 Linux 上它使用 `wl-copy`、`xclip` 或 `xsel`，哪个在就用哪个；如果都没有，它会说明缺了哪个。

通过 SSH 时，它会退回到一种转义序列，请求*你的*终端去设置*你的*剪贴板——这样来自服务器上智能体的文本会落到你能粘贴的地方，而不是落在一台根本没有剪贴板的服务器上。

大多数终端还允许你按住 **Shift** 进行选择，这可以在不关闭鼠标追踪的情况下绕过它。

---

## 谁在说话

每一轮对话都处于一条安静的色带上——你输入的内容是一种色调，回答是另一种：

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

刻意低调。它位于你要连续阅读数分钟的正文之下，任何有存在感的背景都会与文字争夺注意力。每个主题都有自己的配色对，与背景相差几个百分点；`mono` 没有这层色带，因为一个以无色为前提的主题并不需要两种颜色。

它们不占用任何纵向空间——颜色的变化就是边界。

---

## 从右到左的文字

波斯语、阿拉伯语和希伯来语靠右排版，与它们的行首位置一致，并搭配适合的字体栈。混合段落——波斯语句子中的英文标识符——按行而非按文件处理，这更贴近技术对话中的真实情况。

---

## 主题

```
/theme midnight
```

`ember`（默认，暖琥珀色）、`midnight`（冷蓝色）、`matrix`（绿色）、`mono`（完全无色）。

`--ascii` 会把框线字符替换为 ASCII，用于不支持它们的终端。会遵循环境中的 `NO_COLOR`。

---

## 另请参阅

- [命令行使用](cli.md) — 不用界面也拥有同样的能力
- [智能体能做什么](tools.md) — 那些 `▸` 行背后的工具
- [安全](safety.md) — 审批提示在防范什么
