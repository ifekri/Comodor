/**
 * No provider is configured (FR-031, R11). Credentials are entered in a
 * terminal, never in this window; "Check again" restarts the Core so it
 * reads the configuration afresh.
 */

export function SetupNotice({ onCheckAgain }: { onCheckAgain: () => void }) {
  return (
    <section className="setup-notice" data-testid="setup-notice">
      <p>
        No provider is configured, so Comodor cannot answer yet. Run <code>comodor setup</code> in
        a terminal, then choose Check again.
      </p>
      <div className="actions">
        <button type="button" onClick={onCheckAgain}>Check again</button>
      </div>
    </section>
  );
}
