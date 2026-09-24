# Questions

Ambiguity has two bad endings. The agent picks a reading, builds the wrong
thing, and costs you a review cycle. Or it asks in prose, one question at a
time, and you spend four turns settling what could have been settled in one
screen.

Comodor takes a third route. When a request can be read more than one way, the
agent works out *everything* it is unsure about first, then puts it to you as a
short multiple-choice form — three or four questions, answered in about fifteen
seconds, before a line is written.

Asked for "add rate limiting to the web server", it read ten files and then
asked this:

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

Note the second line of the first option. It had read `web/server.py` before it
asked, and the question is about the decision that reading could not settle.

## In the terminal

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

The tab strip carries a mark per question, so you can see at a glance which
ones are still outstanding without visiting each.

## In the browser

The same form as a dialog. Click the tabs or use the arrow keys, click an
option, and press **Send**. `Escape` closes it.

## The last row

Every question ends with **Something else** and a box to type in. It is added
by Comodor, not by the model, and the model cannot remove it — the whole point
of the row is that it covers what the model failed to think of. Typing in it
replaces whatever option was selected, and picking an option clears what was
typed, so a question never comes back with two conflicting answers.

## Answering, skipping and dismissing

Only an answer settles a material question. Everything else leaves the
decision open, and the agent never fills it in itself.

Answering a question resumes the dependent work. That is the one path that
lets the agent carry on.

A **material** question you leave blank is a decline: the decision is recorded
as unresolved, and no work that depends on it runs. A **non-material** question
you leave blank is the agent's to settle, and it says which way it went.

**Dismissing** the form entirely (**Not now**, or `escape`) cancels the
clarification. The decision stays unresolved, the agent is told so, dependent
work does not run, and the same question is not put to you again within that
attempt. It is not the same as cancelling the whole agent turn — the turn
reports that it stopped because a decision is still needed, not that you
stopped it.

The distinction is reported as a `clarification.outcome`:

| Outcome | What happened | What runs next |
| --- | --- | --- |
| *(answered)* | You answered | The dependent work resumes |
| `cancelled` | You dismissed it, or declined a material question | Nothing dependent; the decision is still needed |
| `expired` | The form waited out its thirty minutes | Nothing dependent; the decision is still needed |
| `unattended` | Nobody was listening (headless, background, a scheduled run) | Nothing dependent; the turn reports the needed decision |

A dismissed question is **never** reported as a cancelled turn, and an
expired form is never reported as cancelled — they are different events with
different next steps.

## When it cannot ask

On a surface with nobody to answer — `comodor run` without an interactive
terminal, a scheduled job, a background delegate — a mandatory clarification
does not fall back to a guess. The turn ends reporting that the decision is
needed (`stopped: "clarification_required"`), with no invented value, no
selected option and no default applied.

## Answering later

Every question the agent asks belongs to a decision with a stable
`decision_ref`: it is the same for as long as the decision is open, and the
same when the decision is asked again. A decision left open — dismissed,
expired or unattended — can be answered later by that ref alone, never by
wording, by recency or by position:

- `comodor run --decision-answers` resumes a headless run, a scheduled job or
  a webhook event that stopped for a decision (see [the CLI](cli.md)). It must
  be resumed from the same workspace and in the same mode.
- The API takes `comodor.decision_answers` on the same session.
- ACP takes it in a prompt's `_meta.comodor.decision_answers`.
- Telegram, Slack and WhatsApp offer answer buttons when a turn stops.
  Discord and webhooks name the decision and its ref, and offer no answer
  route of their own.

Answers are checked whole before anything runs. An answer supplies
information; it never grants a permission the mode does not allow.

## When it does not ask

By design, not by accident:

- Anything it could find out by reading the project. It reads first.
- Permission to proceed. That is what the approval prompt is for.
- Confirming its plan back to you.
- A decision with an obvious default. It takes the default and tells you it
  did.

## Limits

At most four questions, and at most four options each — plus the write-your-own
row, which does not use up one of the four. More than that stops being a quick
form and becomes an interview, and an agent that needs six answers should ask
for the four that matter and work out the rest.

The form waits thirty minutes. After that it comes back with the `expired`
outcome and the decision still open — a form left open on a machine nobody is
at cannot hold a run open indefinitely, and it cannot decide anything either.

## For other models

The tool is called `ask` and it is `SAFE`, which means it is available in Plan
mode too — planning is when ambiguity bites hardest.

How readily a model reaches for it varies. Every model tested asks when the
request plainly needs it and stays quiet when it does not, but if yours is
building on a guess, saying *"ask me about anything you need to decide first"*
in your own message settles it immediately.
