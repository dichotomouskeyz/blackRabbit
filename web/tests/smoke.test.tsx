import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "@/app/page";

// Phase 0 harness smoke test — proves Vitest + RTL render React components.
// Real invariant tests (INV-001..019) are written in the RED phase.
describe("Phase 0 harness", () => {
  it("renders the operator shell root", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { name: /blackRabbit Operator/i })).toBeInTheDocument();
  });
});
