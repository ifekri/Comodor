/**
 * A tool waiting for the person's permission: every choice the Core offered,
 * in its order, with the tool and the risk as the Core classified them.
 */

import type { Interaction } from "@comodor/session";

const CHOICE_LABELS: Readonly<Record<string, string>> = {
  allow: "Allow",
  allow_always: "Always allow",
  deny: "Deny",
};

export function PermissionCard({ interaction, onReply }: {
  interaction: Interaction;
  onReply: (choice: string) => void;
}) {
  const request = interaction.request;
  const options = Array.isArray(request["options"]) ? request["options"] as string[] : [];
  const submitting = interaction.state === "submitting";
  return (
    <section className="card permission-card" data-testid="permission"
             data-id={String(request["id"] ?? "")}>
      <h2>{String(request["title"] ?? "")}</h2>
      <dl>
        {typeof request["tool"] === "string" && (<><dt>Tool</dt><dd>{request["tool"]}</dd></>)}
        {typeof request["risk"] === "string" && (<><dt>Risk</dt><dd>{request["risk"]}</dd></>)}
      </dl>
      {typeof request["detail"] === "string" && <pre className="detail">{request["detail"]}</pre>}
      {interaction.state === "failed" && <p className="card-error">{interaction.error}</p>}
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
