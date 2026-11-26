import { FilterSelect } from "@/components/FilterSelect";
import { useTerms } from "@/lib/scope";

/** The gate actions on this page are recorded at - only shown when the farm has more than one. */
export function GatePostPicker({ farm, gates, gate, setGate }: {
  farm: string; gates: string[]; gate: string; setGate: (g: string) => void;
}) {
  if (!farm || gates.length < 2) return null;
  return <FilterSelect label="Gate" value={gate} onChange={setGate} options={gates} />;
}

/** Says where actions are recorded, so nobody books a truck at the wrong farm. */
export function PostLine({ farm, gate }: { farm: string; gate: string }) {
  const T = useTerms();
  return (
    <p className="text-[12px] text-[var(--sd-quiet)]">
      {farm ? (
        <>Recording at <span className="font-medium text-[var(--sd-ink)]">{farm}{gate ? ` · ${gate}` : ""}</span>. Your own posted {T.site}, if your login has one, takes precedence.</>
      ) : (
        <>Choose a {T.site} above to record at; otherwise your login's own posted {T.site} is used.</>
      )}
    </p>
  );
}
