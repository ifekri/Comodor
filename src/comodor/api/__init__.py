"""The agent, speaking OpenAI's protocol.

The web interface answers its own page and nobody else. Every chat frontend
written in the last three years — Open WebUI, LobeChat, LibreChat, the chat
panel of an IDE — already speaks one protocol, and it is not ours. Rather than
ask each of them to learn Comodor's shapes, this speaks theirs: a
``POST /v1/chat/completions`` that takes OpenAI messages and answers with an
OpenAI response, streamed or not.

What an OpenAI client cannot say is what an agent is. A chat request is one
question and one answer; Comodor's turn is a loop of model calls, tool runs
and permission prompts that may take minutes and change files. The mapping is
therefore:

* **One request is one whole turn.** The request's text runs through the same
  agent loop the terminal runs, and whatever comes out — after every tool
  round-trip — is folded into a single assistant message. The loop's steps
  are hidden; only the final answer is OpenAI-shaped, capped at
  ``api.max_turns`` steps so the client's own timeout outlives the answer.
* **State lives behind a header, not a session.** OpenAI clients are
  stateless, and stateless is the honest shape: with no header each request
  is its own conversation. ``X-Comodor-Session: <id>`` continues one, and the
  id is echoed in the response body under ``comodor``.
* **The mode comes from the request, not the protocol.** A non-standard
  ``comodor: {"mode": "plan"}`` body field sets act/plan/ask/chat for that
  request; standard clients never send it and are never broken by it.

The security posture is the web server's, restated for an audience of
programs rather than browsers: loopback bind by default, a token compared in
constant time, a body cap, and no TLS — a non-loopback bind prints what it
means before it does it.
"""

from .server import Server, run

__all__ = ["Server", "run"]
