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
    <>
      <h3 className="panel-section">SHORTCUTS</h3>
      <table className="shortcuts" data-testid="shortcuts">
        <thead>
          <tr><th scope="col">Command</th><th scope="col">Keys</th></tr>
        </thead>
        <tbody>
          {registry.allBindings().map((binding) => (
            <tr key={`${binding.key} ${binding.command}`} data-binding={`${binding.key} ${binding.command}`}>
              <td>{registry.get(binding.command)?.title}</td>
              <td><kbd>{displayKey(binding.key, platform)}</kbd></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
