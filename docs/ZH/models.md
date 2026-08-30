# 选择模型

Comodor 可以搭配任何支持 OpenAI 或 Anthropic API 的服务——开箱即用十七家提供商，再加上任何其他有 URL 的服务。

---

## 简短回答

| 你想要 | 选择 |
|---|---|
| 最容易上手，一个密钥，万事俱备 | **OpenRouter** |
| 最强的智能体工作能力 | **Anthropic**，`claude-sonnet-5` |
| 一分不花并且保持离线 | **Ollama** 或 **LM Studio** |
| 非常便宜，擅长代码 | **DeepSeek** |
| 非常快 | **Groq** 或 **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## 全部提供商

**托管服务，一个密钥：** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**你的机器上，无需密钥：** Ollama · LM Studio

**其他任何服务：** 选择 *Something else* 并填入 base URL。任何 OpenAI 兼容的端点都可以。

---

## 在本地免费运行

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

无需密钥，无需花费，无需联网。一个 14B 的编码模型对于日常工作确实够用；差距体现在耗时的多步任务上。

---

## 切换

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

上下文仪表跟随模型。从百万 token 的模型切换到 128k 的模型会立即改变上限——这很重要，因为智能体会在上限的某个比例处压缩对话，而过期的上限意味着它永远不压缩，然后在提供商的真实上限处失败。

要让切换永久生效：`/save`，或编辑
`~/.comodor/config.json`。

---

## 密钥

两种方式都行，且互不复制：

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

你环境中的密钥**会留在环境中**——`/save` 不会把它写到磁盘上。用导出代替保存是一种明确的决定，并且会被尊重。

Comodor 自己的配置文件以仅所有者可读的权限写入，你的密钥绝不会出现在日志、转录、导出或回溯信息中。
[安全](safety.md#your-keys)。

---

## 网关

跨多个提供商路由，而不是固定一个。

```
/gw                    # or F5
```

```json
{
  "gateway": {
    "enabled": true,
    "policy": "quality",
    "chain": ["anthropic", "openrouter", "deepseek"],
    "failure_threshold": 3
  }
}
```

`policy` 是 `cost`、`speed` 或 `quality`。连续失败三次的提供商会被跳过一分钟。开启时状态行显示 `GW: Quality`，关闭时显示 `GW: Disable`。

---

## 视觉

有些工具会返回图片——`browse look`，以及每一次 `computer` 截图。这些需要能看图的模型。当前所有 Claude 和 GPT-4o 家族都可以；大多数开放模型不行。

如果你打算使用[屏幕](computer.md)，先确认模型有"眼睛"，否则它会被交给一张读不懂的图片，然后开始瞎猜。

---

## 花费

```
/cost
```

关于缓存、预算，以及为什么花费上限有时无法强制执行，参见[成本](cost.md)。
