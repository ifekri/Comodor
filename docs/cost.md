# Cost

What a session costs, and how to make it cost less without making it worse.

```
/cost
```

```
  This session      18,422 in · 640 out · $0.031
  Cache             86% of input served from cache · saved ~$0.19
  Brain             812 lessons · 4.2 MB
```

---

## Prompt caching, which is most of it

Every request re-sends the parts that do not change — the system prompt, the
tool schemas, the conversation so far. Providers will re-serve a byte-identical
prefix at about a tenth of the price.

Comodor is built around this, and it is on by default:

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

Measured on real sessions: **86% of input tokens served from cache**.

### Why nothing dynamic goes in the system prompt

Caching only works on a prefix that is byte-identical to last time. The system
prompt *is* the prefix. Anything that changes per turn — recalled lessons, the
matched skill, the time of day — invalidates it, and you pay full price for
everything, every turn.

So recalled lessons ride on the *turn*, as part of the user message. That one
change took the measured cache hit rate from 72% to 87%.

If you add standing instructions of your own, put them in
`agent.system_prompt_extra`, which is stable, rather than varying them.

### The one-hour cache

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

Costs about 25% more to *write* an entry and keeps it an hour instead of five
minutes. Worth it if you return to a session repeatedly; wasteful for a single
burst of work.

---

## Ceilings

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

Whichever comes first stops the task. `stopped` in `--json` says which.

### When the limit cannot fire

**A spend limit only works for a model with a published rate.**

The pricing table deliberately leaves rates unset for models it is not confident
about — inventing a price produces wrong numbers, which is worse than none. For
an unpriced model the cost meter reads zero, so `spent >= max_cost_usd` is never
true and the limit never fires.

Comodor says so rather than letting you believe you are protected:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Said at the start of a session, and in `comodor doctor`:

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

For a model running on your own machine it says something different, because
there it costs nothing to begin with.

---

## What actually costs money

**Screenshots.** About 1,600 visual tokens each at the default budget — and
that again on every turn they stay in the conversation. Comodor keeps the last
two and replaces the rest with a line saying one was there. Without that, a
thirty-step desktop task carries close to fifty thousand tokens of pixels
describing screens that have since been clicked.

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

Do not set `screenshot_tokens` too low. A picture the model cannot read is worse
than no picture: it guesses instead of asking. See
[Using your screen](computer.md#screenshots-and-what-they-cost).

**Large tool output.** Bounded by `agent.max_tool_chars`. What does not fit is
written to a file the model is told how to read, so it pays only if it looks.

**Reflection.** One model call at the end of a task. Point it at a cheaper
model:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Or switch it off. The free lane — corrections, rules, announcements — keeps
working either way. [How it learns](learning.md#the-two-lanes).

**The browser, when it looks.** `browse` returns text by default and a
screenshot only when asked, because a picture of a page costs the same every
time and cannot be trimmed.

---

## Spending nothing

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

Everything in this documentation works, at no cost, except where it says
otherwise. [Choosing a model](models.md#running-it-locally-for-nothing).

---

## See also

- [Choosing a model](models.md) — what each provider charges for
- [Configuration](configuration.md#agent--how-it-works) — every knob
