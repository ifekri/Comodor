/**
 * One piece of outside text, shown inertly (`src/text.ts`). A link is a
 * button that asks the native side to open it; nothing here navigates.
 */

import { createContext, useContext } from "react";

import { segments, visible } from "../text.ts";

/** How a shown link is opened: `open_external`, provided by the app. */
export const OpenLink = createContext<(url: string) => void>(() => {});

export function InertText({ text }: { text: string | undefined | null }) {
  const open = useContext(OpenLink);
  if (!text) return null;
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
