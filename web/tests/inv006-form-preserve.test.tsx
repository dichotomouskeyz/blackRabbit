import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateSessionForm } from "@/components/CreateSessionForm";

// INV-006 (form half): a 422 surfaces a field-level error AND preserves other
// entered form values (does not wipe the form). Test approach: integration.

describe("INV-006 [integration]: 422 preserves other entered form values", () => {
  it("after a 422 on compound, the entered participant_id and other fields persist", async () => {
    // Tests INV-006: a 422 must not wipe inputs.
    const user = userEvent.setup();
    const VALID_UUID = "11111111-1111-4111-8111-111111111111";
    const onSubmit = vi.fn(async () => ({
      ok: false as const,
      status: 422,
      body: { field: "compound", message: "unknown compound", valid_choices: ["saline", "psilocybin"] },
    }));

    render(
      <CreateSessionForm
        onSubmit={onSubmit}
        vocab={{ compounds: ["saline", "psilocybin"], dose_units: ["mg"] }}
      />,
    );

    const pid = screen.getByLabelText(/participant/i) as HTMLInputElement;
    await user.type(pid, VALID_UUID);
    await user.click(screen.getByRole("button", { name: /create/i }));

    // The field-level error renders...
    expect(screen.getByText(/unknown compound|compound/i)).toBeInTheDocument();
    // ...and the participant_id value is preserved.
    expect((screen.getByLabelText(/participant/i) as HTMLInputElement).value).toBe(VALID_UUID);
  });
});
