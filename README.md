<div align="center">

# Comodor

<img src=".github/header.svg" alt="Comodor" width="640">

**Terminal · Web · Headless · ACP · Telegram · Slack · WhatsApp · Local Models**

[![PyPI](https://img.shields.io/pypi/v/comodor?label=PyPI&color=0A7AFF)](https://pypi.org/project/comodor/)
[![Python](https://img.shields.io/pypi/pyversions/comodor?label=Python)](https://pypi.org/project/comodor/)
[![CI](https://github.com/ifekri/Comodor/actions/workflows/ci.yml/badge.svg)](https://github.com/ifekri/Comodor/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/comodor?label=License)](LICENSE)

[![Windows](./.github/badget/install.svg "Install Comodor")]()
[![macOS](./.github/badget/mac-linux.svg "Install Comodor on macOS")](#linux--macos)
[![Windows](./.github/badget/win.svg "Install Comodor on Windows")](#windows)
[![Install Comodor with UV](./.github/badget/uv.svg)](#uv 'Install Comodor with UV')
[![Install Comodor with PIP](./.github/badget/pip.svg)](#pip 'Install Comodor with PIP')
[![Install Comodor with PIPX](./.github/badget/pipx.svg)](#pipx 'Install Comodor with PIPX')

[![](./.github/badget/doc.svg)]()
[![English Documentation](./.github/badget/en.svg "English")](docs/README.md)
[![Persian Documentation](./.github/badget/fa.svg "Persian")](docs/FA/README.md)
[![Arabic Documentation](./.github/badget/ar.svg "Arabic")](docs/AR/README.md)
[![Turkish Documentation](./.github/badget/tr.svg "Turkish")](docs/TR/README.md)
[![German Documentation](./.github/badget/de.svg "German")](docs/DE/README.md)
[![Spanish Documentation](./.github/badget/es.svg "Spanish")](docs/ES/README.md)
[![French Documentation](./.github/badget/fr.svg "French")](docs/FR/README.md)
[![Russian Documentation](./.github/badget/ru.svg "Russian")](docs/RU/README.md)
[![Chinese Documentation](./.github/badget/zh.svg "Chinese")](docs/ZH/README.md)

---

</div>

### The Agent. Many Algorithms. Your Way.

**Comodor is an open-source coding agent built to understand the project before changing it, coordinate specialized work when a task demands it, learn from verified corrections, and keep uncertainty explicit instead of turning it into code.**

---

## Built to understand before it acts

Writing code is no longer the difficult part.

The difficult part is deciding **what should be written**, which repository facts are trustworthy, what can be derived from the project itself, when another specialist should be involved, and when the missing decision belongs to the user.

Comodor is designed around that boundary.

It inspects the repository before making material decisions, distinguishes verified evidence from assumptions, preserves unresolved information as unresolved, and asks only when the project cannot answer the question itself.

<div align="center">

<img src="/.github/Chart-Request.svg" alt="Requst Chart - Comodor Chart Map."/>

</div>

The goal is not to make the agent sound certain.

The goal is to make its decisions defensible.

---

## What defines Comodor

|                                  |                                                                                                                                                                |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Evidence before assumption**   | Repository facts are verified before they become working assumptions. Material unknowns remain unknown until they are resolved.                                |
| **Clarification with restraint** | Comodor investigates first and asks only when a decision genuinely cannot be recovered from code, configuration, project knowledge, or deterministic evidence. |
| **Progressive learning**         | Verified corrections, accepted decisions, successful outcomes, terminology and project conventions can become reusable knowledge with provenance and scope.    |
| **Multi-agent execution**        | Complex work can be delegated to additional agent loops and background specialists instead of forcing every responsibility through one execution path.         |
| **Efficient context**            | Stable context is reused, repeated material is deduplicated and relevant evidence is selected instead of continuously resending the entire project.            |
| **Completion integrity**         | Partial work is allowed to remain partial. Comodor does not promote an unresolved result to “done” simply because the model produced a final answer.           |
| **Permission-aware execution**   | Repository writes, commands and external actions remain subject to explicit capabilities, modes and authorization boundaries.                                  |
| **Model independence**           | Hosted models, local runtimes and compatible endpoints can use the same agent architecture without coupling Comodor to one provider.                           |

Comodor works with sixteen hosted providers and three local runtimes, and any OpenAI-compatible endpoint can be added as well.

---

## Grounded before action

Model output is not repository truth.

Comodor tracks the difference between information that was supplied, information that was verified, information derived from established project knowledge, and information that is still unknown.

```text
User supplied
Verified from repository
Established project knowledge
Deterministically derived
Unknown
```

That distinction controls behavior.

If a function has not been verified, Comodor should not claim it exists.

If a required value is missing, it should not manufacture one.

If the repository already provides the answer, it should not interrupt the user to ask for it again.

### When clarification is actually required

A material decision is clarified only after the available evidence has been exhausted.

Multiple-choice clarification always preserves a manual path:

```text
○ Use the existing implementation
○ Introduce a new implementation
○ Keep current behavior
○ Other — enter a custom answer
```

A cancelled question is not an answer.

An expired question is not an answer.

And when nobody is available to answer a required clarification, dependent execution stops instead of silently selecting the most convenient option.

This behavior applies consistently across interactive and non-interactive surfaces.

---

## Multi-agent by architecture

Comodor is not limited to a single execution loop.

Its delegation architecture can create additional agent loops with their own conversation, tool registry and permission context. Background delegates can run concurrently while the parent continues its own work.

That makes it possible to decompose complex work into focused responsibilities such as:

```text
Primary Agent
   │
   ├── Backend Investigation
   ├── Security Review
   ├── Test Analysis
   └── Packaging / Deployment Review
```

The important part is that delegation is controlled.

A delegated agent does not automatically inherit every capability of its parent. Cancellation propagates deliberately. Background work has bounded concurrency. Results return through defined turn boundaries instead of being injected unpredictably into an active conversation.

Comodor prefers a single execution path when one is enough.

Additional agents are useful when specialization, isolation, parallel investigation, or background execution provides a real benefit — not simply because more agents look more impressive.

---

## It learns from evidence, not from confidence

A useful coding agent should become more aligned with a project over time.

But learning every statement a model generates would make memory less reliable, not more.

Comodor admits durable knowledge from stronger signals such as:

* explicit user corrections;
* accepted decisions;
* verified repository conventions;
* validated successful fixes;
* repeated project terminology;
* confirmed architectural patterns;
* successful outcomes supported by evidence.

It does **not** automatically promote:

* speculative model output;
* failed implementations;
* rejected suggestions;
* untrusted retrieved text;
* arbitrary tool output;
* unsupported conclusions.

Learned information retains enough context to answer:

```text
Where did this come from?
Which project does it belong to?
Is it still valid?
What replaced it?
Should it influence this task?
```

Knowledge derived from one project does not silently leak into another.

Repository-derived knowledge can become stale when the source changes.

Later evidence can supersede earlier knowledge without replaying the entire conversation history.

```text
◈ learned  naming.functions
  Prefer snake_case for internal Python functions.

◈ learned  architecture.http
  Reuse the existing HTTP transport instead of introducing another client.

◈ superseded  tests.fixtures
  Project fixtures now live under tests/fixtures/.
```

Use:

```bash
comodor insights
```

to inspect how project learning is affecting repeated work.

---

## Less context. More signal.

Sending an entire repository repeatedly is not a context strategy.

Comodor's context pipeline is designed to preserve the information that matters while reducing repeated transmission of information that has not changed.

Depending on the task, that can include:

* relevance-based retrieval;
* context budgets;
* stable-context reuse;
* content-addressed caching;
* deduplication;
* delta context;
* compact tool results;
* canonical summaries;
* selective expansion;
* reusable project knowledge.

The constraint is non-negotiable:

> **Token savings are useful only while result quality remains intact.**

A cheaper answer that becomes less correct is a regression.

Context optimizations are evaluated against baselines together with correctness, validation success and user correction rate.

Benchmarks are not weakened to manufacture attractive percentages.

[Read about cost and context →](docs/cost.md)

---

## Built for real software work

Comodor is an agent runtime, not a prompt wrapper around a shell.

### Codebase engineering

Inspect, search, modify, test and reason across real repositories while preserving project conventions and existing architecture.

### Browser automation

Drive a real browser with JavaScript execution, cookies and authenticated state when Web interaction is part of the task.

[Browser automation →](docs/browser.md)

### Computer use

Interact with applications through screen, pointer and keyboard tooling when repository-level automation is not enough.

[Computer use →](docs/computer.md)

### Delegation and background work

Split appropriate tasks into additional agent executions, keep background work bounded and deliver results through explicit lifecycle boundaries.

### Local models

Use supported local runtimes for offline, private or self-hosted workflows.

[Local models →](docs/local-models.md)

### Editor integration

Comodor speaks ACP so compatible development environments can communicate with the same underlying agent runtime.

[ACP integration →](docs/acp.md)

### Skills

Load reusable procedures only when they match the work being performed rather than permanently expanding every prompt.

[Skills →](docs/skills.md)

### Messaging channels

Continue supported workflows through Telegram, Slack or WhatsApp while preserving project context and permission boundaries.

[Telegram](docs/telegram.md) · [Slack](docs/slack.md) · [WhatsApp](docs/whatsapp.md)

---

## One runtime, multiple surfaces

Comodor's behavior is not tied to one interface.

| Surface                         | Use it for                             |
| ------------------------------- | -------------------------------------- |
| **Terminal UI**                 | Full interactive development sessions  |
| **Web UI**                      | Browser-based project work             |
| **Headless CLI**                | Automation, scripts and one-shot tasks |
| **ACP**                         | Editor-native agent workflows          |
| **Telegram / Slack / WhatsApp** | Remote and asynchronous interaction    |
| **Local runtime**               | Work with locally hosted models        |

The interface can change without replacing the underlying project model.

Evidence, learning, permissions, sessions and clarification behavior belong to the runtime rather than to a particular frontend.

---

## Safety is part of the runtime

Observation and mutation are different operations.

Reading a repository is not equivalent to modifying it. Inspecting a command is not equivalent to executing it. A messaging integration does not automatically inherit every capability available to an interactive local session.

Comodor's permission model keeps these boundaries explicit.

Among other things:

* repository inspection can remain non-destructive;
* writes can require authorization;
* shell execution is independently controlled;
* unknown modes fail closed;
* capabilities remain surface- and mode-aware;
* clarification capability does not imply unrelated tool access;
* delegated work receives its own permission context;
* unresolved decisions do not become implicit authorization.

[Safety and permissions →](docs/safety.md)

---

## Measured, not narrated

Agent quality is easy to claim.

It is harder to measure.

Comodor includes a benchmark harness for evaluating work against real repositories with executable checks instead of relying only on subjective output review.

The benchmark system can evaluate:

* whether the requested change actually works;
* whether existing behavior remains intact;
* how often clarification was required;
* whether unnecessary clarification decreased over repeated work;
* whether user corrections decreased;
* how much context was consumed;
* whether context optimizations preserved quality;
* whether learning improved subsequent tasks.

Benchmark scenarios are treated as test assets.

They are not weakened to improve a score.

```bash
python -m bench
```

Methodology and recorded benchmark results are maintained under [`bench/`](bench/README.md).

---

## Install

### Linux & macOS

```bash
curl -fsSL get.comodor.ai | sh
```

### Windows

```powershell
irm get.comodor.ai | iex
```

### Package managers

Comodor requires **Python 3.11+**.

#### uv

```bash
uv tool install comodor
```

#### pipx

```bash
pipx install comodor
```

#### pip

```bash
pip install comodor
```

The Python package keeps its runtime dependency footprint deliberately small.

The interactive terminal interface uses **Bun**. When the terminal renderer is unavailable, headless and Web workflows remain available.

---

## Docker

Run Comodor and its browser environment inside a container:

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor

export ANTHROPIC_API_KEY=...
docker compose up
```

The container exposes the browser interface and operates against the mounted project workspace.

Or run the image directly:

```bash
docker run --rm -it \
  -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ifekri/comodor:latest
```

The same image is also published through GitHub Container Registry as:

```text
ghcr.io/ifekri/comodor:latest
```

[Docker documentation →](docs/docker.md)

---

## Start working

Launch the terminal interface:

```bash
comodor
```

Run one task without the interactive interface:

```bash
comodor run "fix the failing tests"
```

Open the browser interface:

```bash
comodor web
```

Inspect the installation:

```bash
comodor doctor
```

Use Comodor from an ACP-compatible editor:

```bash
comodor acp
```

Start a messaging integration:

```bash
comodor telegram start
```

### Useful terminal controls

```text
Tab       switch act / plan / ask
Ctrl+K    command palette
Ctrl+B    tasks and agents
End       jump to newest output
Ctrl+C    stop current work
```

---

## Models are replaceable. The runtime is not.

Comodor is designed around a model abstraction rather than a single provider.

It can work with:

* hosted model providers;
* supported local runtimes;
* OpenAI-compatible endpoints.

The model can change without replacing the rest of the agent architecture.

Sessions, tools, permissions, learning, context management and orchestration remain part of Comodor.

[Model configuration →](docs/models.md)

No API key available?

```bash
comodor --demo
```

Or configure a supported local model.

---

## Your project should shape the agent

Comodor is not intended to impose one universal development style on every repository.

Its behavior can be shaped by:

* repository instructions;
* project configuration;
* verified conventions;
* progressive learning;
* skills;
* permissions;
* operating mode;
* explicit decisions;
* available tools and model capabilities.

A Python backend and a TypeScript frontend should not inherit the same assumptions merely because the same agent happens to work on both.

And one project's learned conventions should not silently become another project's rules.

---

## Documentation

### Start here

| Documentation                                  |                                                |
| ---------------------------------------------- | ---------------------------------------------- |
| [Getting started](docs/getting-started.md)     | Installation, configuration and the first task |
| [Interface](docs/interface.md)                 | TUI panels, controls and commands              |
| [Questions & clarification](docs/questions.md) | How unresolved decisions are handled           |
| [Learning](docs/learning.md)                   | Corrections, provenance and project knowledge  |
| [Tools](docs/tools.md)                         | Agent capabilities and execution tools         |
| [Models](docs/models.md)                       | Hosted, local and compatible endpoints         |
| [Configuration](docs/configuration.md)         | Settings and precedence                        |
| [Safety](docs/safety.md)                       | Permissions and trust boundaries               |
| [Cost & context](docs/cost.md)                 | Context efficiency and model usage             |
| [Browser](docs/browser.md)                     | Browser automation                             |
| [Computer use](docs/computer.md)               | Screen, pointer and keyboard control           |
| [ACP](docs/acp.md)                             | Editor integration                             |
| [Docker](docs/docker.md)                       | Containerized operation                        |
| [Troubleshooting](docs/troubleshooting.md)     | Diagnostics and common problems                |

Full documentation:

**[docs/README.md →](docs/README.md)**

---

## Architecture

Comodor keeps model reasoning separate from the runtime responsible for execution.

At a high level:

```text
                               ┌─────────────────┐
                               │      User       │
                               └────────┬────────┘
                                        │
                                        ▼
                             ┌─────────────────────┐
                             │ Session / Interface │
                             └──────────┬──────────┘
                                        │
                                        ▼
                           ┌─────────────────────────┐
                           │ Context + Project State │
                           └───────────┬─────────────┘
                                       │
                      evidence         │         learned knowledge
                  ┌────────────────────┴────────────────────┐
                  ▼                                         ▼
          ┌────────────────┐                       ┌─────────────────┐
          │ Primary Agent  │◄─────────────────────│ Project Memory  │
          └───────┬────────┘                       └─────────────────┘
                  │
        ┌─────────┴──────────┐
        │                    │
        ▼                    ▼
 ┌─────────────┐      ┌─────────────────┐
 │ Tools / ASK │      │ Delegated Agents│
 └──────┬──────┘      └────────┬────────┘
        │                      │
        └──────────┬───────────┘
                   ▼
        ┌───────────────────────┐
        │ Repository / External │
        │ Systems / Applications│
        └───────────────────────┘
```

The model reasons.

The runtime owns execution.

Permissions, sessions, persistence, clarification, delegation, tools and protocol behavior remain controlled outside the model itself.

[Architecture →](docs/architecture.md)

---

## Development

Clone the repository:

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
```

Create an environment and install development dependencies:

```bash
uv venv
uv pip install -e ".[dev]"
```

Run the Python suite:

```bash
uv run pytest -q
```

Run linting:

```bash
uv run ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## Engineering principles

Several rules are intentionally more important than individual implementation choices.

**Evidence before assumption.**
If a material fact is unknown, verify it or ask. Do not hide uncertainty behind a plausible answer.

**Inspect before asking.**
A repository question should be answered from the repository whenever possible.

**Quality before token savings.**
Reducing context is valuable only while correctness, completion and validation remain intact.

**Learning requires provenance.**
Model confidence does not turn information into durable project knowledge.

**Existing architecture before new architecture.**
New capabilities extend the system instead of quietly duplicating responsibilities.

**Specialize when specialization helps.**
Additional agents are useful when they create measurable value, not simply because multi-agent execution is available.

**User control for consequential actions.**
Ambiguity is not permission.

These principles are what make the individual capabilities operate as one system instead of a collection of unrelated features.

---

## License

Comodor is released under the [MIT License](LICENSE).

For security issues, follow [SECURITY.md](SECURITY.md) rather than opening a public issue.

---

<div align="center">

### The Agent. Many Algorithms. Your Way.

[Website](https://comodor.ai) ·
[Documentation](docs/README.md) ·
[Issues](https://github.com/ifekri/Comodor/issues) ·
[Changelog](CHANGELOG.md)

</div>
