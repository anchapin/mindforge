/**
 * /preferences — User preferences and Proactive Monitoring Settings UI (#90).
 *
 * Section 2.7.4 of SPEC.md specifies the Proactive Monitoring panel. The backend
 * exposes GET/PUT /api/preferences which already exists (#46). This page wires
 * up the Settings UI and mounts at /settings via TanStack Router (see router.tsx).
 */

import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPreferences, updatePreferences, type Preferences } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProactiveSettings {
  proactive_monitoring_enabled: boolean;
  email_monitoring_enabled: boolean;
  email_check_interval_minutes: number;
  followup_enabled: boolean;
  followup_days_threshold: number;
  billing_alert_enabled: boolean;
  billing_alert_threshold_usd: number;
  calendar_check_enabled: boolean;
  calendar_check_interval_minutes: number;
}

// ---------------------------------------------------------------------------
// Constants — interval / threshold options
// ---------------------------------------------------------------------------

const EMAIL_INTERVAL_OPTIONS = [
  { label: "Every 15 minutes", value: 15 },
  { label: "Every 30 minutes", value: 30 },
  { label: "Every 1 hour", value: 60 },
  { label: "Every 2 hours", value: 120 },
  { label: "Every 6 hours", value: 360 },
];

const CALENDAR_INTERVAL_OPTIONS = [
  { label: "Every 15 minutes", value: 15 },
  { label: "Every 30 minutes", value: 30 },
  { label: "Every 1 hour", value: 60 },
  { label: "Every 2 hours", value: 120 },
  { label: "Every 6 hours", value: 360 },
];

const BILLING_THRESHOLD_OPTIONS = [
  { label: "$25 USD", value: 25 },
  { label: "$50 USD", value: 50 },
  { label: "$100 USD", value: 100 },
  { label: "$200 USD", value: 200 },
  { label: "$500 USD", value: 500 },
];

const FOLLOWUP_DAYS_OPTIONS = [
  { label: "1 day", value: 1 },
  { label: "2 days", value: 2 },
  { label: "3 days", value: 3 },
  { label: "5 days", value: 5 },
  { label: "7 days", value: 7 },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}

