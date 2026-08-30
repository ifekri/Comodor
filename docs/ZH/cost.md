# 成本

一次会话花多少钱，以及如何在不让质量变差的前提下让它花得更少。

```
/cost
```

```
This session

- prompt tokens: 84,210
- output tokens: 3,180
- served from cache: 72,418 (86% of the prompt)
- cost: $0.1904
- saved by caching: $0.4126 (68%)
- context used: 87,390 / 1,000,000
- compactions: 0

Brain

- lessons: 812
- skills: 4
- episodes: 137 (83% succeeded)
```

---

## 提示词缓存，这才是大头

每个请求都会重发那些不变的部分——系统提示词、工具 schema、到目前为止的对话。提供商愿意以大约十分之一的价格重新提供字节完全相同的前缀。

Comodor 正是围绕这一点构建的，而且默认开启：

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

在真实会话上测得：**86% 的输入 token 由缓存提供**。

### 为什么系统提示词里不放任何动态内容

缓存只对与上次字节完全相同的前缀有效。系统提示词*就是*那个前缀。任何逐轮变化的东西——召回的经验、匹配到的技能、当天的时间——都会使其失效，于是你为一切付出全价，每一轮都如此。

所以召回的经验搭在*轮次*上，作为用户消息的一部分。仅这一项改动就把实测的缓存命中率从 72% 提升到了 87%。

如果你要添加自己的长期指示，请放在 `agent.system_prompt_extra` 里，它保持稳定，而不是让它们变化。

### 一小时档的缓存

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

*写入*一条记录的成本约高 25%，但让它保留一小时而不是五分钟。如果你会反复回到同一个会话，这值得；如果只是一次突发性的工作，那就是浪费。

---

## 天花板

```json
{
  "agent": {
    "max_steps": 0,
    "max_seconds": 3600,
    "max_cost_usd": 2.0
  }
}
```

先到者停止任务，`0` 表示无上限。`--json` 中的 `stopped` 会说明是哪一个。

**默认没有步数上限。** 在真实的代码库上，二十四步什么也做不了——一个横跨十几个文件的重构曾在思考进行到一半时用尽了它们——而且步数与危害之间并无对应关系：读十个文件的十步几乎不花什么钱。真正与危害对应的天花板是时间和金钱，而这两个保持开启。如果你想要一堵硬墙，把 `max_steps` 设为一个数字即可。

当天花板真的停下一个任务时，消息会说明如何越过它，说一句"continue"就从停下的地方继续。

### 上限无法触发的时候

**花费上限只对有公开费率的模型有效。**

价格表刻意不为它没有把握的模型设置费率——编造一个价格会产生错误的数字，这比没有数字更糟。对于一个未定价的模型，费用计数器读数为零，因此 `spent >= max_cost_usd` 永远不成立，上限永远不会触发。

Comodor 会明说，而不是让你以为自己受到了保护：

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

在会话开始时说明，也在 `comodor doctor` 中：

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

对于运行在你自己机器上的模型，它会说些别的，因为那里的成本本来就是零。

---

## 真正花钱的地方

**截图。** 默认预算下每张约 1,600 个视觉 token——而且只要它们还留在对话里，每一轮都要再付一次。Comodor 只保留最后两张，其余的替换为一行说明"这里曾有一张图"。若非如此，一个三十步的桌面任务会携带将近五万个 token 的像素，描述那些早已被点击翻篇的屏幕。

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

不要把 `screenshot_tokens` 设得太低。一张模型读不懂的图比没有图更糟：它会瞎猜而不是开口问。参见[操控你的屏幕](computer.md#screenshots-and-what-they-cost)。

**巨大的工具输出。** 由 `agent.max_tool_chars` 限定。放不下的部分写入一个文件，并告知模型如何读取，所以只有它去看了才付钱。

**反思。** 一个任务结束时的一次模型调用。把它指向更便宜的模型：

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

或者干脆关掉。免费通道——纠正、规则、公告——无论哪种方式都照常运转。[它如何学习](learning.md#the-two-lanes)。

**浏览器，当它要看图的时候。** `browse` 默认返回文本，只有被要求时才返回截图，因为一张页面图片每一次的价格都一样，而且无法压缩。

---

## 一分不花

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

本文档中的一切都能工作，而且分文不花，除了明确说明例外的部分。[选择模型](models.md#running-it-locally-for-nothing)。

---

## 另请参阅

- [选择模型](models.md) — 每家提供商的收费项目
- [配置](configuration.md#agent--how-it-works) — 每一个旋钮
