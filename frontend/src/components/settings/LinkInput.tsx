import { useEffect, useId, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { searchLink } from "@/lib/frappe";

/**
 * A Link field: type a record's name, with matching records suggested as you
 * type (Frappe's own permission-checked link search). The server checks the
 * record exists when the form is saved.
 */
export function LinkInput({ doctype, value, onChange, disabled, id }: {
  doctype: string; value: string; onChange: (v: string) => void; disabled?: boolean; id?: string;
}) {
  const listId = useId();
  const [hits, setHits] = useState<{ value: string; description: string }[]>([]);
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    const t = window.setTimeout(() => {
      void searchLink(doctype, value || "", 12).then((rows) => mine === seq.current && setHits(rows ?? []));
    }, 250);
    return () => window.clearTimeout(t);
  }, [doctype, value]);
  return (
    <>
      <Input id={id} list={listId} value={value} disabled={disabled} placeholder={doctype} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
      <datalist id={listId}>
        {hits.map((h) => <option key={h.value} value={h.value}>{h.description}</option>)}
      </datalist>
    </>
  );
}
