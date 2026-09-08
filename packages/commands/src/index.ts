/**
 * One action, however it was reached.
 *
 * A key binding, a slash command, a palette entry, a menu item and a button
 * are five ways to ask for the same thing, and the usual outcome is five
 * handlers that drift — the button keeps working after the shortcut stops.
 * So there is one registry: a command has an id, a title and a `run`, and
 * every surface looks it up rather than reimplementing it.
 *
 * The registry is also what makes the footer honest. A client that prints
 * `Ctrl+K Commands` and a client that binds `Ctrl+K` are the same list here,
 * so a test can assert every advertised shortcut resolves to a command that
 * exists — which is the check that was missing when the old interface
 * advertised a `ctrl+s` that did nothing.
 *
 * Nothing here calls the core directly. A command is given a context by
 * whoever registers it, so this package has no dependency on the client and a
 * desktop build reuses the same definitions.
 */

export interface CommandContext {
  /** Anything the command needs. Supplied by the client that registers it. */
  readonly [key: string]: unknown;
}

export interface Command<Context = CommandContext> {
  /** Stable, dotted, and the thing every surface refers to. */
  readonly id: string;
  /** What a person reads in a palette or a menu. */
  readonly title: string;
  /** Grouping for a palette; free text. */
  readonly group?: string;
  /** Extra words to match on, for things people call by another name. */
  readonly keywords?: readonly string[];
  /** Whether it can run right now. Absent means always. */
  readonly enabled?: (context: Context) => boolean;
  readonly run: (context: Context) => void | Promise<void>;
}

/** A key, and the command it stands for. */
export interface Binding {
  /** As a client names it: `ctrl+k`, `tab`, `shift+tab`. */
  readonly key: string;
  readonly command: string;
  /** Shown in a footer. Absent means the binding is real but not advertised. */
  readonly hint?: string;
}

export class CommandRegistry<Context = CommandContext> {
  private readonly commands = new Map<string, Command<Context>>();
  private readonly bindings: Binding[] = [];

  add(...commands: Command<Context>[]): this {
    for (const command of commands) {
      if (this.commands.has(command.id)) {
        throw new Error(`two commands claim the id ${command.id}`);
      }
      this.commands.set(command.id, command);
    }
    return this;
  }

  bind(...bindings: Binding[]): this {
    for (const binding of bindings) {
      if (!this.commands.has(binding.command)) {
        // The failure this prevents: a footer that advertises a key which
        // resolves to nothing. Caught when the client is built, not when
        // somebody presses it.
        throw new Error(
          `${binding.key} is bound to ${binding.command}, which is not a command`);
      }
      this.bindings.push(binding);
    }
    return this;
  }

  get(id: string): Command<Context> | undefined {
    return this.commands.get(id);
  }

  all(): Command<Context>[] {
    return [...this.commands.values()];
  }

  allBindings(): Binding[] {
    return [...this.bindings];
  }

  /** Every binding a client would print in a footer. */
  hints(): Required<Binding>[] {
    return this.bindings.filter(
      (binding): binding is Required<Binding> => Boolean(binding.hint));
  }

  forKey(key: string): Command<Context> | undefined {
    const binding = this.bindings.find((entry) => entry.key === key);
    return binding ? this.commands.get(binding.command) : undefined;
  }

  async run(id: string, context: Context): Promise<boolean> {
    const command = this.commands.get(id);
    if (!command) return false;
    if (command.enabled && !command.enabled(context)) return false;
    await command.run(context);
    return true;
  }

  /**
   * Palette search: title, id and keywords, ranked by where the match lands.
   *
   * A prefix beats a word start beats anything else, which is what makes
   * typing `mo` put "Mode" above "Open workspace" instead of sorting them by
   * whatever order they were registered in.
   */
  search(query: string, context?: Context): Command<Context>[] {
    const needle = query.trim().toLowerCase();
    const usable = this.all().filter(
      (command) => !command.enabled || !context || command.enabled(context));
    if (!needle) return usable;

    const scored: Array<{ command: Command<Context>; score: number }> = [];
    for (const command of usable) {
      const score = rank(command, needle);
      if (score > 0) scored.push({ command, score });
    }
    scored.sort((left, right) =>
      right.score - left.score
      || left.command.title.localeCompare(right.command.title));
    return scored.map((entry) => entry.command);
  }
}

function rank<Context>(command: Command<Context>, needle: string): number {
  const haystacks: Array<[string, number]> = [
    [command.title.toLowerCase(), 3],
    [command.id.toLowerCase(), 2],
    ...(command.keywords ?? []).map(
      (word) => [word.toLowerCase(), 1] as [string, number]),
  ];
  let best = 0;
  for (const [text, weight] of haystacks) {
    const at = text.indexOf(needle);
    if (at < 0) continue;
    best = Math.max(best, weight * 10 + place(text, needle, at));
  }
  return best;
}

/**
 * How good a match at this position is.
 *
 * A whole word beats the start of a word beats anywhere. The distinction
 * earns its keep immediately: typing `mode` matches both "Next mode" and
 * "Change model", and without it the two tie and the winner is decided by
 * alphabetical order — so the command actually named "mode" comes second.
 */
function place(text: string, needle: string, at: number): number {
  // Anything that is not a letter or a digit ends a word. Listing separators
  // instead — `[\s.\-_]` — missed the colon in "Mode: ACT", so searching
  // "mode" scored it the same as the "mode" inside "Change model" and the tie
  // was broken alphabetically. The command actually called Mode came second.
  const boundary = /[^\p{L}\p{N}]/u;
  const opens = at === 0 || boundary.test(text[at - 1] ?? "");
  const end = at + needle.length;
  const closes = end === text.length || boundary.test(text[end] ?? "");
  if (opens && closes) return 4;
  if (opens) return 2;
  return 1;
}
