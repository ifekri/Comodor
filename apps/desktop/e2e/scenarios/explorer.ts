/**
 * D3a in the real WebView, over the real Core: the EXPLORER tree, paging,
 * refusals, and the read-only CodeMirror viewer — its colours under the
 * unchanged CSP and freezePrototype, a key typed into it, its line ending and
 * BOM facts — with accessibility checked and every CSP violation recorded.
 * The setup plants a credential canary in the Core's home; the scenario also
 * checks that a workspace `.env` value never reaches the page.
 */

import { accessibilityViolations, expect, type Scenario, type ScenarioContext } from "../runner.ts";

type Data = Record<string, unknown>;

const ENV_SECRET = "ENV-SECRET-D3A-7f3c91";
const TOKEN = "ghp_D3aSpikeTokenAbCdEfGhIjKlMnOp1234";

function frames(count: number): Promise<void> {
  return new Promise((resolve) => {
    let left = count;
    const step = () => (--left <= 0 ? resolve() : requestAnimationFrame(step));
    requestAnimationFrame(step);
  });
}

function hex(rgb: string): string {
  const parts = rgb.match(/\d+/g)?.slice(0, 3).map(Number) ?? [];
  return parts.length === 3 ? `#${parts.map((n) => n.toString(16).padStart(2, "0")).join("")}` : rgb;
}

async function row(context: ScenarioContext, path: string): Promise<HTMLElement> {
  return context.element(`[role="tree"] [data-path="${path}"]`);
}

async function open(context: ScenarioContext, path: string): Promise<HTMLElement> {
  (await row(context, path)).click();
  return context.waitFor(() => {
    const view = document.querySelector<HTMLElement>(`[data-testid="file-view"][data-path="${path}"]`);
    return view && view.dataset["state"] !== "reading" ? view : null;
  });
}

async function expand(context: ScenarioContext, path: string): Promise<void> {
  const folder = await row(context, path);
  if (folder.getAttribute("aria-expanded") !== "true") folder.click();
  await context.waitFor(() => document.querySelector(`[role="tree"] [data-path^="${path}/"]`));
}

