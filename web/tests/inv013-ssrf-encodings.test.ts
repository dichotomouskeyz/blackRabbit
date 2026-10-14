import { describe, it, expect } from "vitest";
import { isEgressAllowed } from "@/lib/ssrf";

// QA-006 — lock SSRF normalization against alternate IP encodings and link-local.
// Each of these adversarial forms MUST be refused (fail closed). This pins the
// behavior so a future refactor honoring IPv4-mapped-IPv6 or numeric IPv4 cannot
// silently open an egress to a public/metadata host with no failing test.

describe("QA-006 [unit]: alternate IP encodings + link-local are refused (fail closed)", () => {
  const refused: Array<[string, string]> = [
    ["IPv4-mapped IPv6 to metadata", "http://[::ffff:169.254.169.254]:4000"],
    ["decimal IPv4 (2130706433 = 127.0.0.1)", "http://2130706433:4000"],
    ["hex IPv4 (0x7f000001 = 127.0.0.1)", "http://0x7f000001:4000"],
    ["octal IPv4 (017700000001 = 127.0.0.1)", "http://017700000001:4000"],
    ["ULA IPv6 fd00::1", "http://[fd00::1]:4000"],
    ["link-local metadata 169.254.169.254", "http://169.254.169.254/latest/meta-data"],
    ["unspecified 0.0.0.0", "http://0.0.0.0:4000"],
    ["bare 0", "http://0:4000"],
  ];

  for (const [label, url] of refused) {
    it(`refuses ${label}`, () => {
      // Tests QA-006 / INV-013 / PRH-007: the host is not a permitted loopback/
      // private address in dotted-quad / ::1 form → refused.
      const result = isEgressAllowed(url);
      expect(result.allowed, `${url} (${label}) must be REFUSED`).toBe(false);
    });
  }

  it("still allows the legitimate dotted-quad loopback and ::1 (no over-refusal)", () => {
    // Guards against a fix that fails closed on EVERYTHING — the real proxy must work.
    expect(isEgressAllowed("http://127.0.0.1:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://[::1]:4000").allowed).toBe(true);
    expect(isEgressAllowed("http://192.168.1.10:4000").allowed).toBe(true);
  });

  it("explicit link-local deny carries a link-local reason (not incidental default-deny)", () => {
    // QA-006: 169.254/16 is refused by an EXPLICIT rule, surfaced in the reason.
    const result = isEgressAllowed("http://169.254.169.254:4000");
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/link-local/i);
  });
});
