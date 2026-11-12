import { useEffect, useState } from "react";
import { EmployeePicker } from "@/components/EmployeePicker";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Picker } from "@/components/ui/picker";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { useScope, useTerms } from "@/lib/scope";
import { checkIn, checkOut, farmGates, reviewVisit, walkIn, type Visit } from "@/lib/visitors-api";

const TRANSPORT = ["On Foot", "Vehicle", "Motorcycle", "Taxi"];

function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function Problems({ list }: { list: string[] }) {
  if (!list.length) return null;
  return (
    <ul className="list-disc pl-5 text-[13px] text-[var(--sd-data-red)]" role="alert">
      {list.map((p) => <li key={p}>{p}</li>)}
    </ul>
  );
}

function Actions({ busy, label, onCancel, onSave, tone }: {
  busy: boolean; label: string; onCancel: () => void; onSave: () => void; tone?: "danger";
}) {
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button>
      <Button variant={tone === "danger" ? "destructive" : "default"} onClick={onSave} disabled={busy}>
        {busy ? "Saving…" : label}
      </Button>
    </div>
  );
}

/** The gates of a visit's farm, for the entry / exit gate picker. */
function useGates(farm: string | null | undefined, open: boolean) {
  const [gates, setGates] = useState<string[]>([]);
  useEffect(() => {
    if (!open || !farm) {
      setGates([]);
      return;
    }
    void farmGates(farm).then((r) => setGates(isError(r) || !Array.isArray(r) ? [] : r.map((g) => g.gate_name)));
  }, [farm, open]);
  return gates;
}

function who(v: Visit) {
  return v.customer_name || v.name;
}

// --- check in ----------------------------------------------------------------------

export function CheckInDialog({ visit, onClose, onDone }: { visit: Visit | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const open = !!visit;
  const gates = useGates(visit?.custom_farmunit, open);
  const [gate, setGate] = useState("");
  const [transport, setTransport] = useState("On Foot");
  const [plate, setPlate] = useState("");
  const [colour, setColour] = useState("");
  const [passengers, setPassengers] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!visit) return;
    setTransport(visit.custom_mode_of_transport || "On Foot");
    setPlate(visit.custom_vehicles_number_plate || "");
    setColour("");
    setPassengers(visit.custom_number_of_passengers ? String(visit.custom_number_of_passengers) : "");
  }, [visit]);
  useEffect(() => setGate(gates[0] ?? ""), [gates]);

  const driving = transport === "Vehicle" || transport === "Motorcycle" || transport === "Taxi";
  const problems: string[] = [];
  if (driving && !plate.trim()) problems.push("Enter the number plate.");
  if (passengers && !(Number(passengers) >= 0)) problems.push("Passengers must be a number.");

  const save = async () => {
    if (!visit || problems.length) return;
    setBusy(true);
    const r = await checkIn({
      name: visit.name,
      entry_gate: gate || undefined,
      transport,
      plate: driving ? plate.trim() : "",
      colour: driving ? colour.trim() : "",
      passengers: passengers ? Number(passengers) : undefined,
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${who(visit)} checked in.`, "ok", { hint: gate ? `at ${gate}` : undefined });
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Check in {visit ? who(visit) : ""}</DialogTitle>
          <DialogDescription>
            {visit?.custom_meet_with_name ? `Visiting ${visit.custom_meet_with_name}` : "Record the visitor's arrival at the gate."}
            {visit?.custom_farmunit ? ` · ${visit.custom_farmunit}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          {gates.length > 1 && (
            <Field label="Entry gate" htmlFor="ci-gate">
              <Picker id="ci-gate" label="Entry gate" value={gate} onChange={setGate} options={gates} />
            </Field>
          )}
          <Field label="Transport" htmlFor="ci-transport">
            <Picker id="ci-transport" label="Transport" value={transport} onChange={setTransport} options={TRANSPORT} />
          </Field>
          {driving && (
            <>
              <Field label="Number plate" htmlFor="ci-plate">
                <Input id="ci-plate" value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} />
              </Field>
              <Field label="Colour" htmlFor="ci-colour">
                <Input id="ci-colour" value={colour} onChange={(e) => setColour(e.target.value)} />
              </Field>
              <Field label="Passengers" htmlFor="ci-pass">
                <Input id="ci-pass" type="number" min={0} value={passengers} onChange={(e) => setPassengers(e.target.value)} />
              </Field>
            </>
          )}
        </div>
        <Problems list={problems} />
        <Actions busy={busy} label="Check in" onCancel={onClose} onSave={save} />
      </DialogContent>
    </Dialog>
  );
}

