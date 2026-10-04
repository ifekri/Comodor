/**
 * One piece of outside text, shown inertly (`src/text.ts`). A link is a
 * button that asks the native side to open it; nothing here navigates.
 */

import { createContext, useContext } from "react";

import { segments, visible } from "../text.ts";

/** How a shown link is opened: `open_external`, provided by the app. */
export const OpenLink = createContext<(url: string) => void>(() => {});

/**
 * `linked` is false for text the native side reported (a failure, its
 * diagnostics, the workspace, a notice): it never passed through the relay,
 * so `open_external` would refuse its links, and none is offered.
 */
export function InertText({ text, linked = true }: { text: string | undefined | null; linked?: boolean }) {
  const open = useContext(OpenLink);
  if (!text) return null;
  if (!linked) return <span>{visible(text)}</span>;
  return (
    <>
      {segments(text).map((segment, index) => segment.kind === "text"
        ? <span key={index}>{visible(segment.text)}</span>
        : (
          <button key={index} type="button" className="link" title={segment.url}
                  onClick={() => open(segment.url)}>
            {segment.url}
          </button>
        ))}
    </>
  );
}
