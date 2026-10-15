/**
 * The keyboard shortcuts reference (US3 scenario 4): every binding of the
 * window's registry, read from the registry itself, with its command and the
 * platform's modifier name — so it cannot list a key that does nothing.
 */

import type { CommandRegistry } from "@comodor/commands";

import type { WindowContext } from "../commands.ts";
import { displayKey, type Platform } from "./keys.ts";

export function ShortcutsPanel({ registry, platform }: {
  registry: CommandRegistry<WindowContext>;
  platform: Platform;
}) {
  return (
    <table className="shortcuts" data-testid="shortcuts">
      <thead>
        <tr><th scope="col">Keys</th><th scope="col">Command</th></tr>
      </thead>
      <tbody>
        {registry.allBindings().map((binding) => (
          <tr key={`${binding.key} ${binding.command}`} data-binding={`${binding.key} ${binding.command}`}>
            <td><kbd>{displayKey(binding.key, platform)}</kbd></td>
            <td>{registry.get(binding.command)?.title}</td>
          </tr>
        ))}
        <tr data-edge="arrows">
          <td><kbd>Left</kbd> / <kbd>Right</kbd></td>
          <td>Widen the side panel / Narrow the side panel, on the focused panel edge</td>
        </tr>
        <tr data-edge="ends">
          <td><kbd>Home</kbd> / <kbd>End</kbd></td>
          <td>The narrowest / widest side panel, on the focused panel edge</td>
        </tr>
      </tbody>
    </table>
  );
}
