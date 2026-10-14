import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SessionText } from "@/components/SessionText";
import { OutcomeMessage } from "@/components/OutcomeMessage";
import type { ApiResult } from "@/lib/api-client";

// INV-005a / PRH-003: Session-derived text is DOM-inert across all render paths,
// including 422/409 echoed input. Test approach: integration.

const XSS = '<script>window.__pwned = true;</script><img src=x onerror="window.__pwned=true">';

describe("INV-005a [integration]: session-derived text renders inert", () => {
  it("a zone_label with a <script> payload renders as escaped text, no element", () => {
    // Tests INV-005a: markup in session data does not create a <script>/<img> element.
    (window as unknown as { __pwned?: boolean }).__pwned = false;
    const { container } = render(<SessionText value={XSS} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    // The literal text must be present (escaped), proving it rendered as data.
    expect(container.textContent).toContain("<script>");
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBe(false);
  });

  it("a 422 {field,message} echoing operator input renders inert", () => {
    // Tests INV-005a: _map_create_value_error can echo operator input; render inert.
    const result: ApiResult<unknown> = {
      ok: false,
      status: 422,
      body: { field: "compound", message: `unknown compound ${XSS}` },
    };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("a 409 blocked_reason carrying markup renders inert", () => {
    // Tests INV-005a: server 409 blocked_reason is session-derived display text.
    const result: ApiResult<unknown> = {
      ok: false,
      status: 409,
      body: {
        error: "capability_unavailable",
        capability: "close_session",
        status: "blocked",
        blocked_reason: XSS,
        gate: "OQ-001",
      },
    };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("INV-005a / PRH-003 [integration]: no dangerouslySetInnerHTML on session-derived strings", () => {
  it("component sources contain no dangerouslySetInnerHTML", async () => {
    // Tests PRH-003: lint/grep ban — no dangerouslySetInnerHTML in the render path.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const dir = path.resolve(__dirname, "../src/components");
    const files = await fs.readdir(dir);
    for (const f of files) {
      if (!f.endsWith(".tsx")) continue;
      const src = await fs.readFile(path.join(dir, f), "utf8");
      expect(src, `${f} uses dangerouslySetInnerHTML`).not.toContain("dangerouslySetInnerHTML");
    }
  });
});