// --- check out ---------------------------------------------------------------------

export function CheckOutDialog({ visit, onClose, onDone }: { visit: Visit | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const open = !!visit;
  const gates = useGates(visit?.custom_farmunit, open);
  const [gate, setGate] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setGate(visit?.custom_entry_gate && gates.includes(visit.custom_entry_gate) ? visit.custom_entry_gate : gates[0] ?? ""), [gates, visit]);

  const save = async () => {
    if (!visit) return;
    setBusy(true);
    const r = await checkOut({ name: visit.name, exit_gate: gate || undefined });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${who(visit)} checked out.`, "ok");
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Check out {visit ? who(visit) : ""}</DialogTitle>
          <DialogDescription>
            Closes the visit and frees their badge{visit?.custom_visitor_badge ? ` (${visit.custom_visitor_badge})` : ""}.
          </DialogDescription>
        </DialogHeader>
        {gates.length > 1 && (
          <Field label="Exit gate" htmlFor="co-gate">
            <Picker id="co-gate" label="Exit gate" value={gate} onChange={setGate} options={gates} />
          </Field>
        )}
        <Actions busy={busy} label="Check out" onCancel={onClose} onSave={save} />
      </DialogContent>
    </Dialog>
  );
}

// --- review (approve / reject / reschedule / redirect / forward) ----------------------

export function ReviewDialog({ visit, action, onClose, onDone }: {
  visit: Visit | null; action: string; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const open = !!visit && !!action;
  const [when, setWhen] = useState("");
  const [host, setHost] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    if (!open) return;
    setWhen((visit?.scheduled_time || "").replace(" ", "T").slice(0, 16));
    setHost("");
    setNote("");
    setTried(false);
  }, [open, visit]);

  const reschedule = action === "Reschedule";
  const redirect = action === "Redirect to Another Host";
  const reject = action === "Reject Visit";
  const problems: string[] = [];
  if (reschedule && !when) problems.push("Choose the new date and time.");
  if (redirect && !host) problems.push("Choose the host to redirect to.");
  if (reject && !note.trim()) problems.push("Say why the visit is rejected.");

  const save = async () => {
    setTried(true);
    if (!visit || problems.length) return;
    setBusy(true);
    const r = await reviewVisit({
      name: visit.name,
      action,
      scheduled_time: reschedule ? when.replace("T", " ") + ":00" : undefined,
      new_host: redirect ? host : undefined,
      note: note.trim() || undefined,
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${who(visit)}: ${action}.`, "ok", { hint: r.workflow_state });
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{action}</DialogTitle>
          <DialogDescription>
            {visit ? `${who(visit)}${visit.customer_organization ? `, ${visit.customer_organization}` : ""}` : ""}
            {visit?.custom_meet_with_name ? ` · host ${visit.custom_meet_with_name}` : ""}
          </DialogDescription>
        </DialogHeader>
        {reschedule && (
          <Field label="New date and time" htmlFor="rv-when">
            <Input id="rv-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          </Field>
        )}
        {redirect && (
          <Field label="New host" htmlFor="rv-host">
            <EmployeePicker id="rv-host" value={host} onChange={(id) => setHost(id)} />
          </Field>
        )}
        <Field label={reject ? "Reason" : "Note (optional)"} htmlFor="rv-note">
          <Textarea id="rv-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {tried && <Problems list={problems} />}
        <Actions busy={busy} label={action} onCancel={onClose} onSave={save} tone={reject ? "danger" : undefined} />
      </DialogContent>
    </Dialog>
  );
}

// --- walk-in -----------------------------------------------------------------------

