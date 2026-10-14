import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// RTL unmounts between tests so component invariants don't leak DOM state.
afterEach(() => {
  cleanup();
});
