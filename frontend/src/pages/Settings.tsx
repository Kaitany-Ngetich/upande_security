import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { Card } from "@/components/Card";
import { PageShell } from "@/components/PageShell";
import { RefreshButton } from "@/components/RefreshButton";
import { SearchInput } from "@/components/SearchInput";
import { FieldInput, visible, type FieldMeta } from "@/components/settings/FieldInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { call, isError } from "@/lib/frappe";
import { cn } from "@/lib/utils";

const M = "upande_security.api.dashboard_v2";
type Values = Record<string, unknown>;
type Row = Record<string, unknown> & { name?: string };
interface Form {
  fields: FieldMeta[];
  children: Record<string, FieldMeta[]>;
  values: Values;
  modified: string;
  can_write: boolean;
  terms: Record<string, string>;
}
interface Section { key: string; label: string; description: string | null; collapsible: boolean; dep: FieldMeta | null; fields: FieldMeta[] }

const LAYOUT = new Set(["Section Break", "Column Break", "Tab Break"]);
const TABLE = new Set(["Table", "Table MultiSelect"]);
const TERM_KEYS = ["use_custom_words", "site_label", "site_label_plural", "area_label", "area_label_plural"];

/** The doctype's fields cut into its own sections, in order. */
function sectionsOf(fields: FieldMeta[]): Section[] {
  const out: Section[] = [];
  let cur: Section = { key: "general", label: "General", description: null, collapsible: false, dep: null, fields: [] };
  for (const f of fields) {
    if (f.fieldtype === "Section Break" || f.fieldtype === "Tab Break") {
      if (cur.fields.length) out.push(cur);
      cur = { key: f.fieldname, label: f.label || "", description: f.description, collapsible: !!f.collapsible, dep: f.depends_on ? f : null, fields: [] };
    } else if (!LAYOUT.has(f.fieldtype)) {
      cur.fields.push(f);
    }
  }
  if (cur.fields.length) out.push(cur);
  // A section with no label takes its first field's (e.g. a table on its own).
  return out.map((s) => ({ ...s, label: s.label || s.fields[0]?.label || "Settings" }));
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const matches = (f: FieldMeta, q: string) => `${f.label ?? ""} ${f.description ?? ""} ${f.fieldname}`.toLowerCase().includes(q);

/** Security Ops Settings, drawn from the doctype itself. */
export function Settings() {
  const toast = useToast();
  const [form, setForm] = useState<Form | null>(null);
  const [values, setValues] = useState<Values>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const r = await call<Form>(`${M}.settings_form`);
    if (isError(r)) return void toast(r.error, "error");
    setForm(r);
    setValues(structuredClone(r.values));
  }, [toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const sections = useMemo(() => (form ? sectionsOf(form.fields) : []), [form]);
  const q = search.trim().toLowerCase();
  const shown = useMemo(
    () => sections.filter((s) => !q || s.label.toLowerCase().includes(q) || s.fields.some((f) => matches(f, q))),
    [sections, q],
  );
  const changed = useMemo(
    () => (form ? Object.keys(values).filter((k) => !same(values[k], form.values[k])) : []),
    [values, form],
  );
  const can = !!form?.can_write;
  const isOpen = (s: Section) => (q ? true : open[s.key] ?? !s.collapsible);
  const set = (k: string, v: unknown) => setValues((cur) => ({ ...cur, [k]: v }));

  const save = async () => {
    if (!form || !changed.length) return;
    setSaving(true);
    const payload = Object.fromEntries(changed.map((k) => [k, values[k]]));
    const r = await call<{ ok: true; modified: string }>(`${M}.save_settings`, { values: payload, modified: form.modified });
    setSaving(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`Settings saved (${changed.length} change${changed.length === 1 ? "" : "s"}).`, "ok");
    // New words change every page's labels: start the app afresh with them.
    if (changed.some((k) => TERM_KEYS.includes(k))) {
      window.setTimeout(() => window.location.reload(), 700);
      return;
    }
    void load();
  };

  return (
    <PageShell
      title="Settings"
      eyebrow="Admin"
      actions={
        <>
          <SearchInput value={search} onChange={setSearch} placeholder="Find a setting" aria-label="Find a setting" />
          <RefreshButton onClick={() => void load()} loading={!form} label="Reload settings" />
        </>
      }
      description={form && !can ? "Read only: only a Security Head or System Manager changes these." : "Security Ops Settings. Every save goes through the same checks as Desk."}
    >
      {!form ? (
        <p className="text-[13px] text-[var(--sd-muted)]">Loading…</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
          <nav aria-label="Settings sections" className="hidden lg:block">
            <ul className="sticky top-4 flex max-h-[calc(100vh-6rem)] flex-col gap-0.5 overflow-auto text-[13px]">
              {shown.map((s) => (
                <li key={s.key}>
                  <button
                    type="button"
                    className="w-full rounded-md px-2.5 py-1.5 text-left text-[var(--sd-muted)] hover:bg-[var(--sd-line-soft)] hover:text-[var(--sd-ink)]"
                    onClick={() => {
                      setOpen((o) => ({ ...o, [s.key]: true }));
                      window.setTimeout(() => document.getElementById(`set-${s.key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
                    }}
                  >
                    {s.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <div className="flex min-w-0 flex-col gap-4 pb-24">
            {shown.length === 0 && <p className="text-[13px] text-[var(--sd-muted)]">No setting matches “{search}”.</p>}
            {shown.map((s) => {
              const hidden = s.dep && !visible(s.dep, values);
              const fields = q && !s.label.toLowerCase().includes(q) ? s.fields.filter((f) => matches(f, q)) : s.fields;
              return (
                <Card key={s.key} className={cn("scroll-mt-4", hidden && "opacity-60")}>
                  <div id={`set-${s.key}`} className="scroll-mt-4" />
                  <button
                    type="button" aria-expanded={isOpen(s)}
                    onClick={() => setOpen((o) => ({ ...o, [s.key]: !isOpen(s) }))}
                    className="flex w-full items-start gap-2 px-4 py-3 text-left"
                  >
                    {isOpen(s) ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" />}
                    <span>
                      <span className="text-[15px] font-semibold text-[var(--sd-ink)]">{s.label}</span>
                      {hidden && <span className="ml-2 text-[12px] text-[var(--sd-quiet)]">(off: its feature flag is not on)</span>}
                      {s.description && <span className="mt-0.5 block text-[12px] text-[var(--sd-muted)]">{s.description}</span>}
                    </span>
                  </button>
                  {isOpen(s) && (
                    <div className="grid gap-x-6 gap-y-4 px-4 pb-4 md:grid-cols-2">
                      {fields.filter((f) => visible(f, values)).map((f) =>
                        TABLE.has(f.fieldtype) ? (
                          <div key={f.fieldname} className="md:col-span-2">
                            <TableEditor
                              df={f} cols={form.children[f.options || ""] ?? []} rows={(values[f.fieldname] as Row[]) ?? []}
                              onChange={(rows) => set(f.fieldname, rows)} disabled={!can}
                            />
                          </div>
                        ) : f.fieldtype === "HTML" ? (
                          // App-defined markup from the doctype itself (e.g. a link to the emergency contacts list).
                          <div key={f.fieldname} className="text-[13px] md:col-span-2" dangerouslySetInnerHTML={{ __html: f.options || "" }} />
                        ) : f.fieldtype === "Button" ? null : (
                          <Field key={f.fieldname} df={f} value={values[f.fieldname]} onChange={(v) => set(f.fieldname, v)} disabled={!can}
                            dirty={!same(values[f.fieldname], form.values[f.fieldname])} />
                        ),
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {changed.length > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
          <div className="flex items-center gap-3 rounded-full border border-[var(--sd-line)] bg-[var(--sd-card)] px-4 py-2 shadow-[var(--sd-shadow-3)]">
            <span className="text-[13px]">{changed.length} unsaved change{changed.length === 1 ? "" : "s"}</span>
            <Button size="sm" variant="outline" disabled={saving} onClick={() => form && setValues(structuredClone(form.values))}>Discard</Button>
            <Button size="sm" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}

/** A labelled field; a Check sits beside its label, everything else under it. */
function Field({ df, value, onChange, disabled, dirty }: { df: FieldMeta; value: unknown; onChange: (v: unknown) => void; disabled: boolean; dirty?: boolean }) {
  const id = `f-${df.fieldname}`;
  const label = (
    <label htmlFor={id} className="text-[13px] font-medium text-[var(--sd-ink)]">
      {df.label || df.fieldname}
      {!!df.reqd && <span className="text-[var(--sd-data-red)]"> *</span>}
      {dirty && <span className="ml-1.5 text-[11px] font-normal text-[var(--sd-target)]">changed</span>}
    </label>
  );
  const help = df.description && <p className="text-[12px] leading-snug text-[var(--sd-muted)]">{df.description}</p>;
  if (df.fieldtype === "Check") {
    return (
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">{label}{help}</div>
        <FieldInput id={id} df={df} value={value} onChange={onChange} disabled={disabled} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      {label}
      <FieldInput id={id} df={df} value={value} onChange={onChange} disabled={disabled} />
      {help}
    </div>
  );
}

/** A child table: one card per row, its list columns as a summary, every field when opened. */
function TableEditor({ df, cols, rows, onChange, disabled }: {
  df: FieldMeta; cols: FieldMeta[]; rows: Row[]; onChange: (rows: Row[]) => void; disabled: boolean;
}) {
  const [openRow, setOpenRow] = useState<number | null>(null);
  const editable = cols.filter((c) => !LAYOUT.has(c.fieldtype) && c.fieldtype !== "HTML" && c.fieldtype !== "Button");
  const summary = (editable.filter((c) => c.in_list_view).length ? editable.filter((c) => c.in_list_view) : editable).slice(0, 4);
  const setCell = (i: number, k: string, v: unknown) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const add = () => {
    const blank: Row = { name: `new-${Date.now()}` };
    for (const c of editable) if (c.default != null) blank[c.fieldname] = c.fieldtype === "Check" || c.fieldtype === "Int" ? Number(c.default) : c.default;
    onChange([...rows, blank]);
    setOpenRow(rows.length);
  };
  const show = (c: FieldMeta, v: unknown) => (c.fieldtype === "Check" ? (Number(v) ? "Yes" : "No") : v === null || v === undefined || v === "" ? "—" : String(v));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium">{df.label} <span className="font-normal text-[var(--sd-quiet)]">({rows.length})</span></span>
        {!disabled && <Button size="sm" variant="outline" onClick={add}><Plus className="mr-1 h-3.5 w-3.5" /> Add row</Button>}
      </div>
      {df.description && <p className="text-[12px] text-[var(--sd-muted)]">{df.description}</p>}
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-[var(--sd-line)] px-3 py-3 text-[12px] text-[var(--sd-quiet)]">No rows.</p>
      ) : (
        <div className="overflow-hidden rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line-soft)]">
          {rows.map((r, i) => (
            <div key={(r.name as string) || i} className="border-t border-[var(--sd-line-soft)] first:border-t-0">
              <div className="flex items-center gap-2 px-3 py-2">
                <button type="button" className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-0.5 text-left text-[13px]" onClick={() => setOpenRow(openRow === i ? null : i)}>
                  {openRow === i ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                  {summary.map((c) => (
                    <span key={c.fieldname} className="min-w-0 truncate"><span className="text-[11px] text-[var(--sd-quiet)]">{c.label}: </span>{show(c, r[c.fieldname])}</span>
                  ))}
                </button>
                {!disabled && (
                  <button type="button" aria-label="Remove row" title="Remove row" className="grid size-7 place-items-center rounded-md text-[var(--sd-quiet)] hover:bg-[var(--sd-line-soft)] hover:text-[var(--sd-data-red)]"
                    onClick={() => { onChange(rows.filter((_, j) => j !== i)); setOpenRow(null); }}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {openRow === i && (
                <div className="grid gap-x-6 gap-y-3 bg-[var(--sd-line-soft)]/30 px-3 py-3 md:grid-cols-2">
                  {editable.filter((c) => visible(c, r)).map((c) => (
                    <Field key={c.fieldname} df={c} value={r[c.fieldname]} onChange={(v) => setCell(i, c.fieldname, v)} disabled={disabled} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
