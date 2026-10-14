import { describe, it, expect } from "vitest";
import {
  contractVersionBanner,
  BUILT_AGAINST_CONTRACT_VERSION,
} from "@/lib/error-messages";

// INV-018: contract_version skew is surfaced, not silently tolerated.
// Test approach: integration.

describe("INV-018 [integration]: contract_version skew banner", () => {
  it("surfaces a mismatch banner when backend contract_version diverges", () => {
    // Tests INV-018: a mismatched contract_version renders a banner.
    const banner = contractVersionBanner("9.9", BUILT_AGAINST_CONTRACT_VERSION);
    expect(banner).not.toBeNull();
    expect(banner!.text).toMatch(/version mismatch|mismatch/i);
    expect(banner!.kind).toBe("version_mismatch");
  });

  it("renders no banner when versions match", () => {
    // Tests INV-018: no false-positive banner on a match.
    const banner = contractVersionBanner(
      BUILT_AGAINST_CONTRACT_VERSION,
      BUILT_AGAINST_CONTRACT_VERSION,
    );
    expect(banner).toBeNull();
  });
});
