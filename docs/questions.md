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

## Skipping

Sending a form with questions unanswered is fine and it is not the same as
dismissing it. The agent is told exactly which ones you left alone, and that
you have therefore not constrained them — so it decides those itself and says
which way it went.

Dismissing the form entirely (**Not now**, or `escape`) tells the agent to
carry on with sensible defaults and **not to ask again**. A second form put to
somebody who just closed the first is the behaviour that makes a feature like
this hated.

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

The form waits thirty minutes. After that it comes back unanswered and the
agent carries on, so a form left open on a machine nobody is at cannot hold a
run open indefinitely.

## For other models

The tool is called `ask` and it is `SAFE`, which means it is available in Plan
mode too — planning is when ambiguity bites hardest.

How readily a model reaches for it varies. Every model tested asks when the
request plainly needs it and stays quiet when it does not, but if yours is
building on a guess, saying *"ask me about anything you need to decide first"*
in your own message settles it immediately.
