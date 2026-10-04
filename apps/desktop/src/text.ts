/**
 * Outside text, made inert (FR-029).
 *
 * Everything the window shows that came from outside it — messages, tool
 * output, file names, model names, errors — is text. React already refuses
 * to turn it into markup; this adds the two things it does not do:
 *
 * - control characters become visible symbols (`\x1b` shows as `␛`), so an
 *   escape sequence is something a person can see rather than something that
 *   acts;
 * - `http` and `https` links are found by the same rule the native side
 *   uses to decide what `open_external` may open (`relay::links_in`), and are
 *   the only thing that can be clicked.
 */

export type Segment =
  | { readonly kind: "text"; readonly text: string }
  | { readonly kind: "link"; readonly url: string };

/** C0 controls show as their Control Pictures symbol; line break and tab stay. */
export function visible(text: string): string {
  return text.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, (character) => {
    const code = character.charCodeAt(0);
    if (code < 0x20) return String.fromCharCode(0x2400 + code);
    if (code === 0x7f) return "␡";
    return "�";
  });
}

const SCHEMES = ["http://", "https://"] as const;
const STOP = /[\s"'<>\u0000-\u001f\u007f-\u009f]/;
const TRAILING = /[.,;:!?)\]}]+$/;

/** The text, split into plain runs and links. */
export function segments(text: string): Segment[] {
  const out: Segment[] = [];
  let rest = text;
  const plain = (run: string) => {
    if (run === "") return;
    const last = out[out.length - 1];
    if (last?.kind === "text") out[out.length - 1] = { kind: "text", text: last.text + run };
    else out.push({ kind: "text", text: run });
  };
  for (;;) {
    const starts = SCHEMES.map((scheme) => rest.indexOf(scheme)).filter((at) => at >= 0);
    if (starts.length === 0) break;
    const at = Math.min(...starts);
    const tail = rest.slice(at);
    const stop = tail.search(STOP);
    const end = stop < 0 ? tail.length : stop;
    const link = tail.slice(0, end).replace(TRAILING, "");
    plain(rest.slice(0, at));
    if (link.length > link.indexOf("://") + 3) {
      out.push({ kind: "link", url: link });
      plain(tail.slice(link.length, end));
    } else {
      plain(tail.slice(0, Math.max(end, 1)));
    }
    rest = tail.slice(Math.max(end, 1));
  }
  plain(rest);
  return out;
}