export function WalkInDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const T = useTerms();
  const toast = useToast();
  const { scope, farmsInScope } = useScope();
  const [f, setF] = useState({
    customer_name: "", phone: "", id_number: "", organization: "", purpose: "",
    transport: "On Foot", plate: "", colour: "", passengers: "", farm: "",
  });
  const [host, setHost] = useState("");
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((cur) => ({ ...cur, [k]: e.target.value }));

  useEffect(() => {
    if (!open) return;
    setF({
      customer_name: "", phone: "", id_number: "", organization: "", purpose: "",
      transport: "On Foot", plate: "", colour: "", passengers: "", farm: scope.farm || (farmsInScope.length === 1 ? farmsInScope[0] : ""),
    });
    setHost("");
    setTried(false);
  }, [open, scope.farm, farmsInScope]);

  const driving = f.transport !== "On Foot";
  const problems: string[] = [];
  if (!f.customer_name.trim()) problems.push("Enter the visitor's name.");
  if (!f.phone.trim()) problems.push("Enter the visitor's phone number.");
  if (!host) problems.push("Choose who they are visiting.");
  if (!f.farm && farmsInScope.length > 0) problems.push(`Choose the ${T.site}.`);
  if (driving && !f.plate.trim()) problems.push("Enter the number plate.");

  const save = async () => {
    setTried(true);
    if (problems.length) return;
    setBusy(true);
    const r = await walkIn({
      customer_name: f.customer_name.trim(),
      phone: f.phone.trim(),
      host,
      id_number: f.id_number.trim() || undefined,
      organization: f.organization.trim() || undefined,
      purpose: f.purpose.trim() || undefined,
      transport: f.transport,
      plate: driving ? f.plate.trim() : undefined,
      colour: driving ? f.colour.trim() : undefined,
      passengers: driving && f.passengers ? Number(f.passengers) : undefined,
      farm: f.farm || undefined,
      company: scope.company || undefined,
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(
      r.duplicate_suppressed ? `${f.customer_name} is already checked in.` : `${f.customer_name} checked in as a walk-in.`,
      r.duplicate_suppressed ? "warn" : "ok",
      { hint: r.name },
    );
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Walk-in visitor</DialogTitle>
          <DialogDescription>Someone at the gate without a booking. They are checked in straight away.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Full name" htmlFor="wi-name"><Input id="wi-name" value={f.customer_name} onChange={set("customer_name")} /></Field>
          <Field label="Phone" htmlFor="wi-phone"><Input id="wi-phone" inputMode="tel" value={f.phone} onChange={set("phone")} /></Field>
          <Field label="ID number" htmlFor="wi-id"><Input id="wi-id" value={f.id_number} onChange={set("id_number")} /></Field>
          <Field label="Organisation" htmlFor="wi-org"><Input id="wi-org" value={f.organization} onChange={set("organization")} /></Field>
          <Field label="Visiting (host)" htmlFor="wi-host"><EmployeePicker id="wi-host" value={host} onChange={(id) => setHost(id)} /></Field>
          {farmsInScope.length > 0 && (
            <Field label={T.Site} htmlFor="wi-farm">
              <Picker id="wi-farm" label={T.Site} value={f.farm} onChange={(v) => setF((c) => ({ ...c, farm: v }))} options={farmsInScope} placeholder={`Choose a ${T.site}`} />
            </Field>
          )}
          <Field label="Purpose" htmlFor="wi-purpose"><Input id="wi-purpose" value={f.purpose} onChange={set("purpose")} /></Field>
          <Field label="Transport" htmlFor="wi-transport">
            <Picker id="wi-transport" label="Transport" value={f.transport} onChange={(v) => setF((c) => ({ ...c, transport: v }))} options={TRANSPORT} />
          </Field>
          {driving && (
            <>
              <Field label="Number plate" htmlFor="wi-plate">
                <Input id="wi-plate" value={f.plate} onChange={(e) => setF((c) => ({ ...c, plate: e.target.value.toUpperCase() }))} />
              </Field>
              <Field label="Colour" htmlFor="wi-colour"><Input id="wi-colour" value={f.colour} onChange={set("colour")} /></Field>
              <Field label="Passengers" htmlFor="wi-pass"><Input id="wi-pass" type="number" min={0} value={f.passengers} onChange={set("passengers")} /></Field>
            </>
          )}
        </div>
        {tried && <Problems list={problems} />}
        <Actions busy={busy} label="Check in walk-in" onCancel={onClose} onSave={save} />
      </DialogContent>
    </Dialog>
  );
}
