import { describe, it, expect } from "vitest";
import { createApiClient } from "@/lib/api-client";

// INV-004 / PRH-001: Neither the client nor the Node agent route sends tenant
// scope (sponsor_id/site_id) in body, query, or header. Test approach: unit.

function recordingTransport(captured: { path: string; init?: RequestInit }[]) {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    captured.push({ path, init });
    return new Response(JSON.stringify({ sessions: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

const TENANT_KEYS = ["sponsor_id", "site_id"];

describe("INV-004 [unit]: client never sends tenant scope", () => {
  it("createSession body carries no sponsor_id/site_id even if passed in fields", () => {
    // Tests INV-004: the create path must not forward tenancy keys to the API.
    const captured: { path: string; init?: RequestInit }[] = [];
    const client = createApiClient({ transport: recordingTransport(captured) });
    return client
      .createSession({
        compound: "saline",
        capture_source: "lsl",
        participant_id: "11111111-1111-4111-8111-111111111111",
        // hostile/erroneous injection of tenancy — must be stripped before outbound
        sponsor_id: "leak",
        site_id: "leak",
      })
      .then(() => {
        expect(captured.length).toBeGreaterThan(0);
        for (const call of captured) {
          const url = call.path;
          const body = call.init?.body ? String(call.init.body) : "";
          const headerObj = call.init?.headers
            ? JSON.stringify(call.init.headers)
            : "";
          for (const key of TENANT_KEYS) {
            expect(url).not.toContain(key);
            expect(body).not.toContain(key);
            expect(headerObj).not.toContain(key);
          }
        }
      });
  });

  it("listSessions sends no tenancy query/header", () => {
    // Tests INV-004: reads carry no client tenancy.
    const captured: { path: string; init?: RequestInit }[] = [];
    const client = createApiClient({ transport: recordingTransport(captured) });
    return client.listSessions().then(() => {
      for (const call of captured) {
        for (const key of TENANT_KEYS) {
          expect(call.path).not.toContain(key);
          expect(call.init?.body ? String(call.init.body) : "").not.toContain(key);
        }
      }
    });
  });
});

describe("INV-004 [unit]: source grep backstop — no tenancy env read in agent route", () => {
  it("agent route source does not read API_SPONSOR_ID/API_SITE_ID", async () => {
    // Tests INV-004 / PRH-001: the Node route must not read tenancy env and attach it.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const routeSrc = await fs.readFile(
      path.resolve(__dirname, "../src/app/api/agent/route.ts"),
      "utf8",
    );
    expect(routeSrc).not.toContain("API_SPONSOR_ID");
    expect(routeSrc).not.toContain("API_SITE_ID");
  });
});
