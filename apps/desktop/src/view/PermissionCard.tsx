/**
 * A tool waiting for the person's permission: every choice the Core offered,
 * in its order, with the tool and the risk as the Core classified them.
 */

import type { Interaction } from "@comodor/session";

import { InertText } from "./InertText.tsx";

const CHOICE_LABELS: Readonly<Record<string, string>> = {
  allow: "Allow",
  allow_always: "Always allow",
  deny: "Deny",
};

export function PermissionCard({ interaction, held, onReply }: {
  interaction: Interaction;
  /** While the session is being checked or read again: nothing is sent. */
  held: boolean;
  onReply: (choice: string) => void;
}) {
  const request = interaction.request;
  const options = Array.isArray(request["options"]) ? request["options"] as string[] : [];
  const submitting = interaction.state === "submitting" || held;
  return (
    <section className="card permission-card" data-testid="permission"
             data-id={String(request["id"] ?? "")}>
      <h2><InertText text={String(request["title"] ?? "")} /></h2>
      <dl>
        {typeof request["tool"] === "string" && (<><dt>Tool</dt><dd><InertText text={request["tool"]} /></dd></>)}
        {typeof request["risk"] === "string" && (<><dt>Risk</dt><dd><InertText text={request["risk"]} /></dd></>)}
      </dl>
      {typeof request["detail"] === "string" && <pre className="detail"><InertText text={request["detail"]} /></pre>}
      {interaction.state === "failed" && <p className="card-error"><InertText text={interaction.error} /></p>}
      <div className="actions">
        {options.map((choice) => (
          <button key={choice} type="button" data-choice={choice} disabled={submitting}
                  onClick={() => onReply(choice)}>
            {CHOICE_LABELS[choice] ?? choice}
          </button>
        ))}
      </div>
    </section>
  );
}
