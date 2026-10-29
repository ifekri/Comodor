/**
 * D2 T093: keys delivered by the operating system to the real window
 * (FR-011, FR-017, FR-018, FR-034). Only with COMODOR_E2E_OS_LEVEL=1 (the CI
 * desktop job); otherwise the outcome is `not-run`, which is never evidence.
 *
 * Outcomes: `verified`; `capability-unavailable` (the runner cannot focus the
 * window or inject keys, proven by preflight or by the plain-letter probe);
 * `product-failure` (the probe reached the page, so a missing shortcut
 * result is the window's). Only `verified` passes.
 */

import { expect, type Scenario, type ScenarioContext } from "../runner.ts";
import { paletteControl, region, SIDEBAR } from "./workbench.ts";

type Data = Record<string, unknown>;
interface KeySpec { key: "q" | "k" | "F6" | "Escape" | "Tab"; mod?: boolean; shift?: boolean }

/** How long a delivered key may take to show; a bound, never a delay. */
const BOUND_MS = 10_000;

/**
 * The next frame, or the next turn of the event loop if no frame comes: a
 * window the system keeps in the background draws no frames, and the wait
 * must still end within its bound.
 */
function frame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
    const turn = new MessageChannel();
    turn.port1.onmessage = () => {
      turn.port1.close();
      resolve();
    };
    turn.port2.postMessage(null);
  });
}

/** Wait, frame by frame, until `check` holds; false if it never does within the bound. */
async function observed(check: () => boolean | Promise<boolean>): Promise<boolean> {
  const ends = performance.now() + BOUND_MS;
  while (performance.now() < ends) {
    if (await check()) return true;
    await frame();
  }
  return await check();
}

function capabilityUnavailable(reason: string): Error {
  return new Error(`capability-unavailable: ${reason}`);
}

function productFailure(reason: string): Error {
  return new Error(`product-failure: ${reason}`);
}

async function press(context: ScenarioContext, key: KeySpec): Promise<void> {
  const reply = await context.checkpoint("press-keys", { key: key as unknown as Data });
  const result = reply["result"] as { ok: boolean; reason?: string } | undefined;
  if (!result?.ok) throw capabilityUnavailable(result?.reason ?? "the key could not be sent");
}


export const keyDelivery: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));

  // 1. Preflight: the gate, the injection tool, the platform's permissions.
  const gate = await context.checkpoint("os-level");
  const preflight = gate["preflight"] as { ok: boolean; outcome?: string; reason?: string };
  if (!preflight.ok && preflight.outcome === "not-run") {
    return { outcome: "not-run", reason: preflight.reason };
  }
  if (!preflight.ok) throw capabilityUnavailable(preflight.reason ?? "preflight failed");

  // The window in front, confirmed by the test build itself.
  const focusing = await context.checkpoint("focus-window");
  const linux = focusing["linux"] as { ok: boolean; reason?: string } | undefined;
  if (linux && !linux.ok) throw capabilityUnavailable(linux.reason ?? "the window could not be focused");
  const windows = focusing["windows"] as { ok: boolean; reason?: string } | undefined;
  if (windows && !windows.ok) throw capabilityUnavailable(windows.reason ?? "the window could not be focused");
  // The page has the focus, or the native window says it does. On Windows the
  // WebView's own child window takes the keyboard focus, so the top-level
  // window never reports it there; the page's document still does.
  const focused = await observed(async () => document.hasFocus()
    || (await context.query("window" as never) as { focused?: boolean })["focused"] === true);
  if (!focused) throw capabilityUnavailable("the window never reported focus");

  // 2. The probe: a plain letter must reach a field in the real page.
  const probe = document.createElement("input");
  probe.setAttribute("data-testid", "key-probe");
  probe.setAttribute("aria-label", "Key probe");
  document.body.appendChild(probe);
  probe.focus();
  // Every key the page sees during the probe, for the failure's message.
  const seen: string[] = [];
  const listen = (event: KeyboardEvent) => seen.push(`${event.type}:${event.key}:${event.code}`);
  window.addEventListener("keydown", listen, true);
  await press(context, { key: "q" });
  const arrived = await observed(() => probe.value === "q");
  window.removeEventListener("keydown", listen, true);
  const holding = `${document.activeElement?.tagName ?? "nothing"}, page focused: ${document.hasFocus()}`;
  probe.remove();
  if (!arrived) {
    throw capabilityUnavailable(`injected keys do not reach the WebView (keys seen: ${seen.join(" ") || "none"
    }; focus: ${holding})`);
  }

  // 3. The shortcuts, each judged by what the page shows afterwards.
  const results: Data = {};
  // The menubar is one tab stop: Tab goes from its menu on to the search.
  const first = document.querySelector<HTMLButtonElement>('header.top-bar [role="menubar"] button[tabindex="0"]')!;
  const second = paletteControl()!;
  first.focus();
  const afterTop = document.querySelector(SIDEBAR) === null ? "main" : "sidebar";

  await press(context, { key: "Tab" });
  if (!(await observed(() => document.activeElement === second))) {
    throw productFailure(`Tab did not move focus to the next control (${document.activeElement?.outerHTML.slice(0, 60)})`);
  }
  results["Tab"] = "next control";
  first.focus();

  // DIAGNOSTIC (branch diag/linux-f6 only): every key and focus event the page sees around F6.
  const f6seen: string[] = [];
  const f6listen = (event: Event) => {
    const k = event as KeyboardEvent;
    const target = event.target as Element | null;
    f6seen.push(`${event.type}:${k.key ?? ""}:${k.code ?? ""}:${k.keyCode ?? ""}:prevented=${event.defaultPrevented}`
      + `:target=${target?.tagName ?? "?"}.${(target as HTMLElement | null)?.className ?? ""}`);
  };
  for (const type of ["keydown", "keyup", "focusin", "focusout", "blur", "focus"]) window.addEventListener(type, f6listen, true);
  const f6before = `${document.activeElement?.tagName}.${(document.activeElement as HTMLElement | null)?.className} hasFocus=${document.hasFocus()}`;
  await press(context, { key: "F6" });
  const f6ok = await observed(() => region() === afterTop);
  for (const type of ["keydown", "keyup", "focusin", "focusout", "blur", "focus"]) window.removeEventListener(type, f6listen, true);
  console.log(`DIAG-F6 ok=${f6ok} before=${f6before} after=${document.activeElement?.tagName} region=${String(region())} events=${JSON.stringify(f6seen)}`);
  if (!f6ok) throw productFailure(`F6 left focus in ${String(region())}; DIAG before=${f6before} events=${JSON.stringify(f6seen)}`);
  results["F6"] = region();
  results["F6-diag"] = { before: f6before, events: f6seen };

  await press(context, { key: "F6", shift: true });
  if (!(await observed(() => region() === "top"))) throw productFailure(`Shift+F6 left focus in ${String(region())}`);
  results["Shift+F6"] = region();

  const opener = document.activeElement;
  await press(context, { key: "k", mod: true });
  const dialog = () => document.querySelector('[role="dialog"][aria-label="Commands"]');
  if (!(await observed(() => dialog() !== null))) throw productFailure("mod+K did not open the palette");
  results["mod+K"] = "palette open";

  await press(context, { key: "Escape" });
  if (!(await observed(() => dialog() === null))) throw productFailure("Escape did not close the palette");
  expect(document.activeElement === opener, "product-failure: focus did not return to where it was");
  results["Escape"] = "palette closed, focus returned";

  return { outcome: "verified", platform: navigator.userAgent, results };
};
