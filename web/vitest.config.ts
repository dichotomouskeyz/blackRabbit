import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Vitest is the frontend TDD gate (frontend-shell INV-017). Component/logic
// invariants run here; Playwright (test:e2e) covers full-path flows.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    // E2E specs run under Playwright, not Vitest.
    exclude: ["tests/e2e/**", "node_modules/**", ".next/**"],
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
});
