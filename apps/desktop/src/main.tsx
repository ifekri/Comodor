import { createRoot } from "react-dom/client";

import { App } from "./app.tsx";

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);

// The test build's scenario runner. The mode is fixed at build time, so a
// release build contains none of it.
if (import.meta.env.MODE === "e2e") {
  void import("../e2e/runner.ts").then(({ runScenario }) => runScenario());
}
