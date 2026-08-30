# Choosing a model

Comodor works with anything that speaks the OpenAI or Anthropic API — seventeen
providers out of the box, plus anything else with a URL.

---

## The short answer

| You want | Choose |
|---|---|
| The easiest start, one key, everything | **OpenRouter** |
| The strongest agentic work | **Anthropic**, `claude-sonnet-5` |
| To pay nothing and stay offline | **Ollama** or **LM Studio** |
| Very cheap, good at code | **DeepSeek** |
| Very fast | **Groq** or **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## Every provider

**Hosted, one key:** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI (Grok) · Mistral · Groq · Cerebras · Moonshot (Kimi) ·
Z.AI (GLM) · Qwen (DashScope) · Together AI · Fireworks · Xiaomi MiMo · B.AI

**On your machine, no key:** Ollama · LM Studio

**Anything else:** choose *Something else* and give it a base URL. Any
OpenAI-compatible endpoint works.

---

## Running it locally, for nothing

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

No key, no cost, no network. A 14B coder model is genuinely usable for
day-to-day work; the difference shows up on long multi-step tasks.

---

## Switching

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

The context gauge follows the model. Switching from a million-token model to a
128k one changes the limit immediately — which matters, because the agent
compacts the conversation at a fraction of it, and a stale limit means it never
compacts and then fails at the provider's real ceiling.

To make a switch permanent: `/save`, or edit
`~/.comodor/config.json`.

---

## Keys

Either place works, and neither is copied to the other:

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

A key in your environment **stays there** — `/save` will not write it to disk.
Exporting rather than saving is a decision, and it is respected.

Comodor's own config file is written with owner-only permissions, and your key
never appears in a log, a transcript, an export, or a traceback.
[Safety](safety.md#your-keys).

---

## The gateway

Route across several providers instead of pinning one.

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

`policy` is `cost`, `speed` or `quality`. A provider that fails three times in a
row is stepped past for a minute. The status line shows `GW: Quality` when it
is on, `GW: Disable` when it is not.

---

## Vision

Some tools return pictures — `browse look`, and every `computer` screenshot.
Those need a model that can see. All the current Claude and GPT-4o family can;
most open models cannot.

If you plan to use [the screen](computer.md), check the model has eyes first, or
it will be handed an image it cannot read and will guess.

---

## What it costs

```
/cost
```

See [Cost](cost.md) for caching, budgets, and why a spend limit sometimes cannot
be enforced.
