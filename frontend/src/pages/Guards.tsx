import { useCallback, useEffect, useState } from "react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { EmployeePicker } from "@/components/EmployeePicker";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { PillTabs } from "@/components/PillTabs";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Picker } from "@/components/ui/picker";
import { isError } from "@/lib/frappe";
import { guardBoard, saveGuard, type Guard } from "@/lib/registers-api";
import { routeHash } from "@/lib/router";
import { useScope, useTerms } from "@/lib/scope";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 100;

/** The external guards: where each is posted, who relieves them, and whether they turn up. */
export function Guards() {
  const toast = useToast();
  const { scope } = useScope();
  const [status, setStatus] = useState("Active");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof guardBoard>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Guard | null>(null);

  useEffect(() => setStart(0), [status, q, scope]);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await guardBoard({ status, company: scope.company || undefined, farm: scope.farm || undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [status, scope, q, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const d = data && !isError(data) ? data : null;
  const c = d?.counts ?? {};
  const today = new Date().toISOString().slice(0, 10);

  return (
    <PageShell
      title="Guards"
      eyebrow="Scheduling"
      tabs={<PillTabs label="Status" value={status} onChange={setStatus} tabs={["Active", "Suspended", "Inactive", "Left"].map((s) => ({ key: s, label: s, count: c[s] ?? 0 }))} />}
      actions={
        <>
          <ScopePicker />
          <SearchInput value={search} onChange={setSearch} placeholder="Name, post" aria-label="Search guards" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh guards" />
        </>
      }
      description={
        <>External guards, planned in the <a className="underline" href={routeHash("schedule")}>monthly schedule</a>. Staff guards come from HR.{d && !d.can_edit ? " Posting changes are made by HR or a System Manager." : ""}</>
      }
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Guard</th><th className={TH}>Posted at</th><th className={TH}>Reliever</th><th className={TH}>Shifts this week</th><th className={TH}>Last punch</th><th className={TH}>App</th><th className={TH} /></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={7} rows={6} /> : d.rows.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-10 text-center text-[var(--sd-muted)]">No guards here.</td></tr>
              ) : d.rows.map((g) => (
                <tr key={g.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                  <td className={TD}>{g.full_name}<div className="text-[12px] text-[var(--sd-quiet)]">{[g.name, g.designation].filter(Boolean).join(" · ")}</div></td>
                  <td className={TD}>{g.farm || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{g.post || <span className="text-[var(--sd-target)]">no post: not on the schedule</span>}</div></td>
                  <td className={TD}>{g.reliever_name || <span className="text-[var(--sd-quiet)]">—</span>}</td>
                  <td className={`${TD} tabular-nums`}>{g.shifts_this_week}</td>
                  <td className={`${TD} tabular-nums`}>
                    {g.last_punch ? <span className={g.last_punch.slice(0, 10) === today ? "" : "text-[var(--sd-muted)]"}>{when(g.last_punch)}</span> : <span className="text-[var(--sd-quiet)]">never</span>}
                  </td>
                  <td className={TD}>{g.app_version ? <span>{g.app_version}<div className="text-[12px] text-[var(--sd-quiet)]">opened {when(g.app_last_open)}</div></span> : <Verdict ok={null}>No app</Verdict>}</td>
                  <td className={`${TD} text-right`}>{d.can_edit && <Button size="sm" variant="outline" onClick={() => setEditing(g)}>Posting</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={d?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>
      <PostingDialog guard={editing} onClose={() => setEditing(null)} onDone={load} />
    </PageShell>
  );
}

function PostingDialog({ guard, onClose, onDone }: { guard: Guard | null; onClose: () => void; onDone: () => void }) {
  const T = useTerms();
  const toast = useToast();
  const { boot } = useScope();
  const [farm, setFarm] = useState("");
  const [post, setPost] = useState("");
  // "" = keep the current reliever; "none" = no reliever; else the new one.
  const [reliever, setReliever] = useState("");
  const [status, setStatus] = useState("Active");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!guard) return;
    setFarm(guard.farm || "");
    setPost(guard.post || "");
    setReliever("");
    setStatus(guard.status);
  }, [guard]);
  const save = async () => {
    if (!guard) return;
    setBusy(true);
    const r = await saveGuard({
      name: guard.name, farm, post: post.trim(), status,
      reliever: reliever === "none" ? "" : reliever || guard.reliever || "",
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${guard.full_name}'s posting saved.`, "ok");
    onClose();
    onDone();
  };
  return (
    <Dialog open={!!guard} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{guard?.full_name}</DialogTitle>
          <DialogDescription>A guard appears on the monthly schedule when Active with a {T.site} and a post. The reliever is booked first when they take a day off.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="flex flex-col gap-1.5"><Label htmlFor="gp-farm">{T.Site}</Label><Picker id="gp-farm" label={T.Site} value={farm} onChange={setFarm} options={boot.farms.map((f) => f.name)} placeholder="Choose" /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="gp-post">Post</Label><Input id="gp-post" value={post} onChange={(e) => setPost(e.target.value)} placeholder="e.g. Main Gate" /></div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="gp-rel">Designated reliever</Label>
            <span className="text-[12px] text-[var(--sd-muted)]">
              {reliever === "none" ? "None" : guard?.reliever_name ? `Now: ${guard.reliever_name}` : "None yet"}
              {guard?.reliever && reliever !== "none" && (
                <button type="button" className="ml-2 underline" onClick={() => setReliever("none")}>remove</button>
              )}
            </span>
            <EmployeePicker id="gp-rel" doctype="Security Guard" placeholder="Search to change" value={reliever === "none" ? "" : reliever} onChange={(id) => setReliever(id)} />
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="gp-st">Status</Label><Picker id="gp-st" label="Status" value={status} onChange={setStatus} options={["Active", "Suspended", "Inactive", "Left"]} /></div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
