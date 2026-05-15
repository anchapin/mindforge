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
        shouldShowOnboarding({
          preferencesOnboardingCompleted: undefined,
          preferencesLoading: true,
        })
      ).toBe(false);
    });

    it("returns false when onboarding is already completed", () => {
      expect(
        shouldShowOnboarding({
          preferencesOnboardingCompleted: true,
          preferencesLoading: false,
        })
      ).toBe(false);
    });

    it("returns true when onboarding has NOT completed and no dismissal", () => {
      expect(
        shouldShowOnboarding({
          preferencesOnboardingCompleted: false,
          preferencesLoading: false,
        })
      ).toBe(true);
    });

    it("treats undefined onboarding_completed as not-yet-onboarded (legacy backend)", () => {
      expect(
        shouldShowOnboarding({
          preferencesOnboardingCompleted: undefined,
          preferencesLoading: false,
        })
      ).toBe(true);
    });

    it("returns false when user has dismissed in this browser", () => {
      markOnboardingDismissed();
      expect(
        shouldShowOnboarding({
          preferencesOnboardingCompleted: false,
          preferencesLoading: false,
        })
      ).toBe(false);
    });
  });
});
