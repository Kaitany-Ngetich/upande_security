import { useEffect, useState } from "react";

/** The value once it has stopped changing for `ms` (search boxes). */
export function useDebounced(value: string, ms = 300): string {
  const [v, setV] = useState(value.trim());
  useEffect(() => {
    const t = window.setTimeout(() => setV(value.trim()), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}
