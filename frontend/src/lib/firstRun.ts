/**
 * First-run detection and dismissal (#46).
 *
 * "Is this the first time the user opens the dashboard?" The backend tells us
 * via GET /api/preferences:
 *   - { id: "" }   -> singleton row not created yet -> first run
 *   - { id: "..." -> a real UUID } -> already onboarded
 *
 * Once the user dismisses the wizard (Skip OR Complete), we persist that
 * decision in localStorage so we never re-prompt for that browser. The
 * caller is also expected to invalidate the React-Query cache for
 * /api/preferences after onComplete so a subsequent reload skips the gate
 * via the backend signal.
 */

const STORAGE_KEY = "mindforge:onboarding-dismissed";

export function hasUserDismissedOnboarding(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    // localStorage can throw in private-browsing or restricted contexts;
    // treat that as "no decision recorded yet" so we still render the gate.
    return false;
  }
}

export function markOnboardingDismissed(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "true");
  } catch {
    // No-op: failing to remember the dismissal is annoying but not broken.
  }
}

export function clearOnboardingDismissed(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // No-op
  }
}

/**
 * Compose the full first-run decision: show the gate when BOTH:
 *   - the backend signal says first run (id == "")
 *   - the user hasn't already dismissed in this browser
 *
 * preferencesLoading covers the in-flight case so we don't flash the modal
 * before we know whether it's needed.
 */
export function shouldShowOnboarding(args: {
  preferencesId: string | undefined;
  preferencesLoading: boolean;
}): boolean {
  if (args.preferencesLoading) return false;
  const isFirstRun = args.preferencesId === "";
  if (!isFirstRun) return false;
  return !hasUserDismissedOnboarding();
}

export const _ONBOARDING_STORAGE_KEY = STORAGE_KEY;
