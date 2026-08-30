# 在编辑器中使用

Comodor 遵循 [Agent Client Protocol](https://agentclientprotocol.com)（代理客户端协议），因此支持该协议的编辑器可以直接驱动 Comodor——使用它自己的面板、它自己的权限提示、它自己的文件视图——背后是同一个代理、同一套已学习的规则和同一批会话记录，与终端中完全一致。

```bash
comodor acp
```

你通常不需要手动输入这条命令，编辑器会自动启动它。

---

## 配置方法

Comodor 可以输出编辑器所需的配置块：

```bash
comodor acp --print-config
```

```json
{
  "agent_servers": {
    "Comodor": {
      "command": "/home/you/.local/bin/comodor",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

配置放在哪里取决于编辑器。以下是编写本文时在一台真实机器上实际配置并验证过的三个编辑器：

**JetBrains** — PyCharm、IntelliJ、WebStorm 等，通过 AI Assistant 插件使用。将配置块放入 `~/.jetbrains/acp.json`，或在 AI Chat 窗口菜单中选择 *Add Custom Agent*，它会打开同一个文件。之后 Comodor 会出现在聊天面板底部的代理选择器中。此功能不需要 JetBrains AI 订阅——ACP 代理无需订阅即可工作。

**VS Code** — 安装一个 ACP 客户端扩展；[ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) 是验证时使用的那个。配置块放在 `settings.json` 的 `acp.agents` 下，之后 Comodor 会出现在 ACP 面板的代理列表中。

**Zed** — 在 `settings.json` 中配置，之后 Comodor 会出现在代理面板中。

另外据反馈也可使用（本文未验证）：Neovim（CodeCompanion、avante.nvim、agentic.nvim）、Emacs（agent-shell.el）、Qt Creator、Obsidian 和 Visual Studio。

协议在任何地方都是相同的，不同的只是配置文件。

先在终端中设置好 Comodor：

```bash
comodor setup
```

编辑器无法询问你使用哪个模型提供商，因此从未配置过的 Comodor 会拒绝启动会话，并告知应运行哪条命令。这样你会在编辑器中看到一条明确的提示，而不是在第一个任务上失败。

---

## 编辑器能获得什么

| | |
|---|---|
| 流式回复 | 模型输出时实时显示 |
| 工具调用 | 每次调用都会标明名称及其执行的操作，并标记为读取 / 编辑 / 执行，方便编辑器选择图标 |
| 权限提示 | 在编辑器中提问，在编辑器中作答 |
| 任务计划 | 当 Comodor 写出任务列表时，编辑器会将其渲染出来 |
| 取消 | 编辑器的停止按钮会中断当前回合 |
| 会话 | 可以列出、恢复和删除——与 `comodor` 恢复的是同一批会话记录 |

工作目录来自编辑器：代理在你当前打开的项目中读写文件，并且仅限于此目录。

---

## 它不做什么

**从编辑器获取模型提供商。** Comodor 的提供商、模型、规则、技能和权限由它自己管理，通过 `comodor setup` 或浏览器界面配置。如果编辑器也要配置模型，就会对同一设置形成第二个真相来源。

**登录。** Comodor 向模型提供商认证，而不是向你的编辑器认证，因此它不会声明任何认证方法，客户端也不会向你提供登录选项。

---

## 出现问题时

协议将标准输出保留用于协议消息，因此 Comodor 的日志输出到标准错误。编辑器通常会在某处显示这些日志——在 Zed 中就是代理服务器的日志。

```
comodor acp — speaking ACP v2 on stdio
```

有一个常见问题，看起来像是代理坏了，但其实是：提供商拒绝了你的密钥。它在编辑器中显示为 `Error during prompt
turn`，或者显示为提供商自己的报错——例如 `OpenRouter: User not found`，这意味着密钥已被吊销。`comodor doctor` 会告诉你配置的是哪个提供商；浏览器界面可以接受新密钥，或让你重新登录。

如果代理已连接却毫无反应，先在终端中运行 `comodor doctor`：从编辑器看，无法访问的提供商和损坏的代理表现是一样的。

---

## 另请参阅

- [从浏览器使用](web.md) — 同一个代理，在浏览器标签页中
- [界面](interface.md) — 终端版本
- [安全性](safety.md) — 它事先会询问什么，以及它从不做什么
