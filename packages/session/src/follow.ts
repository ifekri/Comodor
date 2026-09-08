/**
 * Whether the conversation is keeping up with the newest line, and what that
 * means for what the person is shown.
 *
 * The rule everybody expects and few interfaces implement: a long answer
 * scrolls itself while you are at the bottom, and **stops** the moment you
 * scroll up. Being yanked back down mid-paragraph, three times, while the
 * model is still writing, is the difference between a transcript you can read
 * and one you have to copy out somewhere else.
 *
 * What is deliberately *not* here is the scrolling. OpenTUI's scroll box
 * already keeps a viewport pinned to the bottom and lets a manual scroll take
 * it off, and a browser's overflow container does the same thing with
 * different numbers; reimplementing row arithmetic on top of either would be
 * a second mechanism to keep in step with the first.
 *
 * What is here is the part both clients would otherwise write twice: given
 * that the viewport has moved or that content has arrived, is there something
 * below worth mentioning, and when does following resume. A renderer reports
 * where the viewport is; this says what follows from that.
 */

export interface Follow {
  /** True while the viewport is showing the newest content. */
  readonly following: boolean;
  /** New content arrived while not following, and has not been looked at. */
  readonly unseen: boolean;
}

export const start: Follow = { following: true, unseen: false };

/**
 * The viewport moved, and the renderer says whether it is now at the bottom.
 *
 * Arriving at the tail resumes following and clears the marker, because that
 * is how a person says "keep up with it again" without learning a key for it.
 */
export function moved(state: Follow, atTail: boolean): Follow {
  if (atTail) return start;
  return { following: false, unseen: state.unseen };
}

/**
 * Content was appended.
 *
 * Following: nothing changes — the viewport is the tail and the tail moved.
 * Paused: the viewport must not move, and there is now something below worth
 * telling the person about.
 */
export function grew(state: Follow): Follow {
  if (state.following) return state;
  if (state.unseen) return state;
  return { following: false, unseen: true };
}

/** Back to the live tail, deliberately — a key, or a click on the marker. */
export function tail(): Follow {
  return start;
}

/**
 * A new prompt was sent.
 *
 * Following resumes: somebody starting a turn is asking to see its answer, and
 * leaving them parked in the history would make the interface look as though
 * nothing had happened.
 */
export function sent(): Follow {
  return start;
}

/** Whether to draw the "there is more below" marker. */
export function marker(state: Follow): boolean {
  return !state.following && state.unseen;
}
