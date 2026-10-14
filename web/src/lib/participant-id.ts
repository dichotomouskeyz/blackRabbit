// Pseudonymous participant IDs for the create form (frontend-shell INV-011).
// The operator records the mapping to a real person in the lab's own enrollment
// key; blackRabbit only ever sees the UUID.

type CryptoLike = Pick<Crypto, "getRandomValues"> & { randomUUID?: () => string };

// A random version-4 UUID. Prefers crypto.randomUUID, which browsers expose
// only on secure origins (https or localhost); elsewhere, such as the LAN
// address Next.js prints, it builds one from getRandomValues.
export function newParticipantId(cryptoImpl: CryptoLike = globalThis.crypto): string {
  if (typeof cryptoImpl.randomUUID === "function") return cryptoImpl.randomUUID();
  const b = cryptoImpl.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
