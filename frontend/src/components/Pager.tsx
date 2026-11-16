import { Button } from "@/components/ui/button";

export function Pager({ start, total, page, loading, onChange }: {
  start: number; total: number; page: number; loading: boolean; onChange: (start: number) => void;
}) {
  if (total <= page) return null;
  return (
    <div className="flex items-center justify-between border-t border-[var(--sd-line-soft)] px-4 py-3 text-[12px] text-[var(--sd-muted)]">
      <span className="tabular-nums">{start + 1}–{Math.min(start + page, total)} of {total}</span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={start === 0 || loading} onClick={() => onChange(Math.max(0, start - page))}>Previous</Button>
        <Button size="sm" variant="outline" disabled={start + page >= total || loading} onClick={() => onChange(start + page)}>Next</Button>
      </div>
    </div>
  );
}
