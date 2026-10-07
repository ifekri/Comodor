/**
 * T041: forms and permissions (FR-015). Nothing is sent without the person's
 * action, an answer is exactly the selection, and the card stays until the
 * Core says the request is resolved.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { openWindow } from "./fake-native.ts";
import { byText, click, render, type Rendered, typeInto, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function open() {
  return openWindow(async (n) => {
    rendered = await render(<App api={n.api} />);
    return rendered;
  }, until);
}

const S = "s1";

const FORM = {
  id: "q1", session_id: S, title: "A decision",
  questions: [{
    header: "Database", prompt: "Which database should this use?", multiple: false,
    options: [
      { id: "o1", label: "SQLite" },
      { id: "o2", label: "PostgreSQL", description: "a server" },
      { id: "o3", label: "Something else", free: true },
    ],
  }],
};

describe("a form", () => {
  test("shows every option, with the write-your-own row as a text field", async () => {
    const { native, container } = await open();
    native.core.emit("question.requested", FORM);
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="form"]'), "the form");
    expect(card.textContent).toContain("Which database should this use?");
    expect(byText(card, "button", "SQLite")).not.toBeNull();
    expect(byText(card, "button", "PostgreSQL")).not.toBeNull();
    expect(card.querySelector('input[type="text"]')).not.toBeNull();
    expect(native.core.requests("question.answer")).toEqual([]);
  });

  test("the answer is exactly the selection, sent only on the person's action", async () => {
    const { native, container } = await open();
    native.core.emit("question.requested", FORM);
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="form"]'), "the form");
    await click(byText(card, "button", "PostgreSQL")!);
    expect(native.core.requests("question.answer")).toEqual([]);
    await click(byText(card, "button", "Answer")!);
    await until(() => native.core.requests("question.answer").length === 1, "the answer");
    expect(native.core.requests("question.answer")[0]!.params)
      .toEqual({ id: "q1", answers: [{ header: "Database", chosen: ["o2"] }] });
  });

  test("written text travels as written", async () => {
    const { native, container } = await open();
    native.core.emit("question.requested", FORM);
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="form"]'), "the form");
    await typeInto(card.querySelector('input[type="text"]')!, "DuckDB");
    await click(byText(card, "button", "Answer")!);
    await until(() => native.core.requests("question.answer").length === 1, "the answer");
    const sent = native.core.requests("question.answer")[0]!.params;
    expect(sent["answers"]).toEqual([{ header: "Database", chosen: ["o3"], written: "DuckDB" }]);
  });

  test("an answered form stays until question.resolved", async () => {
    const { native, container } = await open();
    native.core.emit("question.requested", FORM);
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="form"]'), "the form");
    await click(byText(card, "button", "SQLite")!);
    await click(byText(card, "button", "Answer")!);
    await until(() => native.core.requests("question.answer").length === 1, "the answer");
    expect(container.querySelector('[data-testid="form"]')).not.toBeNull();
    native.core.emit("question.resolved", { id: "q1", session_id: S, answers: [] });
    await until(() => container.querySelector('[data-testid="form"]') === null, "the form to go");
  });

  test("a dismissal is sent as cancelled", async () => {
    const { native, container } = await open();
    native.core.emit("question.requested", FORM);
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="form"]'), "the form");
    await click(byText(card, "button", "Dismiss")!);
    await until(() => native.core.requests("question.answer").length === 1, "the dismissal");
    expect(native.core.requests("question.answer")[0]!.params).toEqual({ id: "q1", cancelled: true });
  });
});

describe("a permission", () => {
  test("shows allow, allow_always and deny, and the reply is the choice", async () => {
    const { native, container } = await open();
    native.core.emit("permission.requested", {
      id: "p1", session_id: S, title: "Write out.txt", detail: "hello",
      options: ["allow", "allow_always", "deny"], tool: "write_file", risk: "write",
    });
    const card = await until(() => container.querySelector<HTMLElement>('[data-testid="permission"]'), "the card");
    expect(card.textContent).toContain("write_file");
    expect(card.textContent).toContain("write");
    const labels = [...card.querySelectorAll("button")].map((button) => button.dataset["choice"]);
    expect(labels).toEqual(["allow", "allow_always", "deny"]);
    expect(native.core.requests("permission.reply")).toEqual([]);
    await click(card.querySelector('button[data-choice="deny"]')!);
    await until(() => native.core.requests("permission.reply").length === 1, "the reply");
    expect(native.core.requests("permission.reply")[0]!.params).toEqual({ id: "p1", choice: "deny" });
    await click(card.querySelector('button[data-choice="allow"]')!);
    expect(native.core.requests("permission.reply").length).toBe(1);
  });
});
