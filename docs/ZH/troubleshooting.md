# 故障排除

## 从这里开始

```bash
comodor doctor
```

它会检查配置文件及其权限、提供商、模型、花费上限、大脑、搜索索引、你的技能、遗留文件、MCP 服务器，以及是否有更新的版本发布。

```bash
comodor doctor --fix
```

会修复可修复的部分。它从不改动任何没有先报告过的东西。

---

## 它启动不了

**安装后紧接着出现 `comodor: command not found`** — 安装程序已把它放进了你的 `PATH`，但子进程无法改变启动它的那个 shell 的环境。每个*新*终端已经可以用了。对当前这个终端，安装程序打印过要粘贴的那一行；或者：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**在新终端里出现 `comodor: command not found`** — 这是真问题。
`python -m comodor` 能确认它到底装没装，而
`ls ~/.local/bin/comodor` 能看它是否在该在的地方。

**`No provider is configured`** — 运行 `comodor setup`，或者导出一个密钥：

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python 太旧。** Comodor 需要 3.11 或更新版本。用 `python --version` 检查。

---

## 一个设置看起来毫无作用

Comodor 在拒绝某个设置时会告诉你：

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

如果什么都没说而它仍然不生效，检查哪一层赢了：

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

命令行上的 `--model` 压过你的配置文件，环境里的密钥压过文件里的密钥。这是刻意的——
[配置](configuration.md#what-wins)。

---

## `/save` 没有保存我期望的东西

这是设计如此。它只写**你选定的东西**——不写仓库的设置，不写你保存在环境里的密钥，不写你只为一次运行传过的标志。

想把一个仓库的设置变成你自己的，先自己设置一遍（`/model x`），然后保存。

---

## 请求失败

**`401` 或 `invalid api key`** — 密钥错了、过期了，或属于另一个提供商。`comodor doctor` 会显示当前激活的是哪个提供商。

**`404 model not found`** — 那个提供商不提供那个模型 id。`/model` 会列出它实际提供的模型。

**超时。** 在一台普通的机器上，本地模型真的可能要花几分钟。调高 `providers.<name>.timeout`。

**它提前停止了。** 看看 `stopped`。`max_steps` 和 `budget` 是在正常履职的上限，不是故障。用 `--max-steps` 为一次运行调高，或在 `agent` 下永久调高。

---

## 花费上限不起作用

它多半本来就不可能起作用，而且 Comodor 会说明这一点。参见
[成本——当上限无法触发时](cost.md#when-the-limit-cannot-fire)。

---

## 浏览器工具

**"no browser found"** — 安装 Chrome、Chromium、Edge 或 Brave，或者设置
`browser.executable`。都没有的话，`browse` 会退回到一个文本浏览器，它仍然能回答关于页面的大部分问题。

**我想看它工作** — `browser.headless: false`。

**它需要一个我已经有的登录** — 用 DevTools 端口启动你自己的浏览器并设置 `browser.port`，让它使用那个会话，而不是把你的配置文件交出去。

---

## 屏幕工具

**它不在工具列表里。** 要么这个平台没有后端——目前仅支持 Windows——要么 `computer.enabled` 是 false。问它：

```
/computer
```

**点击落错了地方。** 这不应该发生：DPI 感知在任何屏幕度量被读取之前就已设置。如果真的发生了，请附上你的显示缩放和分辨率报告。那是一个真正的 bug。

**它自己停了。** 鼠标进入了屏幕的一个角落，这会按设计结束授权。`/computer 15m` 开始新的一次。

**到达的文本不是它输入的文本。** 是应用程序改写了它——
Windows 11 的记事本会边打边自动更正。这不是 Comodor 的 bug，它在每次 `type` 时都会说明。[更多](computer.md#typed-is-not-the-same-as-arrived)。

---

## 网页界面

**它拒绝启动。** 没有配置提供商，而浏览器界面没有添加提供商的地方。消息会说明要设置什么。

**"Unauthorised"。** 每次运行都生成新 token——使用*本次*运行给出的 URL，或者设置 `COMODOR_WEB_TOKEN` 让它保持稳定。

**在 Docker 里，`localhost:8765` 上什么都没有。** 检查端口是否以
`127.0.0.1:8765:8765` 的形式发布。[Docker](docker.md)。

---

## 什么东西很慢

**一个会话的第一次请求。** 什么都还没缓存；第二次会快得多。

**每个任务之后的反思。** 一次模型调用。用 `learning.reflect_model` 换一个更便宜的，或设 `reflect: false`。

**截图。** 大约 80 毫秒截取，加上模型看它们的时间。如果你还能读清结果，就调低 `computer.screenshot_tokens`。

---

## 重新开始

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

或者只删大脑，保留你的设置：

```bash
rm ~/.comodor/brain.db
```

---

## 报告一个问题

请附上：

```bash
comodor --version
comodor doctor
```

`doctor` 会遮蔽你的密钥。不过无论如何，粘贴之前还是请先读一遍输出。

- Issues: <https://github.com/ifekri/Comodor/issues>
- 敏感事项: [SECURITY.md](../SECURITY.md)
