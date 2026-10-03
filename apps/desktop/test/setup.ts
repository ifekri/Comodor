/**
 * Window tests run React into a DOM, under Bun, with nothing behind it.
 *
 * happy-dom gives the DOM. The network is closed off explicitly: a window
 * test that reached for `fetch` would be testing the network rather than the
 * window, and the offline rule (FR-034) says nothing in a test may.
 */

import { GlobalRegistrator } from "@happy-dom/global-registrator";

GlobalRegistrator.register({ url: "http://localhost/" });

const refuse = (): never => {
  throw new Error("window tests run offline: no network access");
};
globalThis.fetch = refuse as unknown as typeof fetch;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
