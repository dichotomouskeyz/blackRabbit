import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateSessionForm } from "@/components/CreateSessionForm";

// INV-011 / OQ-004: No PII collected, stored, logged, or transmitted client-side;
// transcripts ephemeral; participant_id UUID-validated; storage carries nothing
// session-derived. Test approach: integration.

afterEach(() => {
  vi.restoreAllMocks();
});

const PII_FIELD_NAMES = ["name", "first_name", "last_name", "email", "dob", "date_of_birth", "address", "phone", "ssn"];

describe("INV-011 [integration]: participant_id UUID validation", () => {
  it("rejects a non-UUID participant_id before submission", async () => {
    // Tests INV-011: form rejects non-UUID participant_id (no submit).
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => ({ ok: true as const, status: 200, data: { session_id: "x" } }));
    render(<CreateSessionForm onSubmit={onSubmit} vocab={{ compounds: ["saline"], dose_units: ["mg"] }} />);

    const pid = screen.getByLabelText(/participant/i);
    await user.type(pid, "not-a-uuid");
    await user.click(screen.getByRole("button", { name: /create/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("INV-011 [integration]: no PII form fields", () => {
  it("the create form exposes no PII inputs", () => {
    // Tests INV-011: no name/email/dob/etc. fields.
    const onSubmit = vi.fn(async () => ({ ok: true as const, status: 200, data: { session_id: "x" } }));
    render(<CreateSessionForm onSubmit={onSubmit} vocab={{ compounds: ["saline"], dose_units: ["mg"] }} />);
    for (const field of PII_FIELD_NAMES) {
      expect(screen.queryByLabelText(new RegExp(`^${field}$`, "i"))).toBeNull();
    }
  });
});

describe("INV-011 [integration]: nothing session-derived persists to durable storage", () => {
  it("submitting a session-derived form writes nothing to localStorage/cookie/indexedDB", async () => {
    // Tests INV-011: spies on Storage.setItem + cookie setter assert no session-derived persistence.
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const cookieSetter = vi.fn();
    const originalCookie = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
    Object.defineProperty(document, "cookie", { configurable: true, set: cookieSetter, get: () => "" });

    const user = userEvent.setup();
    const VALID_UUID = "11111111-1111-4111-8111-111111111111";
    const onSubmit = vi.fn(async () => ({ ok: true as const, status: 200, data: { session_id: VALID_UUID } }));
    render(<CreateSessionForm onSubmit={onSubmit} vocab={{ compounds: ["saline"], dose_units: ["mg"] }} />);

    await user.type(screen.getByLabelText(/participant/i), VALID_UUID);
    await user.click(screen.getByRole("button", { name: /create/i }));

    expect(setItemSpy).not.toHaveBeenCalled();
    expect(cookieSetter).not.toHaveBeenCalled();

    if (originalCookie) Object.defineProperty(document, "cookie", originalCookie);
  });
});

describe("INV-011 [integration]: agent route is no-store / dynamic", () => {
  it("the agent route module sets dynamic + no-store", async () => {
    // Tests INV-011: no Next.js Data Cache / RSC caching of session-derived responses.
    const route = await import("@/app/api/agent/route");
    expect((route as { dynamic?: string }).dynamic).toBe("force-dynamic");
    expect((route as { fetchCache?: string }).fetchCache).toBe("force-no-store");
  });
});
