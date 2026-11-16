# UI primitives (SCP design parity)

Ported from Upande SCP (kaitet). Use these instead of native `<select>`, `<input type="date">`
or ad-hoc pills. Everything is Poppins; numbers use tabular figures (`tabular-nums` is on by
default on `body`; never use a mono font for figures or IDs).

Tokens: `--sd-*` (ink, paper, line, quiet, shadows, alerts) and shadcn tokens (`--primary`,
`--card`, `--border` ...) both work. Cards: `bg-[var(--sd-card)] rounded-[var(--sd-radius-lg)] shadow-[var(--sd-shadow-1)]`.

## Page frame

### PageShell  (`@/components/PageShell`)
The frame every view renders. Renders SCP's `PageHeader` (eyebrow with thin rule, big title,
ONE toolbar row) then a padded body (`px-4 md:px-6`). Do not add your own page padding.
Props: `title`, `eyebrow` (default "Upande Security"; pass the crop name), `actions`
(right side of the toolbar row: filters, refresh, buttons), `tabs` (left side: pill tabs),
`filters` (`ToolbarFilter[]`, tab-scoped) + `tab` (active tab id), `description` (quiet line
under the toolbar), `children`.
```tsx
<PageShell title="Approvals" eyebrow={crop.name} tabs={<TabsList>...</TabsList>}
  actions={<><DateRangePicker value={r} onChange={setR} /><ClearFiltersPill active={dirty} onClear={reset} /></>}>
```
`Page` (same file) is the bare padded container, for stubs.

### PageHeader  (`@/components/PageHeader`)
Same header without the body wrapper. Props: `title`, `eyebrow`, `switcher` (left),
`filters`, `tab`, `children` (right cluster). Exports `PAGE_HEADER_CLASS` etc.

### PageToolbar  (`@/components/PageToolbar`)
The one-row toolbar: `left` (tabs) ... right-aligned `filters`/`children`. Props: `left`,
`children`, `filters: {key, tabs?, node}[]`, `tab`, `className`. Filters tagged with `tabs`
fade out when the active `tab` is not listed (state survives).
```tsx
<PageToolbar left={<TabsList/>} filters={[{ key: "farm", tabs: ["plan"], node: <FilterSelect .../> }]} tab={tab}>
  <RefreshButton />
</PageToolbar>
```

## Toolbar controls (all share the `HEADER_PILL` look: 36px tall, fully round, soft shadow)

### FilterSelect  (`@/components/FilterSelect`)
Replaces native selects. Props: `value: string`, `onChange(next)`, `options: (string | {value,label})[]`,
`label` (accessible name AND placeholder) or `aria-label`, `allLabel?` ("All farms" -> option
that means `""`), `placeholder?`, `format?(option)` (for string options), `disabled`, `className`.
```tsx
<FilterSelect label="Farm" value={farm} onChange={setFarm} options={farms} allLabel="All farms" />
<FilterSelect aria-label="Status" value={s} onChange={setS} options={[{ value: "p", label: "Pending" }]} />
```

### DateRangePicker  (`@/components/DateRangePicker`)
Range calendar with presets, month/year zoom and a Counter (wheels) mode. No typed dates.
Props: `value: {from, to}` (YYYY-MM-DD), `onChange(range)`, `min?`, `max?`, `presets?`
(`{label, range: () => DateRange}[]`, after built-ins), `allowSingleDay=true`, `weekStartsOn=1`,
`label="Date range"` (accessible name), `variant="pill" | "field"` (field = bordered, for dialogs),
`disabled`, `className`. Also exports `DateRange`, `formatRange`, `builtInPresets`.
```tsx
const [range, setRange] = useState<DateRange>(currentWeekRange());   // from "@/lib/utils"
<DateRangePicker label="Period" value={range} onChange={setRange} max={todayISO()} />
```
Single date (existing): `DatePicker` (`@/components/DatePicker`); week: `WeekPicker`.

### TogglePill  (`@/components/TogglePill`)
On/off filter in the pill shape; on = check mark + tint. Props: `pressed`, `onPressedChange(next)`,
plus button props.
```tsx
<TogglePill pressed={byFarm} onPressedChange={setByFarm}>Group by farm</TogglePill>
```

### ClearFiltersPill  (`@/components/ClearFiltersPill`)
Red "Clear" pill; renders nothing unless `active`. Props: `active`, `onClear`, `label="Clear"`.
```tsx
<ClearFiltersPill active={!!farm || !!status} onClear={() => { setFarm(""); setStatus(""); }} />
```

