/**
 * The reference's prompt footer around D1's composer (spec Clarifications,
 * 2026-10-17): before Send, the model the Core reports, the later
 * attachments and Agentic controls, and D1's mode control; Send's key; after
 * it, "Command" (the palette) and "Shortcuts". What runs is the window's own
 * command; what arrives later says so.
 */

import { type ReactNode, useContext, useMemo } from "react";

import { COMMAND_IDS, commands } from "../commands.ts";
import type { ModelInfo } from "../view/StatusStrip.tsx";
import { InertText } from "../view/InertText.tsx";
import { WORKBENCH_COMMAND_IDS as ID } from "./commands.ts";
import { currentPlatform, displayKey } from "./keys.ts";
import { LaterButton } from "./Later.tsx";
import { ShellRun } from "./run-context.ts";

function useKeyFor(): (id: string) => string | undefined {
  const platform = useMemo(currentPlatform, []);
  return (id) => {
    const binding = commands.allBindings().find((entry) => entry.command === id);
    return binding ? displayKey(binding.key, platform) : undefined;
  };
}

export function PromptLead({ model, modeControl }: { model: ModelInfo | null; modeControl: ReactNode }) {
  return (
    <>
      <span className="icon prompt-forum" data-icon="forum" aria-hidden="true" />
      <span className="model-chip" title="The model the Core reports" data-testid="model-chip" dir="auto">
        {model === null ? "No model reported yet"
          : <InertText text={[model.provider, model.model].filter(Boolean).join(" / ") || "No model"} linked={false} />}
      </span>
      <LaterButton label="Attachments" className="prompt-later">
        <span className="icon" data-icon="attach_file" aria-hidden="true" />
        <span>Files</span>
      </LaterButton>
      <LaterButton label="Agentic mode" className="prompt-later prompt-agentic">
        <span className="icon" data-icon="hub" aria-hidden="true" />
        <span>Agentic</span>
      </LaterButton>
      {modeControl}
      <span className="prompt-spacer" />
    </>
  );
}

export function SendHint() {
  const keyFor = useKeyFor();
  const key = keyFor(COMMAND_IDS.send);
  return key ? <span className="prompt-key" aria-hidden="true">[{key.toUpperCase()}]</span> : null;
}

export function PromptTrail() {
  const run = useContext(ShellRun);
  const keyFor = useKeyFor();
  const palette = keyFor(ID.paletteOpen);
  const shortcuts = keyFor(ID.viewShortcuts);
  if (!run) return null;
  return (
    <>
      <span className="prompt-sep" aria-hidden="true">|</span>
      <button type="button" className="prompt-link" data-focus-key="prompt-commands"
              title={palette ? `Commands (${palette})` : "Commands"} onClick={() => run(ID.paletteOpen)}>
        <span className="prompt-link-label">Command</span>{palette && <span className="prompt-link-key">[{palette}]</span>}
      </button>
      <span className="prompt-sep prompt-shortcuts-sep" aria-hidden="true">|</span>
      <button type="button" className="prompt-link prompt-shortcuts"
              title={shortcuts ? `Keyboard shortcuts (${shortcuts})` : "Keyboard shortcuts"}
              onClick={() => run(ID.viewShortcuts)}>
        <span className="prompt-link-label">Shortcuts</span>{shortcuts && <span className="prompt-link-key">[{shortcuts}]</span>}
      </button>
    </>
  );
}
