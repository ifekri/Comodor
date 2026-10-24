# D3 spike: Monaco, its worker, the CSP, and a three-button native dialog

Throwaway measurement code on the branch `spike/d3-monaco-csp-dialog`.
It is **not** D3 product code, is never merged, and is not a base for the D3
pull requests: D3 starts again from `main` under its own specification.

What it measures, in the real WebView of the test build, with the window's
Content Security Policy unchanged (`src-tauri/tauri.conf.json`):

- `monaco-probe.ts` (run by the `spike-monaco` scenario): Monaco 0.57.0's
  editor core and six Monarch tokenizers bundled by Vite, its base editor
  worker through Vite's `?worker` import, every `securitypolicyviolation`,
  whether the theme's token colours actually render, whether the worker
  runs, line-ending and BOM behaviour of Monaco's model, OS-level typing,
  and a 2,000,000-byte file. One labelled experiment tries Tauri's style
  nonce, if the effective policy has one.
- `dialog-evidence.mjs`: the test build started with `COMODOR_SPIKE_DIALOG`
  shows a native message dialog with three custom buttons (Save, Discard,
  Cancel) through `tauri-plugin-dialog` 2.8.1, parented to the window; the
  script answers it per platform (Escape, Enter, each button pressed through
  the platform's accessibility interface, closing the dialog) and records the
  button the application received, the labels read from the dialog, and a
  screenshot of the dialog's window alone.

CI: `.github/workflows/spike-d3.yml`, on pushes to this branch only.
