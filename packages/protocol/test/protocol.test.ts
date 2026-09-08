import assert from "node:assert/strict";
import test from "node:test";

import {
  EVENTS,
  METHODS,
  MODES,
  PROTOCOL_VERSION,
  ProtocolError,
  decode,
  errorEnvelope,
  event,
  request,
  response,
} from "../src/index.ts";

test("a request carries the version it was built with", () => {
  const built = request("1", "session.send", { session_id: "s", text: "hi" });

  assert.equal(built.version, PROTOCOL_VERSION);
  assert.equal(built.type, "request");
  assert.equal(built.method, "session.send");
});

test("a round trip preserves every field", () => {
  const built = request("42", "session.set_mode",
    { session_id: "s", mode: "plan" });
  const read = decode(JSON.stringify(built));

  assert.deepEqual(read, built);
});

test("a response and an error are told apart by type, not by shape", () => {
  assert.equal(decode(JSON.stringify(response("1", { ok: true }))).type,
    "response");
  assert.equal(decode(JSON.stringify(errorEnvelope("1", "not_allowed", "no"))).type,
    "error");
});

test("an error with no id is legal, because a bad line has none", () => {
  const read = decode(JSON.stringify(errorEnvelope(null, "parse_error", "nope")));

  assert.equal(read.type, "error");
  assert.equal(read.id, null);
});

test("a line that is not JSON is refused with parse_error", () => {
  assert.throws(() => decode('{"unclosed"'),
    (problem: ProtocolError) => problem.code === "parse_error");
});

test("an array is not an envelope", () => {
  assert.throws(() => decode("[]"),
    (problem: ProtocolError) => problem.code === "parse_error");
});

test("a version this client does not speak is refused", () => {
  const line = JSON.stringify({ version: 99, type: "response", id: "1", result: {} });

  assert.throws(() => decode(line),
    (problem: ProtocolError) => problem.code === "unsupported_version");
});

test("an unknown envelope type is refused rather than ignored", () => {
  const line = JSON.stringify({ version: PROTOCOL_VERSION, type: "telegram" });

  assert.throws(() => decode(line),
    (problem: ProtocolError) => problem.code === "invalid_envelope");
});

test("a request with no method is refused", () => {
  const line = JSON.stringify(
    { version: PROTOCOL_VERSION, type: "request", id: "1", params: {} });

  assert.throws(() => decode(line),
    (problem: ProtocolError) => problem.code === "invalid_envelope");
});

test("params must be an object, not an array", () => {
  const line = JSON.stringify({
    version: PROTOCOL_VERSION, type: "request", id: "1",
    method: "session.list", params: [],
  });

  assert.throws(() => decode(line),
    (problem: ProtocolError) => problem.code === "invalid_envelope");
});

test("an event name the schema does not have is refused at the source", () => {
  // Otherwise a typo is silent: nothing is delivered and the sender looks
  // like it stopped.
  assert.throws(() => event("message.startd" as never, {}));
});

test("the generated constants are not empty", () => {
  // A generator that silently produced nothing would leave every other test
  // here passing vacuously.
  assert.ok(METHODS.length > 0);
  assert.ok(EVENTS.length > 0);
  assert.deepEqual([...MODES], ["act", "plan", "ask", "chat"]);
});

test("every method the schema names is a string constant", () => {
  for (const method of METHODS) {
    assert.equal(typeof method, "string");
    assert.ok(method.length > 0);
  }
});
