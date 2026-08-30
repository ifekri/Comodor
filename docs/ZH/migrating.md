# 从其他智能体迁移

如果你已经在用 **OpenClaw** 或 **Hermes**，Comodor 会在你第一次运行时提议把你的配置迁移过来。

你已经找到过 API 密钥并把它们粘贴到某个地方了。再来一遍是个糟糕的第一印象。

---

## 首次运行时

```
 1/7  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

只有确实有东西可导入时，这个问题才会出现。

---

## 之后

后来才装了其中一个，或者当初回答了"start fresh"之后改变了主意：

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

运行两次是安全的——第二次它会告诉你没有新的东西。

---

## 会迁移过来的

| | |
|---|---|
| **API 密钥** | 全部繁琐的部分。来自它们的 `.env`，也来自 OpenClaw 内联的 JSON |
| **模型** | 如果 Comodor 能承载它 |
| **技能** | 两个工具写的是同一种开放格式，所以这些就是待复制的文件 |

整个过程贯穿三条规则，因为这要读取另一个程序写的文件：

- **不会覆盖任何东西。** 这里已经配置的密钥优先；导入只负责填补空缺。
- **不会移动任何东西。** 每一次操作都是读取。另一个工具保持原样继续工作。
- **格式错误的文件会被跳过，而不是致命错误。** 它一半的价值就在于能在另一台智能体处于奇怪状态的机器上运行。

---

## 不会迁移的，以及为什么

**它们的记忆。** 明说出来，而不是悄悄跳过：

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

Comodor 的大脑是带有置信度、证据和衰减机制的经验，从纠正中学来。一份 `MEMORY.md` 是散文。把后者当成前者导入，等于凭空捏造没人测量过的置信度，并用从未挣得的条目填满召回。你会得到一个看起来见多识广、实际却更糟糕的智能体。

**人格、消息、文字转语音。** Comodor 没有对应物，而一项导入后无处安放的设置比没有设置更糟。

**存放在别处的密钥。** OpenClaw 允许密钥是对某个文件或某条命令的引用。这些只在写它们的机器上有意义，在这里什么都不是，所以会被报告而不是被猜测。

---

## 技能，以及一件值得知道的事

导入的技能会加上命名空间——`review` 变成 `openclaw-review`——因此导入永远不会悄悄替换掉你自己的一个技能。

技能文件夹逐文件复制，并且**包含指向自身之外的链接的文件夹会被拒绝**。技能是一个其内容会被读入提示词的文件，因此若不加防范，另一个程序技能目录中指向 `~/.ssh/id_rsa` 的符号链接就会被复制进去并发给模型。拒绝，并点名道姓：

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## 它会查看哪里

| | |
|---|---|
| OpenClaw | `~/.openclaw`、`~/.clawdbot`、`~/.moltbot` |
| Hermes | `~/.hermes` |

那两个较旧的 OpenClaw 目录仍然存在于真实的机器上——它改过两次名——所以三处都会检查。

要让它完全不查看：

```bash
export COMODOR_NO_IMPORT=1
```

---

## 另请参阅

- [快速上手](getting-started.md) — 首次运行的其余部分
- [配置](configuration.md) — 导入的设置最终去了哪里
- [技能](skills.md) — 对迁移过来的技能做点什么
