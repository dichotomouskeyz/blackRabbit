import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateSessionForm } from "@/components/CreateSessionForm";
import { newParticipantId } from "@/lib/participant-id";
import { UUID_RE } from "@/lib/tool-registry";

// The create form can generate a pseudonymous participant ID so operators never
// type a name or a UUID by hand (INV-011).

afterEach(() => vi.restoreAllMocks());

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("participant ID generation", () => {
  it("Generate fills a UUID that the form submits as participant_id", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => ({ ok: true as const, status: 200, data: { session_id: "x" } }));
    render(<CreateSessionForm onSubmit={onSubmit} vocab={{ compounds: ["psilocybin"], dose_units: ["mg"] }} />);

    await user.click(screen.getByRole("button", { name: "Generate" }));
    const pid = (screen.getByLabelText(/participant/i) as HTMLInputElement).value;
    expect(pid).toMatch(UUID_RE);

    await user.click(screen.getByRole("button", { name: /create/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ participant_id: pid }));
  });

  it("each click gives a new ID and nothing is written to browser storage", async () => {
    const user = userEvent.setup();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<CreateSessionForm onSubmit={vi.fn()} vocab={{ compounds: ["psilocybin"], dose_units: ["mg"] }} />);
    const input = screen.getByLabelText(/participant/i) as HTMLInputElement;

    await user.click(screen.getByRole("button", { name: "Generate" }));
    const first = input.value;
    await user.click(screen.getByRole("button", { name: "Generate" }));
    expect(input.value).not.toBe(first);
    expect(setItem).not.toHaveBeenCalled();
  });

  it("falls back to getRandomValues when randomUUID is unavailable", () => {
    const fallback = { getRandomValues: <T extends ArrayBufferView>(a: T) => globalThis.crypto.getRandomValues(a) };
    const ids = new Set(Array.from({ length: 50 }, () => newParticipantId(fallback)));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(V4);
  });
});
