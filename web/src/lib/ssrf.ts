// AGENT_BASE_URL egress validation (frontend-shell INV-013 / PRH-007 / BND-005).
// Loopback/private-range + scheme check before any outbound call.

export interface EgressCheck {
  allowed: boolean;
  reason: string;
}

function parseIpv4(host: string): number[] | null {
  const parts = host.split(".");
  if (parts.length !== 4) return null;
  const nums: number[] = [];
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const n = Number(p);
    if (n < 0 || n > 255) return null;
    nums.push(n);
  }
  return nums;
}

// Explicit link-local deny (169.254.0.0/16) — cloud metadata (AWS/GCP/Azure
// 169.254.169.254) lives here. Refused explicitly, not merely by default-deny
// (QA-006), so a future refactor cannot silently open it.
function isLinkLocalIpv4(octets: number[]): boolean {
  return octets[0] === 169 && octets[1] === 254;
}

function isPrivateIpv4(octets: number[]): boolean {
  // Link-local is NEVER private/allowed (explicit deny, checked first).
  if (isLinkLocalIpv4(octets)) return false;
  const [a, b] = octets;
  // 127.0.0.0/8 loopback
  if (a === 127) return true;
  // 10.0.0.0/8
  if (a === 10) return true;
  // 172.16.0.0/12
  if (a === 172 && b >= 16 && b <= 31) return true;
  // 192.168.0.0/16
  if (a === 192 && b === 168) return true;
  return false;
}

// Reject IPv4-mapped IPv6 (::ffff:a.b.c.d / ::ffff:NNNN:NNNN) outright (QA-006).
// Honoring the embedded IPv4 here would let ::ffff:<public> or ::ffff:169.254.x.y
// slip past the loopback/private gate; we fail closed on the whole family.
function isIpv4MappedIpv6(host: string): boolean {
  // .hostname compresses to e.g. [::ffff:a9fe:a9fe]; match with or without brackets.
  return /^\[?::ffff:/i.test(host) || /^\[?::(0{1,4}:)?ffff:/i.test(host);
}

// Extract the RAW host substring from the input URL string, BEFORE WHATWG URL
// normalization (QA-006). Node's `new URL()` silently rewrites alternate IPv4
// encodings (decimal 2130706433 / hex 0x7f000001 / octal 017700000001 / bare 0)
// into dotted-quad 127.0.0.1 — which would otherwise be ALLOWED. We inspect the
// pre-normalization authority so these non-dotted-quad numeric forms are refused.
function rawHost(baseUrl: string): string | null {
  // scheme://[userinfo@]host[:port][/...]
  const m = /^[a-z][a-z0-9+.-]*:\/\/(?:[^@/?#]*@)?(\[[^\]]+\]|[^:/?#]*)/i.exec(baseUrl);
  if (!m) return null;
  return m[1] ?? null;
}

// A non-dotted-quad numeric host: decimal (one integer), hex (0x...), octal
// (leading 0), or any host made only of digits/hex that is NOT a proper a.b.c.d
// quad. These are alternate IPv4 encodings WHATWG would normalize to loopback.
function isNonDottedQuadNumeric(raw: string): boolean {
  const h = raw.toLowerCase();
  if (h.startsWith("[")) return false; // IPv6 literal — handled elsewhere
  // hex: 0x...
  if (/^0x[0-9a-f]+$/.test(h)) return true;
  // a proper dotted quad is fine here (allowed/denied by the IPv4 path)
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return false;
  // bare decimal integer (incl. octal leading-zero forms) with no dots
  if (/^\d+$/.test(h)) return true;
  // partial-dotted numeric forms (e.g. "127.1", "0.0.0") are non-canonical too
  if (/^[0-9.]+$/.test(h) && h.split(".").length !== 4) return true;
  return false;
}

// Returns allowed only when the host is loopback (127.0.0.0/8, ::1, localhost) or
// an RFC-1918 private range, AND the scheme is http/https. Link-local
// (169.254/16 — cloud metadata) and public hosts are refused.
export function isEgressAllowed(baseUrl: string): EgressCheck {
  let parsed: URL;
  try {
    parsed = new URL(baseUrl);
  } catch {
    return { allowed: false, reason: "AGENT_BASE_URL is not a valid URL" };
  }

  const scheme = parsed.protocol.replace(/:$/, "").toLowerCase();
  if (scheme !== "http" && scheme !== "https") {
    return { allowed: false, reason: `scheme ${scheme} not allowed (http/https only)` };
  }

  // QA-006: reject alternate IPv4 encodings BEFORE trusting the normalized host.
  // WHATWG URL rewrites decimal/hex/octal IPv4 into dotted-quad loopback, which we
  // must not honor — only a canonical dotted-quad / ::1 / localhost may be allowed.
  const raw = rawHost(baseUrl);
  if (raw && isNonDottedQuadNumeric(raw)) {
    return {
      allowed: false,
      reason: `host ${raw} is a non-dotted-quad numeric form (alternate IP encoding), refused`,
    };
  }

  // .hostname may carry brackets for IPv6 literals.
  const host = parsed.hostname.toLowerCase();

  if (host === "localhost") {
    return { allowed: true, reason: "loopback (localhost)" };
  }

  // IPv6 loopback ::1 (URL.hostname yields "[::1]" → already stripped to "::1").
  if (host === "::1" || host === "[::1]") {
    return { allowed: true, reason: "loopback (::1)" };
  }

  // IPv4-mapped IPv6 (::ffff:a.b.c.d) is refused outright (QA-006) — never
  // unwrapped to its embedded IPv4, which could smuggle a public/link-local host.
  if (isIpv4MappedIpv6(host)) {
    return { allowed: false, reason: `IPv4-mapped IPv6 host ${host} is refused` };
  }

  // Any other IPv6 literal (e.g. fd00::1 ULA, fe80:: link-local) is refused —
  // fail closed; only the explicit ::1 loopback is allowed.
  if (host.includes(":")) {
    return { allowed: false, reason: `IPv6 host ${host} is not loopback (only ::1)` };
  }

  const octets = parseIpv4(host);
  if (octets) {
    // Explicit link-local (metadata) deny before the private check (QA-006).
    if (isLinkLocalIpv4(octets)) {
      return { allowed: false, reason: `host ${host} is link-local (169.254/16), refused` };
    }
    if (isPrivateIpv4(octets)) {
      return { allowed: true, reason: "loopback / RFC-1918 private" };
    }
    return { allowed: false, reason: `host ${host} is not loopback/private` };
  }

  // Non-dotted-quad numeric forms (decimal 2130706433, hex 0x7f000001, octal
  // 017700000001, bare "0") and any public DNS name are refused — fail closed
  // (QA-006). We never normalize alternate IP encodings into an allow.
  return { allowed: false, reason: `host ${host} is not a permitted loopback/private address` };
}
