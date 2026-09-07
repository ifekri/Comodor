/**
 * The Comodor protocol, in TypeScript.
 *
 * `generated.ts` beside this file is written by `tools/protocol-codegen.py`
 * from `schemas/protocol/v1.json` — the same run that writes the Python types.
 * Nothing in it is edited by hand, and a test regenerates both and fails on a
 * difference. That is the whole of the claim that the two sides cannot drift.
 *
 * This file is what is *not* generated: the four envelope builders and the
 * reader, which are small enough that generating them would cost more than it
 * saved and clear enough that they are worth reading.
 *
 * No dependencies, and nothing about a pipe. `@comodor/client` moves these;
 * a future WebSocket moves the same objects.
 */

export * from "./generated.ts";

import {
  PROTOCOL_VERSION,
  EVENTS,
  type Envelope,
  type ErrorEnvelope,
  type ErrorCode,
  type EventEnvelope,
  type EventName,
  type Method,
  type RequestEnvelope,
  type ResponseEnvelope,
} from "./generated.ts";

/** A refusal with a code the other side can branch on. */
export class ProtocolError extends Error {
  readonly code: ErrorCode | string;
  readonly data: Record<string, unknown>;

  constructor(code: ErrorCode | string, message: string,
              data: Record<string, unknown> = {}) {
    super(message || code);
    this.name = "ProtocolError";
    this.code = code;
    this.data = data;
  }
}

export function request(
  id: string, method: Method, params: Record<string, unknown> = {},
): RequestEnvelope {
  return { version: PROTOCOL_VERSION, type: "request", id, method, params };
}

export function response(
  id: string, result: Record<string, unknown> = {},
): ResponseEnvelope {
  return { version: PROTOCOL_VERSION, type: "response", id, result };
}

export function errorEnvelope(
  id: string | null, code: ErrorCode | string, message: string,
  data?: Record<string, unknown>,
): ErrorEnvelope {
  return {
    version: PROTOCOL_VERSION,
    type: "error",
    id,
    error: data === undefined ? { code, message } : { code, message, data },
  };
}

export function event(
  name: EventName, params: Record<string, unknown> = {},
): EventEnvelope {
  if (!(EVENTS as readonly string[]).includes(name)) {
    // A typo in an event name is otherwise invisible: nothing is delivered
    // and the sender looks like it stopped.
    throw new ProtocolError("invalid_envelope", `unknown event ${name}`);
  }
  return { version: PROTOCOL_VERSION, type: "event", event: name, params };
}

/**
 * One line of wire text into an envelope.
 *
 * Throws rather than returning a sentinel: every caller has to do something
 * different about a malformed line, and a sentinel makes forgetting the
 * default.
 */
export function decode(line: string): Envelope {
  let raw: unknown;
  try {
    raw = JSON.parse(line);
  } catch (problem) {
    throw new ProtocolError("parse_error",
      `not JSON: ${(problem as Error).message}`);
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new ProtocolError("parse_error", "top level is not an object");
  }

  const body = raw as Record<string, unknown>;
  if (body["version"] !== PROTOCOL_VERSION) {
    throw new ProtocolError("unsupported_version",
      `this client speaks protocol ${PROTOCOL_VERSION}, `
      + `not ${JSON.stringify(body["version"])}`);
  }

  switch (body["type"]) {
    case "request":
      requireString(body, "id");
      requireString(body, "method");
      requireObject(body, "params");
      return body as unknown as RequestEnvelope;
    case "response":
      requireString(body, "id");
      requireObject(body, "result");
      return body as unknown as ResponseEnvelope;
    case "error": {
      if (!("id" in body)) throw new ProtocolError("invalid_envelope", "error is missing id");
      const detail = body["error"];
      if (typeof detail !== "object" || detail === null
          || typeof (detail as Record<string, unknown>)["code"] !== "string") {
        throw new ProtocolError("invalid_envelope", "error must carry a code");
      }
      return body as unknown as ErrorEnvelope;
    }
    case "event":
      requireString(body, "event");
      requireObject(body, "params");
      return body as unknown as EventEnvelope;
    default:
      throw new ProtocolError("invalid_envelope",
        `unknown envelope type ${JSON.stringify(body["type"])}`);
  }
}

function requireString(body: Record<string, unknown>, key: string): void {
  if (typeof body[key] !== "string" || body[key] === "") {
    throw new ProtocolError("invalid_envelope",
      `${key} must be a non-empty string`);
  }
}

function requireObject(body: Record<string, unknown>, key: string): void {
  const value = body[key];
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProtocolError("invalid_envelope", `${key} must be an object`);
  }
}
