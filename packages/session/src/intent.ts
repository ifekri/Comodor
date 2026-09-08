/**
 * Where the person wants the mode to end up, versus where the core says it is.
 *
 * F1 computed the next mode from the last one the core had confirmed, so a
 * key repeat that outran the round trip landed on fewer switches than were
 * pressed: three Tabs inside one confirmation produced one change. The obvious
 * fixes are both wrong. A debounce makes the interface feel slower to be more
 * accurate, and picks a number nobody can justify. Letting the client move its
 * own label first makes it authoritative about a thing it does not decide,
 * which is exactly what a refused change then contradicts.
 *
 * The separation is the fix:
 *
 * - **confirmed** is the core's answer. Nothing here writes it except a
 *   `mode.changed` event.
 * - **desired** is where repeated presses currently point. It moves at the
 *   speed of the keyboard.
 * - **inFlight** is the one request allowed to be outstanding.
 *
 * When a confirmation arrives and `confirmed !== desired`, the next request
 * goes out for the *current* desired value — not for the intermediate states
 * that were passed through. Coalescing those is fine; losing the final one is
 * not, and that is the difference this file exists to hold.
 */

import { next as nextInCycle, type Mode } from "@comodor/modes";

export interface ModeIntent {
  /** What the core last said. The only value a label should be drawn from. */
  readonly confirmed: Mode;
  /** Where the presses so far are pointing. */
  readonly desired: Mode;
  /** The request currently outstanding, if any. At most one. */
  readonly inFlight?: Mode | undefined;
  /** Set when the core refused; cleared on the next intent. */
  readonly refused?: string | undefined;
}

export function begin(confirmed: Mode): ModeIntent {
  return { confirmed, desired: confirmed };
}

/** A Tab, or a Shift+Tab. Computed from intent, so repeats accumulate. */
export function step(intent: ModeIntent, back = false): ModeIntent {
  return {
    ...intent,
    desired: nextInCycle(intent.desired, back),
    refused: undefined,
  };
}

/** A click, a palette entry, or anything else naming a mode outright. */
export function want(intent: ModeIntent, mode: Mode): ModeIntent {
  return { ...intent, desired: mode, refused: undefined };
}

/**
 * The request to make now, or nothing.
 *
 * Nothing when a request is already outstanding — one mutation in flight per
 * session — or when the core already agrees with the intent.
 */
export function due(intent: ModeIntent): Mode | undefined {
  if (intent.inFlight !== undefined) return undefined;
  if (intent.confirmed === intent.desired) return undefined;
  return intent.desired;
}

export function sending(intent: ModeIntent, mode: Mode): ModeIntent {
  return { ...intent, inFlight: mode };
}

/**
 * The core confirmed a mode.
 *
 * `desired` is deliberately untouched: presses that arrived while this was in
 * flight are still where the person wants to end up, and `due` will ask for
 * that next. The confirmation of an *older* request does not cancel a newer
 * intention.
 */
export function confirmed(intent: ModeIntent, mode: Mode): ModeIntent {
  return { ...intent, confirmed: mode, inFlight: undefined };
}

/**
 * The core refused, or the request failed.
 *
 * Intent falls back to what the core actually has. Leaving `desired` where it
 * was would make `due` ask again immediately, and again after that — a loop
 * that hammers a core which has already said no.
 */
export function refuse(intent: ModeIntent, reason: string): ModeIntent {
  return {
    ...intent,
    desired: intent.confirmed,
    inFlight: undefined,
    refused: reason,
  };
}

/** Whether anything is still to be asked for or waited on. */
export function settled(intent: ModeIntent): boolean {
  return intent.inFlight === undefined && intent.confirmed === intent.desired;
}
