/**
 * The command palette (US2; FR-011–FR-014): a dialog with a combobox over a
 * listbox of `registry.search(query, context)` — only the commands that apply
 * now, ranked by the shared search. The highlight goes back to the first
 * result whenever the query changes (`selectionFor`). It runs a command
 * through the registry, the same path a button and a key take, and traps
 * nothing: Escape or a click outside closes it.
 */

import { type CommandRegistry, moveSelection, selectedCommand, selectionFor } from "@comodor/commands";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { WindowContext } from "../commands.ts";
import { displayKey, type Platform } from "./keys.ts";

/** Each group's icon, as the reference marks its result rows. */
const GROUP_ICONS: Readonly<Record<string, string>> = {
  Conversation: "forum", Mode: "tune", Core: "deployed_code", Workbench: "dashboard",
};

export function Palette({ registry, context, platform, onClose, onRun, onCount }: {
  registry: CommandRegistry<WindowContext>;
  /** The context now; the list follows it while the palette is open. */
  context: WindowContext;
  platform: Platform;
  onClose: () => void;
  /** Close, then run this command. */
  onRun: (id: string) => void;
  /** How many results there are, to be said once. */
  onCount: (count: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  // Rebuilt on every render: a Core restart changes what applies.
  const selection = { ...selectionFor(registry, context, query), index };
  const results = selection.results;
  const highlighted = results.length === 0 ? -1 : Math.min(Math.max(index, 0), results.length - 1);

  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    onCount(results.length);
  }, [results.length, onCount]);

  const keyOf = (id: string) => registry.allBindings().find((binding) => binding.command === id)?.key;

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setIndex(moveSelection({ ...selection, index: highlighted }, event.key === "ArrowDown" ? 1 : -1).index);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const command = selectedCommand({ ...selection, index: highlighted });
      if (command) onRun(command.id);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  const optionId = (at: number) => `palette-option-${at}`;
  return (
    <>
      <div className="palette-backdrop" data-testid="palette-backdrop" aria-hidden="true" onClick={onClose} />
      <div className="palette" role="dialog" aria-modal="true" aria-label="Commands" data-testid="palette">
        <input ref={input} className="palette-input" type="text" role="combobox" aria-expanded="true"
               aria-controls="palette-results" aria-autocomplete="list" aria-label="Search commands"
               aria-activedescendant={highlighted < 0 ? undefined : optionId(highlighted)}
               placeholder="Type a command" value={query}
               onChange={(event) => {
                 setQuery(event.target.value);
                 // The shared rule: back to the first result on every change.
                 setIndex(selectionFor(registry, context, event.target.value).index);
               }}
               onKeyDown={onKeyDown} />
        <ul id="palette-results" className="palette-results" role="listbox" aria-label="Commands">
          {results.map((command, at) => {
            const key = keyOf(command.id);
            return (
              <li key={command.id} id={optionId(at)} role="option" aria-selected={at === highlighted}
                  data-command={command.id} className={at === highlighted ? "palette-option active" : "palette-option"}
                  onMouseMove={() => setIndex(at)} onClick={() => onRun(command.id)}>
                <span className="icon palette-icon" data-icon={GROUP_ICONS[command.group ?? ""] ?? "terminal"}
                      aria-hidden="true" />
                <span className="palette-title">{command.title}</span>
                {command.group && <span className="palette-group">{command.group}</span>}
                {key && <kbd className="palette-key">{displayKey(key, platform)}</kbd>}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
