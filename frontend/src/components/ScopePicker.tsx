import { FilterSelect } from "@/components/FilterSelect";
import { useScope, useTerms } from "@/lib/scope";

/** Company and farm, shared by every page and remembered in this browser. */
export function ScopePicker() {
  const T = useTerms();
  const { boot, scope, setScope, farmsInScope } = useScope();
  return (
    <>
      {boot.companies.length > 1 && (
        <FilterSelect
          label="Company"
          value={scope.company}
          onChange={(company) => setScope({ company, farm: "" })}
          options={boot.companies}
          allLabel="All companies"
        />
      )}
      {farmsInScope.length > 1 && (
        <FilterSelect
          label={T.Site}
          value={scope.farm}
          onChange={(farm) => setScope({ ...scope, farm })}
          options={farmsInScope}
          allLabel={`All ${T.sites}`}
        />
      )}
    </>
  );
}
