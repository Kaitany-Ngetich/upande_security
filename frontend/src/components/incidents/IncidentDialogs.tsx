import { useEffect, useState } from "react";
import { ExternalLink, ImagePlus, X } from "lucide-react";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Picker } from "@/components/ui/picker";
import { Textarea } from "@/components/ui/textarea";
import { isError, searchLink, uploadFile } from "@/lib/frappe";
import {
  attachIncidentPhotos, createIncident, incidentDetail, updateIncident,
  type IncidentDetail, type IncidentOptions, type IncidentPerson,
} from "@/lib/incidents-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

/** Severity is a reserved status colour, always shown with its word. */
export function SeverityTag({ severity }: { severity: string }) {
  const tone: Record<string, string> = {
    Critical: "bg-[var(--sd-alert-error)] text-[var(--sd-sev-critical)]",
    High: "bg-[var(--sd-alert-warn)] text-[var(--sd-sev-high)]",
    Medium: "bg-[var(--sd-line-soft)] text-[var(--sd-ink)]",
    Low: "bg-[var(--sd-line-soft)] text-[var(--sd-muted)]",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", tone[severity] ?? tone.Low)}>
      {(severity === "Critical" || severity === "High") && <span aria-hidden>▲</span>}
      {severity}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  if (children === null || children === undefined || children === "") return null;
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 text-[13px]">
      <span className="text-[var(--sd-quiet)]">{label}</span>
      <span className="whitespace-pre-wrap">{children}</span>
    </div>
  );
}

function People({ title, list }: { title: string; list?: IncidentPerson[] }) {
  if (!list?.length) return null;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-[var(--sd-quiet)]">{title}</span>
      {list.map((p, i) => (
        <div key={i} className="text-[13px]">
          {p.person_name || "—"}
          <span className="text-[var(--sd-quiet)]">{[p.person_type, p.contact, p.id_number].filter(Boolean).map((x) => ` · ${x}`).join("")}</span>
          {p.notes && <div className="text-[12px] text-[var(--sd-muted)]">{p.notes}</div>}
        </div>
      ))}
    </div>
  );
}

