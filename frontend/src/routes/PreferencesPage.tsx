/**
 * /preferences — placeholder. The full UI lands with #46 (OnboardingWizard
 * gate) and a future preferences-form ticket. For #48 (router foundation)
 * this just confirms the route resolves.
 */
export default function PreferencesPage() {
  return (
    <section>
      <h2 className="mb-4 text-lg font-semibold">Preferences</h2>
      <p className="text-sm text-zinc-400">
        Preferences UI will be wired in a follow-up ticket. Today the API at
        <code className="mx-1 rounded bg-zinc-800 px-1 py-0.5">/api/preferences</code>
        is reachable but no editor is mounted yet.
      </p>
    </section>
  );
}
