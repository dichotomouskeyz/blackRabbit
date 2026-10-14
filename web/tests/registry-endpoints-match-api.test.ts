import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { TOOL_REGISTRY } from "@/lib/tool-registry";

// Every tool endpoint must be a route the FastAPI app declares, or a gated tool
// would get a 404/405 instead of the structured 409 (INV-002a).

const APP_PY = readFileSync(resolve(__dirname, "../../api/app.py"), "utf8");
const ROUTES = new Set(
  [...APP_PY.matchAll(/@app\.(get|post)\("([^"]+)"/g)].map((m) => `${m[1].toUpperCase()} ${m[2]}`),
);

describe("tool registry endpoints match api/app.py routes", () => {
  for (const def of Object.values(TOOL_REGISTRY)) {
    it(`${def.name}: ${def.method} ${def.endpoint}`, () => {
      expect(ROUTES.has(`${def.method.toUpperCase()} ${def.endpoint}`)).toBe(true);
    });
  }
});