export const explorer: Scenario = async (context) => {
  const violations: Array<{ directive: string; phase: string }> = [];
  let phase = "load";
  document.addEventListener("securitypolicyviolation", (event) => {
    violations.push({ directive: event.effectiveDirective || event.violatedDirective, phase });
  });
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  const result: Data = {};

  // The tree, as the real Core lists the workspace.
  phase = "tree";
  const tabs = [...document.querySelectorAll<HTMLButtonElement>('[data-testid="sidebar"] [role="tab"]')];
  tabs.at(-1)!.click();
  await context.element('[role="tree"] [data-path="src"]');
  const top = [...document.querySelectorAll<HTMLElement>('[role="tree"] > [data-path]')].map((r) => r.dataset["path"]);
  expect(JSON.stringify(top) === JSON.stringify(["big", "media", "notes", "src", ".env"]),
         `the root lists folders first, then files: ${JSON.stringify(top)}`);
  const env = await row(context, ".env");
  expect(env.dataset["refused"] === "sensitive_name" && env.getAttribute("aria-disabled") === "true",
         ".env is listed locked");
  result["root"] = top;

  // Paging: 600 entries, 500 at first, then the rest once.
  phase = "paging";
  await expand(context, "big");
  const count = () => document.querySelectorAll('[role="tree"] [data-path^="big/"]').length;
  await context.waitFor(() => count() === 500);
  (await context.element('[data-testid="explorer-more"]')).click();
  await context.waitFor(() => count() === 600);
  const paths = [...document.querySelectorAll<HTMLElement>('[role="tree"] [data-path^="big/"]')].map((r) => r.dataset["path"]);
  expect(new Set(paths).size === 600 && document.querySelector('[data-testid="explorer-more"]') === null,
         "600 unique entries after one Show more, and no more to show");
  (await row(context, "big")).click();
  await context.waitFor(() => count() === 0);
  result["paging"] = { first: 500, total: 600 };

  // A TypeScript file in the viewer: CodeMirror in a shadow root.
  phase = "view";
  await expand(context, "src");
  const started = context.now();
  const view = await open(context, "src/app.ts");
  expect(view.dataset["state"] === "text", "src/app.ts opens as text");
  const host = view.querySelector<HTMLElement>('[data-testid="file-code"]')!;
  const shadow = host.shadowRoot!;
  await context.waitFor(() => [...shadow.querySelectorAll(".cm-line span")].some((s) => s.textContent === "export"));
  await frames(2);
  const keyword = [...shadow.querySelectorAll<HTMLElement>(".cm-line span")].find((s) => s.textContent === "export")!;
  const expected = getComputedStyle(document.documentElement).getPropertyValue("--text-keyword").trim().toLowerCase();
  const facts = view.querySelector('[data-testid="file-facts"]')!.textContent ?? "";
  result["view"] = {
    openMs: Math.round(context.now() - started), lines: shadow.querySelectorAll(".cm-line").length,
    keywordColour: hex(getComputedStyle(keyword).color), expected, facts,
    adoptedSheets: shadow.adoptedStyleSheets.length,
    readonly: shadow.querySelector(".cm-content")?.getAttribute("aria-readonly"),
  };
  expect(hex(getComputedStyle(keyword).color) === expected, `the keyword is coloured ${expected}`);
  expect(facts.includes("TypeScript") && facts.includes("LF") && facts.includes("Read-only"), `facts: ${facts}`);
  const shot = await context.checkpoint("screenshot", { name: "explorer-viewer" });
  result["screenshot"] = shot["shot"] ?? null;

  // A key typed into the read-only viewer changes nothing and trips no CSP.
  phase = "typing";
  const before = shadow.querySelector(".cm-content")!.textContent;
  (shadow.querySelector(".cm-content") as HTMLElement).focus();
  const gate = await context.checkpoint("os-level");
  const preflight = gate["preflight"] as { ok: boolean; outcome?: string } | undefined;
  if (preflight?.ok) {
    await context.checkpoint("focus-window");
    (shadow.querySelector(".cm-content") as HTMLElement).focus();
    const sent = await context.checkpoint("press-keys", { key: { key: "q" } as unknown as Data });
    await frames(6);
    result["typing"] = { sent: sent["result"] ?? null, unchanged: shadow.querySelector(".cm-content")!.textContent === before };
    expect(shadow.querySelector(".cm-content")!.textContent === before, "the read-only text is unchanged");
  } else {
    result["typing"] = { outcome: preflight?.outcome ?? "not-run" };
  }

  // What each kind of file says.
  phase = "files";
  await expand(context, "notes");
  const bom = await open(context, "notes/bom.txt");
  const crlf = await open(context, "notes/crlf.txt");
  const persian = await open(context, "notes/persian.md");
  await expand(context, "media");
  const binary = await open(context, "media/logo.bin");
  const huge = await open(context, "media/huge.txt");
  const token = await open(context, "src/token.ts");
  const said = (v: HTMLElement) => v.querySelector('[data-testid="file-facts"]')?.textContent
    ?? v.querySelector('[data-testid="file-notice"]')?.textContent ?? "";
  result["files"] = { bom: said(bom), crlf: said(crlf), persian: said(persian), binary: binary.dataset["reason"],
                      huge: huge.dataset["reason"], token: token.dataset["reason"] };
  expect(said(bom).includes("with BOM"), "the BOM is reported");
  expect(said(crlf).includes("CRLF"), "CRLF is reported");
  expect(binary.dataset["reason"] === "binary" && huge.dataset["reason"] === "too_large",
         "a binary and an oversized file are unavailable");
  expect(token.dataset["reason"] === "secret_content", "a file holding a token is refused");
  (await row(context, ".env")).click();
  await frames(3);
  expect(document.querySelector('[data-testid="file-view"][data-path=".env"]') === null, ".env opens nothing");
  const tabsShown = [...document.querySelectorAll<HTMLElement>('[data-testid="file-tabs"] [role="tab"]')]
    .map((t) => t.dataset["path"] ?? "");
  result["tabs"] = tabsShown;

  // Accessibility with the viewer and the tree open.
  phase = "axe";
  (await row(context, "src/app.ts")).click();
  await context.element('[data-testid="file-view"][data-path="src/app.ts"][data-state="text"]');
  const axe = await accessibilityViolations();
  result["axe"] = axe;
  phase = "after";

  // Nothing secret reached the page.
  const page = document.documentElement.outerHTML + JSON.stringify({ ...sessionStorage })
    + [...document.querySelectorAll<HTMLElement>('[data-testid="file-code"]')]
      .map((h) => h.shadowRoot?.textContent ?? "").join("");
  result["secretsInPage"] = { envValue: page.includes(ENV_SECRET), token: page.includes(TOKEN) };
  expect(!page.includes(ENV_SECRET) && !page.includes(TOKEN), "no workspace secret reached the page");

  result["violations"] = violations;
  expect(axe.length === 0, `axe: ${axe.map((v) => `${v.rule} at ${v.targets.join(", ")}`).join("; ")}`);
  expect(violations.length === 0, `CSP violations: ${JSON.stringify(violations)}`);
  return result;
};
