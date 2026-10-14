import { describe, it, expect } from "vitest";
import { isEgressAllowed } from "@/lib/ssrf";

// INV-013 / PRH-007 / BND-005: The agent route validates AGENT_BASE_URL is
// loopback/private before any outbound call. Test approach: unit.

describe("INV-013 [unit]: egress is refused for non-loopback/non-private hosts", () => {
  it("refuses the cloud metadata IP 169.254.169.254", () => {
    // Tests INV-013: link-local / metadata host is not loopback/private-allowed.
    expect(isEgressAllowed("http://169.254.169.254/latest/meta-data").allowed).toBe(false);
  });

  it("refuses a public host", () => {
    // Tests INV-013: a public host is refused.
    expect(isEgressAllowed("https://api.openai.com/v1").allowed).toBe(false);
    expect(isEgressAllowed("http://8.8.8.8:4000").allowed).toBe(false);
  });

  it("refuses a file:// scheme", () => {
    // Tests INV-013: only http/https schemes allowed.
    expect(isEgressAllowed("file:///etc/passwd").allowed).toBe(false);
  });
});

describe("INV-013 [unit]: egress is allowed for loopback / RFC-1918 private", () => {
  it("allows loopback 127.0.0.1 and localhost", () => {
    // Tests INV-013: loopback allowed.
    expect(isEgressAllowed("http://127.0.0.1:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://localhost:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://[::1]:4000").allowed).toBe(true);
  });

  it("allows RFC-1918 private ranges", () => {
    // Tests INV-013: 10/8, 172.16/12, 192.168/16 allowed.
    expect(isEgressAllowed("http://10.0.0.5:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://172.16.3.4:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://192.168.1.10:4000").allowed).toBe(true);
  });
});
