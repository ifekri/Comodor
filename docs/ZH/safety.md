# 安全与权限

Comodor 能对你的机器做什么，它事先会问什么，以及无论你怎么说它都不会做什么。

---

## 简短版本

- **读取悄无声息。** 列出文件、读取内容、搜索——没有提示。
- **写入会询问。** 事情发生之前你能看到 diff。
- **运行命令的询问更郑重**，访问网络或操控你的屏幕也一样。
- **一切可逆的都可由 `/undo` 逆转。**
- **它无法离开项目文件夹**，除非你关闭这一限制。
- **一个仓库无法改变以上任何一条。**

---

## 风险等级

每个工具都声明一个。等级决定它运行之前会发生什么。

| Tier | Tools | What happens |
|---|---|---|
| **safe** | `read_file`、`list_dir`、`grep`、`glob`、`todo_write` | 直接运行 |
| **write** | `write_file`、`edit_file` | 询问，附带 diff |
| **dangerous** | `run_shell`、`run_python`、`web_fetch`、`web_search`、`browse`、`computer` | 询问 |

在**计划模式**下，任何高于 `safe` 的操作都会在运行之前被拒绝。这是在权限层强制执行的，而不是靠请求模型守规矩。

在**聊天模式**下根本没有工具。

---

## 提示

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  [a] allow   [A] allow always this session   [d] deny
```

`A` 在本次会话内按类别记忆——允许写入并不意味着允许运行命令，允许 `pytest` 也不意味着允许 `rm`。

想停止被询问：

```
/approve writes      files yes, commands still ask
/approve shell       commands yes, files still ask
/approve all         everything
```

或者永久生效，在你的配置里：

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### 拒绝也能教它

拒绝是界面能收集到的最明确的偏好信号。它会进入学习引擎，于是智能体再次提出同样做法的可能性会降低。拒绝不是白费的力气。

---

## 检查点与 `/undo`

智能体写入的每个文件都会先做检查点——先前内容，保存在项目的 `.comodor/checkpoints/` 之下。

```
/undo
```

恢复它修改的最后一个文件。无论你是否批准了那次写入、是否开启了自动批准，它都有效。这正是 `/approve all` 成为一件合理之事的原因。

实在要关的话：

```json
{ "safety": { "checkpoints": false } }
```

但没有什么好理由这么做。

---

## 工作区边界

智能体可以**在项目文件夹之内**读写，**除此之外任何地方都不行**。

项目根目录通过从你启动的位置向上逐层查找得出，直到有东西说"这是一个项目"——一个 `.git`、一个 `pyproject.toml`、一个 `package.json`。它会被展示给你并询问，每个文件夹一次：

```
  Work in  /home/you/projects/api-server ?
```

已批准的文件夹会被记住。`--cwd` 直接指定一个，并且不再询问。

```json
{ "safety": { "workspace_only": true } }
```

关闭它会让智能体触碰你的整个文件系统。仓库的配置之所以对这一点完全无权过问，正是为了这个。

---

## 它不会运行的命令

有些东西在任何提示出现之前就会被拒绝，因为没有任何提示应该能在漫长会话的尾声把一个人劝进这些事：

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

完整列表是 `safety.deny_commands`。添加你自己的：

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` 是反方向——从不提示的命令：

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## 你的密钥

**存放在哪里。** 你自己的 `~/.comodor/config.json`，以仅所有者可读的权限写入，或者你的环境。除此之外无处可去。

**绝不会去哪里。** 不进仓库的配置。不进界面。不进日志。不进 `repr`——那是一个真实的 bug，已被发现并修复：任何提及 Config 的回溯信息过去都会打印出密钥，而 pytest 时刻都在打印回溯。

**你环境中的密钥留在环境中。** 如果你导出 `ANTHROPIC_API_KEY` 而不是保存它，`/save` 不会把它复制进你的配置文件。用导出代替保存是一种明确的决定，它会被尊重。

**脱敏。** 任何看起来像你的密钥的东西，都会在工具输出、转录和导出中被遮蔽。它作用于文本。它读不了像素——参见[操控你的屏幕](computer.md#what-goes-to-the-model)。

---

## 一个仓库可以设置什么

项目中的 `.comodor/config.json` 会从你启动的任何目录读取——对一个编码智能体来说，这意味着*从别人写的仓库中，在克隆完成之后立即读取*。

所以它被限制在无法反过来对付你的东西上：

| 项目可以设置 | |
|---|---|
| `provider`、`model` | 使用哪个模型 |
| `agent` | 模式、循环、各项预算、temperature、输出大小 |
| `ui` | 主题、边框、字标 |
| `learning`、`skills` | 是否开启，以及各自的限制 |
| `mcp.servers` | 它使用哪些服务器——**到达时处于关闭状态** |

| 项目**不得**设置 | 原因 |
|---|---|
| `providers.*.base_url` | 你的密钥会在第一个请求发往他们的服务器 |
| `safety.*` | 它可以让智能体不再询问，或清空拒绝列表 |
| `agent.system_prompt_extra` | 以你的权威注入的指示 |
| `browser.executable` | 它指定了一个由智能体启动的二进制文件 |
| `computer.*` | 它向刚被克隆到的机器索要你的鼠标 |
| `mcp.enabled` | 声明一个服务器只是建议；启动一个则是决定 |

这是一份**允许列表**，而不是拒绝列表，所以明年新增的设置在被信任之前默认不受信任，直到有人另行决定——这是错误的正确方向。

拒绝会被大声说出：

```
config: this project cannot set safety, computer — only your own can
```

悄悄无视某个人的配置文件，正是让一个配置文件背上"不起作用"名声的做法。

---

## 天花板

三个，适用于每一个任务：

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**金钱那一项只对有公开费率的模型有效。** 对于价格表不认识的模型，费用计数器读数为零，上限永远不会触发。Comodor 会明说，而不是让你以为自己拥有一道天花板：

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

在会话开始时说明，也在 `comodor doctor` 中。参见[成本](cost.md)。

---

## 子智能体

`delegate` 在 git worktree 中运行一个子智能体——仓库的一个隔离副本。它没有记忆，不能再委派，而且**不会被给予屏幕**：在 worktree 中干活的子智能体没有理由用你的鼠标。

---

## 报告问题

如果你发现了安全问题，请不要开公开 issue。参见 [SECURITY.md](../SECURITY.md)。

---

## 另请参阅

- [操控你的屏幕](computer.md) — 这里最严格的权限模型
- [配置](configuration.md) — 每一项设置的位置
- [终端界面](interface.md#approvals) — 这些提示长什么样
