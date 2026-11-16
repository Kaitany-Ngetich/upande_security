import { Input } from "@/components/ui/input";
import { Picker } from "@/components/ui/picker";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { LinkInput } from "@/components/settings/LinkInput";

export interface FieldMeta {
  fieldname: string; fieldtype: string; label: string | null; options: string | null; description: string | null;
  default: string | null; reqd: number; read_only: number; depends_on: string | null; collapsible: number; in_list_view: number;
}

/** "eval:doc.x", "eval:!doc.x", "eval:doc.x=='v'" - the forms this doctype uses; anything else shows. */
export function visible(df: FieldMeta, doc: Record<string, unknown>): boolean {
  const dep = (df.depends_on || "").trim();
  if (!dep) return true;
  const expr = dep.replace(/^eval:\s*/, "");
  let m = /^(!?)doc\.(\w+)$/.exec(expr);
  if (m) return m[1] ? !doc[m[2]] : !!doc[m[2]];
  m = /^doc\.(\w+)\s*(==|!=)=?\s*["'](.*)["']$/.exec(expr);
  if (m) return m[2] === "==" ? String(doc[m[1]] ?? "") === m[3] : String(doc[m[1]] ?? "") !== m[3];
  if (/^\w+$/.test(dep)) return !!doc[dep];
  return true;
}

const asText = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** One field of a Frappe doctype, drawn as the matching v2 control. */
export function FieldInput({ df, value, onChange, disabled, id }: {
  df: FieldMeta; value: unknown; onChange: (v: unknown) => void; disabled?: boolean; id?: string;
}) {
  const ro = disabled || !!df.read_only;
  switch (df.fieldtype) {
    case "Check":
      return <Switch id={id} checked={!!Number(value)} disabled={ro} onCheckedChange={(c) => onChange(c ? 1 : 0)} />;
    case "Int":
    case "Float":
    case "Currency":
    case "Percent":
      return (
        <Input id={id} type="number" step={df.fieldtype === "Int" ? 1 : "any"} value={asText(value)} disabled={ro}
          onChange={(e) => onChange(e.target.value === "" ? null : df.fieldtype === "Int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value))} />
      );
    case "Select": {
      const opts = (df.options || "").split("\n").filter((o) => o !== "");
      return <Picker id={id} label={df.label || df.fieldname} value={asText(value)} onChange={onChange} options={opts} disabled={ro} clearable={!df.reqd} placeholder="—" />;
    }
    case "Link":
      return <LinkInput id={id} doctype={df.options || ""} value={asText(value)} onChange={onChange} disabled={ro} />;
    case "Time":
      return <Input id={id} type="time" value={asText(value).slice(0, 5)} disabled={ro} onChange={(e) => onChange(e.target.value ? `${e.target.value}:00` : null)} />;
    case "Date":
      return <Input id={id} type="date" value={asText(value).slice(0, 10)} disabled={ro} onChange={(e) => onChange(e.target.value || null)} />;
    case "Color":
      return <Input id={id} type="color" className="h-9 w-16 p-1" value={asText(value) || "#000000"} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    case "Small Text":
    case "Text":
    case "Long Text":
    case "Code":
    case "Text Editor":
      return <Textarea id={id} rows={df.fieldtype === "Small Text" ? 3 : 5} value={asText(value)} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    default:
      // Data, Autocomplete, Phone, and anything else plain.
      return <Input id={id} value={asText(value)} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
  }
}