function Toggle({ checked, onChange, label, description, disabled }: ToggleProps) {
  return (
    <label className={`flex items-start gap-3 cursor-pointer${disabled ? " opacity-50" : ""}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`mt-0.5 relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900 ${
          checked ? "bg-blue-600" : "bg-zinc-600"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      <span>
        <span className="block text-sm font-medium text-zinc-100">{label}</span>
        {description && (
          <span className="block text-xs text-zinc-400">{description}</span>
        )}
      </span>
    </label>
  );
}

interface SelectOption {
  label: string;
  value: number;
}

interface SelectFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  options: SelectOption[];
  disabled?: boolean;
}

function SelectField({ label, value, onChange, options, disabled }: SelectFieldProps) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-sm text-zinc-300">{label}</label>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 rounded border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Proactive Settings Section
// ---------------------------------------------------------------------------

interface ProactiveSectionProps {
  settings: ProactiveSettings;
  onChange: (partial: Partial<ProactiveSettings>) => void;
  disabled?: boolean;
}

function ProactiveSection({ settings, onChange, disabled }: ProactiveSectionProps) {
  return (
    <section aria-labelledby="proactive-monitoring-heading">
      <div className="rounded border border-zinc-700 bg-zinc-800/50 p-4 space-y-5">
        {/* Section header */}
        <div className="flex items-center gap-2">
          <span className="text-lg">⚙️</span>
          <h2 id="proactive-monitoring-heading" className="text-base font-semibold text-zinc-100">
            Proactive Monitoring
          </h2>
        </div>

        {/* Master toggle */}
        <div className="rounded border border-zinc-700 bg-zinc-800 p-3">
          <Toggle
            checked={settings.proactive_monitoring_enabled}
            onChange={(v) => onChange({ proactive_monitoring_enabled: v })}
            label="Enable Proactive Monitoring"
            description="Master switch for all background monitoring"
            disabled={disabled}
          />
        </div>

        {/* Monitoring toggles — only active when master switch is on */}
        <div className="space-y-4">
          <Toggle
            checked={settings.email_monitoring_enabled}
            onChange={(v) => onChange({ email_monitoring_enabled: v })}
            label="Monitor inbox overnight"
            description="Check for new and urgent emails while you sleep"
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <Toggle
            checked={settings.followup_enabled}
            onChange={(v) => onChange({ followup_enabled: v })}
            label="Follow-up on unreplied emails"
            description="Draft follow-up reminders for threads you haven't responded to"
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <Toggle
            checked={settings.billing_alert_enabled}
            onChange={(v) => onChange({ billing_alert_enabled: v })}
            label="Alert on billing anomalies"
            description="Notify you when Stripe detects unusual charges or renewals"
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <Toggle
            checked={settings.calendar_check_enabled}
            onChange={(v) => onChange({ calendar_check_enabled: v })}
            label="Calendar conflict detection"
            description="Detect scheduling conflicts before they become a problem"
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />
        </div>

        {/* Interval + threshold dropdowns — only active when master switch is on */}
        <div className="space-y-3 rounded border border-zinc-700 bg-zinc-800 p-3">
          <SelectField
            label="Email check interval"
            value={settings.email_check_interval_minutes}
            onChange={(v) => onChange({ email_check_interval_minutes: v })}
            options={EMAIL_INTERVAL_OPTIONS}
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <SelectField
            label="Calendar check interval"
            value={settings.calendar_check_interval_minutes}
            onChange={(v) => onChange({ calendar_check_interval_minutes: v })}
            options={CALENDAR_INTERVAL_OPTIONS}
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <SelectField
            label="Follow-up threshold"
            value={settings.followup_days_threshold}
            onChange={(v) => onChange({ followup_days_threshold: v })}
            options={FOLLOWUP_DAYS_OPTIONS}
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />

          <SelectField
            label="Billing alert threshold"
            value={settings.billing_alert_threshold_usd}
            onChange={(v) => onChange({ billing_alert_threshold_usd: v })}
            options={BILLING_THRESHOLD_OPTIONS}
            disabled={disabled || !settings.proactive_monitoring_enabled}
          />
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// PreferencesPage
// ---------------------------------------------------------------------------

function defaultSettings(): ProactiveSettings {
  return {
    proactive_monitoring_enabled: true,
    email_monitoring_enabled: true,
    email_check_interval_minutes: 30,
    followup_enabled: true,
    followup_days_threshold: 3,
    billing_alert_enabled: true,
    billing_alert_threshold_usd: 50,
    calendar_check_enabled: true,
    calendar_check_interval_minutes: 60,
  };
}

export default function PreferencesPage() {
  const queryClient = useQueryClient();

  // Fetch current preferences
  const { data: prefs, isLoading, error } = useQuery<Preferences>({
    queryKey: ["preferences"],
    queryFn: fetchPreferences,
    staleTime: 30_000,
  });

  // Local editable state — seeded from API, then mutated optimistically
  const [settings, setSettings] = useState<ProactiveSettings>(defaultSettings);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync local state when API response arrives
  useEffect(() => {
    if (prefs) {
      setSettings({
        proactive_monitoring_enabled: prefs.proactive_monitoring_enabled,
        email_monitoring_enabled: prefs.proactive_monitoring_enabled, // API doesn't split these yet
        email_check_interval_minutes: prefs.email_check_interval_minutes,
        followup_enabled: prefs.proactive_monitoring_enabled,
        followup_days_threshold: 3, // API doesn't expose this — use reasonable default
        billing_alert_enabled: prefs.proactive_monitoring_enabled,
        billing_alert_threshold_usd: prefs.billing_alert_threshold_usd,
        calendar_check_enabled: prefs.proactive_monitoring_enabled,
        calendar_check_interval_minutes: prefs.calendar_check_interval_minutes,
      });
    }
  }, [prefs]);

  // PUT /api/preferences mutation — typed explicitly to avoid TypeParameters<...>[0]
  // triggering JSX parser in .tsx files.
  const updateMutation = useMutation({
    mutationFn: async (payload: {
      proactive_monitoring_enabled?: boolean;
      email_check_interval_minutes?: number;
      calendar_check_interval_minutes?: number;
      billing_alert_threshold_usd?: number;
    }) => {
      return updatePreferences(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["preferences"] });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  const handleSave = useCallback(() => {
    setSaveSuccess(false);
    updateMutation.mutate({
      proactive_monitoring_enabled: settings.proactive_monitoring_enabled,
      email_check_interval_minutes: settings.email_check_interval_minutes,
      calendar_check_interval_minutes: settings.calendar_check_interval_minutes,
      billing_alert_threshold_usd: settings.billing_alert_threshold_usd,
    });
  }, [settings, updateMutation]);

  const handleChange = useCallback((partial: Partial<ProactiveSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }));
    setSaveSuccess(false);
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12" role="status" aria-label="Loading preferences">
        <span className="text-sm text-zinc-400">Loading preferences…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded border border-red-800 bg-red-900/20 p-4 text-sm text-red-300" role="alert">
        Failed to load preferences: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }

  const isSaving = updateMutation.isPending;

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Settings</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Configure how MindForge monitors your inbox, calendar, and billing.
        </p>
      </div>

      {/* Proactive Monitoring section */}
      <ProactiveSection
        settings={settings}
        onChange={handleChange}
        disabled={isSaving}
      />

      {/* Save bar */}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900"
        >
          {isSaving ? "Saving…" : "Save preferences"}
        </button>

        {saveSuccess && (
          <span className="text-sm text-green-400" role="status" aria-live="polite">
            ✓ Preferences saved
          </span>
        )}

        {updateMutation.isError && (
          <span className="text-sm text-red-400" role="alert">
            Failed to save. Please try again.
          </span>
        )}
      </div>
    </div>
  );
}