/**
 * Unit tests for the first-run helpers (#46).
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  hasUserDismissedOnboarding,
  markOnboardingDismissed,
  clearOnboardingDismissed,
  shouldShowOnboarding,
  _ONBOARDING_STORAGE_KEY,
} from "./firstRun";

describe("firstRun helpers", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe("dismissal flag", () => {
    it("starts false", () => {
      expect(hasUserDismissedOnboarding()).toBe(false);
    });

    it("returns true after mark", () => {
      markOnboardingDismissed();
      expect(hasUserDismissedOnboarding()).toBe(true);
      expect(localStorage.getItem(_ONBOARDING_STORAGE_KEY)).toBe("true");
    });

    it("clears", () => {
      markOnboardingDismissed();
      clearOnboardingDismissed();
      expect(hasUserDismissedOnboarding()).toBe(false);
    });
  });

  describe("shouldShowOnboarding", () => {
    it("returns false while preferences are loading", () => {
      expect(
        shouldShowOnboarding({ preferencesId: undefined, preferencesLoading: true })
      ).toBe(false);
    });

    it("returns false when the user has a real preferences id (not first run)", () => {
      expect(
        shouldShowOnboarding({
          preferencesId: "abc-123",
          preferencesLoading: false,
        })
      ).toBe(false);
    });

    it("returns true on first run with no dismissal", () => {
      expect(
        shouldShowOnboarding({ preferencesId: "", preferencesLoading: false })
      ).toBe(true);
    });

    it("returns false on first run after dismissal", () => {
      markOnboardingDismissed();
      expect(
        shouldShowOnboarding({ preferencesId: "", preferencesLoading: false })
      ).toBe(false);
    });
  });
});
