# Comodor 文档

一个会学习你纠正方式的终端编码智能体。

初次使用？**[快速上手](getting-started.md)** 大约需要五分钟，结束时智能体会做成一件有用的事。

---

## 按你想做的事查找

### 上手

| | |
|---|---|
| [快速上手](getting-started.md) | 安装、选择模型、第一个任务 |
| [从其他智能体迁移](migrating.md) | 把密钥和技能从 OpenClaw 或 Hermes 迁移过来 |
| [选择模型](models.md) | 用哪家提供商、哪个模型、费用多少 |

### 使用它

| | |
|---|---|
| [终端界面](interface.md) | 面板、按键、模式，以及全部 29 条命令 |
| [命令行使用](cli.md) | 每条命令与每个参数，附示例 |
| [智能体能做什么](tools.md) | 它拥有的 13 个工具，以及各自何时使用 |
| [技能](skills.md) | 你只需写一次、它便会遵循的操作流程 |

### 让它触及更远

| | |
|---|---|
| [真实浏览器](browser.md) | 能运行 JavaScript 并可登录的浏览器 |
| [操控你的屏幕](computer.md) | 鼠标与键盘，适用于任何应用程序 |
| [通过浏览器使用](web.md) | Web 界面，本地或在服务器上 |
| [在编辑器中使用](acp.md) | 从 Zed 或任何 Agent Client Protocol 客户端驱动 Comodor |
| [在 Docker 中](docker.md) | 一条命令，运行于容器之中 |
| [MCP 服务器](mcp.md) | 来自 Model Context Protocol 的工具 |

### 深入了解它

| | |
|---|---|
| [从手机使用](telegram.md) | Telegram 机器人：配对、按钮，以及它响应谁 |
| [从 Slack 使用](slack.md) | Socket Mode — 五分钟，无需公网地址，还能在会话线程中回复 |
| [从 WhatsApp 使用](whatsapp.md) | Cloud API — 大约二十分钟且偏技术性。Telegram 一分钟就能做到同样的事 |
| [本机模型](local-models.md) | 下载模型、离线运行、加入列表 |
| [提问](questions.md) | 当一个请求存在两种理解时，它给出的表单 |
| [它如何学习](learning.md) | 纠正、经验、规则，以及证据 |
| [安全与权限](safety.md) | 它能做什么、何时询问、绝不做什么 |
| [成本](cost.md) | 缓存、预算，以及为同样的工作花更少的钱 |
| [配置](configuration.md) | 每一项设置、文件存放位置、优先级规则 |

### 出现问题时

| | |
|---|---|
| [故障排查](troubleshooting.md) | `doctor`、常见问题，以及如何报告问题 |

---

## 最简版本

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # it asks a few questions, once
```

然后输入你想做的事。它做错了就纠正——直接改文件，或者口头说明——它就会学习。`/progress` 会告诉你这样做是否真的有效。

```bash
comodor run "fix the failing test in tests/test_parser.py"   # one task, no interface
comodor web                                                  # from a browser
comodor doctor                                               # is everything alright?
comodor help                                                 # the written help page
```

## 它的独特之处

**它从纠正中学习，而不是从表扬中学习。** 大多数智能体在会话结束的瞬间便忘掉一切。Comodor 会观察你对其输出所做的修改，并将其转化为一条经验（lesson），其置信度在成立时上升、不成立时下降。[它如何学习](learning.md) 说明了机制；`/progress` 展示证据。

**它先询问再行动，而且一切皆可撤销。** 读取悄无声息。写入需要确认。运行命令则需要更郑重的确认。每次写入都有检查点，`/undo` 可恢复上一次。[安全与权限](safety.md)。

**仅一个依赖。** HTTP 客户端、SSE 读取器、浏览器用的 WebSocket、截图用的 PNG 编码器——都包含在软件包之内。安装 Comodor 只会引入 `rich`，别无其他。

**它能使用真实的浏览器和真实的桌面。** 这不是一个文本抓取器：而是一个能运行 JavaScript 并保留 cookie 的浏览器，以及在 Windows 上——鼠标和键盘，屏幕上还有光晕提示它即将点击的位置。[浏览器](browser.md)、[屏幕](computer.md)。

---

## 仓库中还有

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | 变更了什么，以及原因 |
| [CONTRIBUTING](../CONTRIBUTING.md) | 参与 Comodor 本身的开发 |
| [SECURITY](../SECURITY.md) | 报告敏感问题 |
| [RELEASING](../RELEASING.md) | 发布版本是如何制作的 |
