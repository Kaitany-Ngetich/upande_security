import { useCallback, useEffect, useState } from "react";
import type { DateRange } from "@/components/DateRangePicker";
import { useToast } from "@/components/Toast";
import { isError } from "@/lib/frappe";
import { gateLog, type LogKind, type LogPage } from "@/lib/gate-api";
import { useScope } from "@/lib/scope";
import { todayISO } from "@/lib/utils";

export const LOG_PAGE = 50;

/** One gate log (dispatch / receiving / vehicles): filters, paging, reload. */
export function useGateLog<T>(kind: LogKind) {
  const toast = useToast();
  const { scope } = useScope();
  const [range, setRange] = useState<DateRange>({ from: todayISO(), to: todayISO() });
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [page, setPage] = useState<LogPage<T> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [range, status, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await gateLog<T>({
      kind, from_date: range.from, to_date: range.to, company: scope.company || undefined,
      farm: scope.farm || undefined, status: status || undefined, search: debounced || undefined,
      start, page_length: LOG_PAGE,
    });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setPage(r as LogPage<T>);
  }, [kind, range, scope, status, debounced, start, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = !!status || !!search || range.from !== todayISO() || range.to !== todayISO();
  const clear = () => {
    setStatus("");
    setSearch("");
    setRange({ from: todayISO(), to: todayISO() });
  };
  return { range, setRange, status, setStatus, search, setSearch, start, setStart, page, loading, load, dirty, clear };
}
