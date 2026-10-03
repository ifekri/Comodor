import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The window's content is served from the application bundle only: no
// development server in a test or release build, no remote origin, and no
// inline script (the Content Security Policy in src-tauri/tauri.conf.json
// refuses it). `--mode e2e` adds the scenario runner; any other mode leaves
// it out entirely.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
});
