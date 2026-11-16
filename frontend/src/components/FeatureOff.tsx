import { PageShell } from "@/components/PageShell";

/** A gate operation switched off in Security Ops Settings. */
export function FeatureOff({ title, what }: { title: string; what: string }) {
  return (
    <PageShell title={title} eyebrow="Gate operations">
      <div className="max-w-xl rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] px-5 py-5 text-[13px] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)]">
        {what} is switched off on this site. A System Manager can turn it on in{" "}
        <a className="underline" href="/app/security-ops-settings">Security Ops Settings</a>.
      </div>
    </PageShell>
  );
}