### ToolbarButton  (`@/components/ToolbarButton`)
Text action in the toolbar ("New cycle", "Approve 3"). Plain `<button>` props; `type="button"` default.
```tsx
<ToolbarButton onClick={add}><Plus className="h-4 w-4" /> New cycle</ToolbarButton>
```
Icon-only round button: `HeaderIconButton` from `@/components/header-controls`
(`aria-label` required, optional `tooltip`, `active`). `HEADER_PILL` (same file) is the
class string if you need the pill on something else. Refresh: `RefreshButton`.

### SearchInput  (`@/components/SearchInput`)
Rounded search box with magnifier and clear (x). `onChange` gets the text. Props: `value`,
`onChange(text)`, `size="sm" | "md"` (md for toolbars), `placeholder`, `className` (wrapper).
```tsx
<SearchInput size="md" value={q} onChange={setQ} placeholder="Search blocks" className="w-56" />
```

### TreePicker  (`@/components/TreePicker`)
Multi-select for hierarchies (farm -> block): pill that opens a searchable tree with round dots.
Props: `label`, `nodes: TreeNode[]` (`{id, label, search?, count?, children?}`), `checked: Set<string>`,
`onChange(next: Set<string>)`, `icon?`, `count?`, `emptyHint?`, `searchPlaceholder?`, `disabled`.
Selecting a group row selects the group id only; its icons select/clear all children.
`TreePickerPanel` is the same panel without the pill (for use inside your own popover).
```tsx
<TreePicker label="Blocks" nodes={tree} checked={sel} onChange={setSel} />
```

### TimePicker / WheelColumn / WheelStepper  (`TimePicker`, `WheelPicker`)
Odometer time picker (`value` "HH:mm", `onChange`) and its draggable wheel pieces. Only needed
for time entry; DateRangePicker already uses them.

## Cards and figures

### KpiCard  (`@/components/KpiCard`)  (alias `Kpi`; layout helper `KpiGrid`)
White card: uppercase label, 44px figure, hint, optional UFD-style sparkline top-right and a
delta pill. Props: `label`, `value` (numbers get thousands separators), `hint?`,
`tone="default" | "warning" | "critical" | "good"`, `series?: {week: string; value: number}[]`
(oldest first; delta = last vs previous), `goodDirection?: "up" | "down"` (tints the delta),
`deltaLabel?` (default "vs prev week"), `loading?` (keeps the label, pulses figure and hint),
`className`. `KpiGrid` props: `cols=2|3|4`.
```tsx
<KpiGrid cols={4}><KpiCard label="Done this week" value={done} hint="of 120 planned" series={weekly} goodDirection="up" loading={firstLoad(loading, !!data)} /></KpiGrid>
```
`Sparkline` (`@/components/Sparkline`) is the bare trend line (`points`) if you need it elsewhere;
`seriesDelta(points)` gives `{dir, pct, abs}`.

### Figure  (`@/components/Figure`)  existing figure/label tiles; `ScrollTable` existing scroll box.

## Loading (`@/components/Loading`)
The frame paints at once; only data slots pulse. No full-page spinners.
- `firstLoad(loading, hasData)` true only on the first load (a refresh keeps old data).
- `Bar` (sized by class, e.g. `h-4 w-24`), `TextSkeleton`, `KpiValueSkeleton`, `AvatarSkeleton`,
  `RowsSkeleton rows`, `TableRowsSkeleton cols rows avatar` (inside a real `<TableBody>`),
  `ChartSkeleton height`, `PageSkeleton title? eyebrow?`, `MapPageSkeleton`.
- `LoadProgress active progress? label?` inline slow-load bar under the header (`ProgressBar`).
```tsx
<TableBody>{firstLoad(loading, !!rows) ? <TableRowsSkeleton cols={5} /> : rows.map(...)}</TableBody>
```

## Toasts (`@/components/Toast`)
Floating desk-style toasts, bottom right; max 3; errors never time out. `useToast()` returns
`toast(text, tone?, opts?)` with tone `"ok" | "error" | "warn" | "info"` (`"err"` also accepted),
`opts = { hint?, ms? }`; also `toast.show` / `toast.dismiss(id)`. Needs `ToastProvider` (in App).
```tsx
const toast = useToast();
toast("Approved 3 entries."); toast(err.message, "error", { hint: "Check the quantity." });
```

## Sidebar
`AppSidebar` is crop-scoped (groups from `lib/nav.ts`). Optional `pendingApprovals` prop shows
a red count on the Approvals item.

## Utilities (`@/lib/utils`)
`cn`, `ymd`, `currentWeekRange`, `parseYmd` (returns `Date | undefined`), `todayISO`, `matchesQuery(text, query)`,
`to12h`/`from12h`/`format12h`/`stepTime`. Motion classes in `index.css`: `scp-card-in`,
`scp-panel-in`, `scp-fade-in`; `.scp-map-credit` for the map's small credit.