/** An incident in full, with the follow-up a Security Head records on it. */
export function IncidentDialog({ name, statuses, onClose, onChanged }: {
  name: string | null; statuses: string[]; onClose: () => void; onChanged: () => void;
}) {
  const toast = useToast();
  const [doc, setDoc] = useState<IncidentDetail | null>(null);
  const [status, setStatus] = useState("");
  const [resolution, setResolution] = useState("");
  const [actions, setActions] = useState("");
  const [assignee, setAssignee] = useState("");
  const [users, setUsers] = useState<{ value: string; label: string }[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDoc(null);
    if (!name) return;
    void incidentDetail(name).then((r) => {
      if (isError(r)) {
        toast(r.error, "error");
        onClose();
        return;
      }
      setDoc(r);
      setStatus(r.status || "Open");
      setResolution(r.resolution || "");
      setActions(r.corrective_actions || "");
      setAssignee(r.assigned_to || "");
    });
  }, [name, toast, onClose]);

  useEffect(() => {
    if (!doc?.can_manage) return;
    void searchLink("User", "", 50).then((rows) =>
      setUsers((rows ?? []).map((u) => ({ value: u.value, label: u.description ? `${u.description} (${u.value})` : u.value }))),
    );
  }, [doc?.can_manage]);

  const save = async () => {
    if (!doc) return;
    // Only what changed is sent: the endpoint treats a key it receives as an edit.
    const args: Parameters<typeof updateIncident>[0] = { name: doc.name };
    if (status !== (doc.status || "Open")) args.status = status;
    if (resolution !== (doc.resolution || "")) args.resolution = resolution;
    if (actions !== (doc.corrective_actions || "")) args.corrective_actions = actions;
    if (assignee !== (doc.assigned_to || "")) args.assigned_to = assignee;
    if (Object.keys(args).length === 1) return void onClose();
    if ((status === "Resolved" || status === "Closed") && !resolution.trim()) {
      return void toast("Say how the incident was resolved.", "warn");
    }
    setBusy(true);
    const r = await updateIncident(args);
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${doc.name} updated.`, "ok", { hint: args.status ? `Now ${args.status}` : undefined });
    onChanged();
    onClose();
  };

  const injury = doc?.nature_of_incident === "Workplace Injury";

  return (
    <Dialog open={!!name} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {doc ? <>{doc.nature_of_incident} <SeverityTag severity={doc.severity} /></> : name}
          </DialogTitle>
          <DialogDescription>
            {doc ? `${doc.name} · ${when(doc.incident_datetime)} · ${[doc.location, doc.farm].filter(Boolean).join(", ")}` : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {doc && (
          <div className="flex flex-col gap-4">
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{doc.description}</p>
            <div className="flex flex-col gap-1.5">
              <Row label="Reported by">{doc.reporter_name}</Row>
              <Row label="Status">{doc.status}</Row>
              <Row label="Assigned to">{doc.assigned_to}</Row>
              {injury && (
                <>
                  <Row label="Injury">{[doc.nature_of_injury, doc.body_part_affected].filter(Boolean).join(" · ") as string}</Row>
                  <Row label="Doing at the time">{doc.activity_at_time_of_injury as string}</Row>
                  <Row label="Case status">{doc.injury_case_status as string}</Row>
                  <Row label="DOSHS deadline">{doc.doshs_deadline as string}</Row>
                  {doc.is_fatal ? <Row label="Fatal">Yes</Row> : null}
                </>
              )}
              {doc.police_report_required ? <Row label="Police">{[doc.ob_number && `OB ${doc.ob_number}`, doc.police_station].filter(Boolean).join(" · ") as string || "Report required"}</Row> : null}
            </div>
            <People title="Victims" list={doc.victims} />
            <People title="Witnesses" list={doc.witnesses} />
            {doc.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {doc.attachments.map((u) => (
                  <a key={u} href={u} target="_blank" rel="noreferrer" className="block size-24 overflow-hidden rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)]">
                    <img src={u} alt="Incident photo" className="size-full object-cover" />
                  </a>
                ))}
              </div>
            )}

            {doc.can_manage ? (
              <div className="flex flex-col gap-3 border-t border-[var(--sd-line-soft)] pt-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="in-status">Status</Label>
                    <Picker id="in-status" label="Status" value={status} onChange={setStatus} options={statuses} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="in-assignee">Assigned to</Label>
                    <Picker id="in-assignee" label="Assigned to" value={assignee} onChange={setAssignee} options={users} clearable clearLabel="Nobody" placeholder="Nobody" />
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="in-res">Resolution</Label>
                  <Textarea id="in-res" rows={2} value={resolution} onChange={(e) => setResolution(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="in-act">Corrective actions</Label>
                  <Textarea id="in-act" rows={2} value={actions} onChange={(e) => setActions(e.target.value)} />
                </div>
              </div>
            ) : (
              <>
                {doc.resolution && <Row label="Resolution">{doc.resolution}</Row>}
                {doc.corrective_actions && <Row label="Corrective actions">{doc.corrective_actions}</Row>}
              </>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2">
              <a className="inline-flex items-center gap-1 text-[12px] text-[var(--sd-muted)] underline" href={`/app/incident-report/${encodeURIComponent(doc.name)}`}>
                <ExternalLink className="h-3.5 w-3.5" /> Full record{injury ? " (injury case, people, police)" : ""}
              </a>
              <div className="flex gap-2">
                <Button variant="outline" onClick={onClose} disabled={busy}>{doc.can_manage ? "Cancel" : "Close"}</Button>
                {doc.can_manage && <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const INJURIES = ["Cut/Laceration", "Fracture", "Burn", "Sprain/Strain", "Bruise/Contusion", "Head Injury", "Crush Injury", "Amputation", "Other"];

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

/** Report an incident from the dashboard - the same report the guard app files. */
export function ReportDialog({ open, options, onClose, onDone }: {
  open: boolean; options: IncidentOptions; onClose: () => void; onDone: (name: string) => void;
}) {
  const T = useTerms();
  const toast = useToast();
  const { scope, farmsInScope } = useScope();
  const [f, setF] = useState({
    when: nowLocal(), farm: "", location: "", category: "", severity: "", description: "", anonymous: false,
    activity: "", body: "", injury: "", injuryAt: "", fatal: false,
  });
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((c) => ({ ...c, [k]: v }));

  useEffect(() => {
    if (!open) return;
    setF({
      when: nowLocal(), farm: scope.farm || (farmsInScope.length === 1 ? farmsInScope[0] : ""), location: "", category: "",
      severity: "", description: "", anonymous: false, activity: "", body: "", injury: "", injuryAt: "", fatal: false,
    });
    setPhotos([]);
    setTried(false);
  }, [open, scope.farm, farmsInScope]);

  const injury = f.category === "Workplace Injury";
  const problems: string[] = [];
  if (!f.category) problems.push("Choose what happened.");
  if (!f.severity) problems.push("Choose how serious it is.");
  if (!f.location.trim()) problems.push("Say where it happened.");
  if (!f.description.trim()) problems.push("Describe what happened.");
  if (f.when && new Date(f.when) > new Date()) problems.push("The time cannot be in the future.");

  const save = async () => {
    setTried(true);
    if (problems.length) return;
    setBusy(true);
    const r = await createIncident({
      incident_datetime: f.when.replace("T", " ") + ":00",
      farm: f.farm || undefined,
      location: f.location.trim(),
      nature_of_incident: f.category,
      severity: f.severity,
      description: f.description.trim(),
      anonymous: f.anonymous ? "1" : undefined,
      ...(injury
        ? {
            activity_at_time_of_injury: f.activity.trim() || undefined,
            body_part_affected: f.body.trim() || undefined,
            nature_of_injury: f.injury || undefined,
            injury_current_location: f.injuryAt.trim() || undefined,
            is_fatal: f.fatal ? "1" : undefined,
          }
        : {}),
    });
    if (isError(r)) {
      setBusy(false);
      return void toast(r.error, "error");
    }
    let photoNote = "";
    if (photos.length && !f.anonymous) {
      const urls: string[] = [];
      for (const p of photos) {
        const u = await uploadFile(p, { isPrivate: true, doctype: "Incident Report", docname: r.name });
        if ("file_url" in u) urls.push(u.file_url);
      }
      const a = urls.length ? await attachIncidentPhotos(r.name, urls) : null;
      const added = a && !isError(a) ? a.attached : 0;
      if (added < photos.length) photoNote = `${photos.length - added} photo(s) could not be added.`;
    }
    setBusy(false);
    toast(`Incident ${r.name} reported.`, photoNote ? "warn" : "ok", { hint: photoNote || undefined });
    onClose();
    onDone(r.name);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Report an incident</DialogTitle>
          <DialogDescription>Filed exactly as a guard's report: the people set to be notified for it are told.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ri-cat">What happened</Label>
            <Picker
              id="ri-cat" label="What happened" value={f.category} placeholder="Choose a type"
              options={options.categories.map((c) => ({ value: c.name, label: c.category_name || c.name }))}
              onChange={(v) => {
                const cat = options.categories.find((c) => c.name === v);
                setF((c) => ({ ...c, category: v, severity: c.severity || cat?.default_severity || "" }));
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ri-sev">Severity</Label>
            <Picker id="ri-sev" label="Severity" value={f.severity} onChange={(v) => set("severity", v)} options={options.severities} placeholder="How serious" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ri-when">When</Label>
            <Input id="ri-when" type="datetime-local" value={f.when} max={nowLocal()} onChange={(e) => set("when", e.target.value)} />
          </div>
          {farmsInScope.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ri-farm">{T.Site}</Label>
              <Picker id="ri-farm" label={T.Site} value={f.farm} onChange={(v) => set("farm", v)} options={farmsInScope} clearable clearLabel="From my post" placeholder="From my post" />
            </div>
          )}
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="ri-loc">Where exactly</Label>
            <Input id="ri-loc" value={f.location} onChange={(e) => set("location", e.target.value)} placeholder="e.g. Greenhouse 4, north fence" />
          </div>
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="ri-desc">What happened</Label>
            <Textarea id="ri-desc" rows={4} value={f.description} onChange={(e) => set("description", e.target.value)} />
          </div>
          {injury && (
            <>
              <div className="flex flex-col gap-1.5"><Label htmlFor="ri-act">Doing at the time</Label><Input id="ri-act" value={f.activity} onChange={(e) => set("activity", e.target.value)} /></div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="ri-body">Body part</Label><Input id="ri-body" value={f.body} onChange={(e) => set("body", e.target.value)} /></div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ri-inj">Injury</Label>
                <Picker id="ri-inj" label="Injury" value={f.injury} onChange={(v) => set("injury", v)} options={INJURIES} clearable placeholder="Choose" />
              </div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="ri-at">Where the person is now</Label><Input id="ri-at" value={f.injuryAt} onChange={(e) => set("injuryAt", e.target.value)} /></div>
              <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
                <input type="checkbox" checked={f.fatal} onChange={(e) => set("fatal", e.target.checked)} /> Fatal
              </label>
            </>
          )}
        </div>

        <label className="flex items-start gap-2 text-[13px]">
          <input type="checkbox" className="mt-0.5" checked={f.anonymous} onChange={(e) => set("anonymous", e.target.checked)} />
          <span>File anonymously<span className="block text-[12px] text-[var(--sd-quiet)]">Nobody's name is kept on the report. Photos can't be added: a file always records who uploaded it.</span></span>
        </label>

        {!f.anonymous && (
          <div className="flex flex-col gap-2">
            <Label>Photos (up to 4)</Label>
            <div className="flex flex-wrap items-center gap-2">
              {photos.map((p, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-[var(--sd-line-soft)] px-2.5 py-1 text-[12px]">
                  {p.name}
                  <button type="button" aria-label={`Remove ${p.name}`} onClick={() => setPhotos((c) => c.filter((_, j) => j !== i))}><X className="h-3 w-3" /></button>
                </span>
              ))}
              {photos.length < 4 && (
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-[var(--sd-line)] px-3 py-1 text-[12px] hover:bg-[var(--sd-line-soft)]">
                  <ImagePlus className="h-3.5 w-3.5" /> Add photo
                  <input type="file" accept="image/*" className="sr-only" onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) setPhotos((c) => [...c, file].slice(0, 4));
                    e.target.value = "";
                  }} />
                </label>
              )}
            </div>
          </div>
        )}

        {tried && problems.length > 0 && (
          <ul className="list-disc pl-5 text-[13px] text-[var(--sd-data-red)]" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Report incident"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
