import { defineConfig, devices } from "@playwright/test";

// E2E lane (frontend-shell INV-017). Full-path flows that Vitest/RTL can't cover
// — capability gating end-to-end, the agent tool round-trip, fail-closed renders.
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
