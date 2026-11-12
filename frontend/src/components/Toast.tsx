import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { plainText } from "@/lib/plain-text";
import { cn } from "@/lib/utils";

/**
 * What just happened, said without moving the page.
 *
 * An inline notice pushed every card down the moment a button answered, so the
 * thing you had just clicked jumped out from under the pointer — and on a
 * screen you had scrolled, the answer appeared somewhere you were not looking.
 * These float instead.
 *
 * ONLY WHAT JUST HAPPENED. A toast is gone in a few seconds, so it is the wrong
 * home for anything you might need to read twice: a page that failed to load, a
 * recipe whose ingredients do not add up, the case for culling a cow. Those
 * stay inline, where they are still there when you look back. The rule is the
 * lifetime of the fact, not how it is worded.
 *
 * Hand-rolled, like the charts: this is a hundred lines against a dependency,
 * on a page a farm loads over a rural connection.
 *
 * AN ERROR DOES NOT TIME OUT. The farm's refusals carry instructions — which
 * items are short, the earliest date that would work — and a message somebody
 * has to act on must not vanish while they are reading it.
 */

export type ToastTone = "ok" | "warn" | "error" | "info";
/** SCP spells the error tone "err"; both are accepted. */
export type ToastKindInput = ToastTone | "err";

export interface ToastOpts {
  /** What to do about it; sits under the statement, quieter. */
  hint?: string;
  /** Lifetime override in ms (0 = until dismissed). Errors never time out. */
  ms?: number;
}

/** `toast(text, tone?, opts?)`, plus `toast.show` / `toast.dismiss` (SCP shape). */
export interface ToastApi {
  (text: string, tone?: ToastKindInput, opts?: ToastOpts): number;
  show: (text: string, tone?: ToastKindInput, opts?: ToastOpts) => number;
  dismiss: (id: number) => void;
}

interface Toast {
  id: number;
  tone: ToastTone;
  text: string;
  hint?: string;
}

const LIFETIME: Record<ToastTone, number> = { ok: 5000, info: 7000, warn: 9000, error: 0 };

/**
 * How each tone is coloured, and what is NOT coloured: the words.
 *
 * This is Frappe's desk alert, so that a message from this app and a message
 * from the desk are recognisably the same object to somebody who uses both all
 * day. The panel is filled with a wash of the tone and the icon carries the
 * colour; the words stay in ink at full contrast, because asking a herdsman to
 * READ in red is the one thing red is worst for.
 *
 * WHAT WENT: the 3px coloured bar down the left edge. It was the loudest thing
 * on the screen and it said "error" twice — once in the icon and once in a
 * stripe the eye reaches before the sentence. Frappe leaves the edge alone and
 * so does this.
 */
const TONES: Record<ToastTone, { accent: string; wash: string }> = {
  error: { accent: "var(--sd-sev-critical)", wash: "var(--sd-alert-error)" },
  // Amber: something worth knowing that is not a refusal.
  warn: { accent: "var(--sd-sev-high)", wash: "var(--sd-alert-warn)" },
  // Green — it worked, which is what was expected.
  ok: { accent: "var(--sd-sev-moderate)", wash: "var(--sd-alert-ok)" },
  // Neutral: a statement of fact wearing no colour of its own.
  info: { accent: "var(--sd-quiet)", wash: "var(--sd-alert-info)" },
};

const NOOP = Object.assign(() => 0, { show: () => 0, dismiss: () => {} }) as ToastApi;
const ToastContext = createContext<ToastApi>(NOOP);

/** Say something, from anywhere. */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const show = useCallback(
    (text: string, kind: ToastKindInput = "ok", opts?: ToastOpts) => {
      const body = plainText(String(text));
      if (!body.trim()) return 0;
      const tone: ToastTone = kind === "err" ? "error" : kind;
      const id = next.current++;
      // Three at once is a stack nobody reads; the oldest goes.
      setToasts((all) => [...all.slice(-2), { id, tone, text: body, hint: opts?.hint }]);
      const ms = tone === "error" ? 0 : (opts?.ms ?? LIFETIME[tone]);
      if (ms) timers.current.set(id, setTimeout(() => dismiss(id), ms));
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const running = timers.current;
    return () => running.forEach(clearTimeout);
  }, []);

  const value = useMemo<ToastApi>(() => Object.assign((...a: Parameters<typeof show>) => show(...a), { show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        // Bottom right on a desktop, across the bottom on a phone — where a
        // thumb already is, and clear of the header dock.
        className="pointer-events-none fixed inset-x-3 bottom-3 z-[60] flex flex-col items-stretch gap-2 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:w-[min(24rem,calc(100vw-2.5rem))]"
      >
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon =
    toast.tone === "error" || toast.tone === "warn"
      ? AlertTriangle
      : toast.tone === "ok"
        ? CheckCircle2
        : Info;
  const tone = TONES[toast.tone];
  return (
    <div
      // `alert` is announced at once and interrupts; `status` waits for a pause.
      // A refusal the operator has to act on earns the interruption, a
      // confirmation does not.
      role={toast.tone === "error" ? "alert" : "status"}
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-[var(--sd-radius-toast)] px-4 py-3.5",
        "text-[13px] leading-relaxed whitespace-pre-line shadow-[var(--sd-shadow-3)]",
        "animate-in slide-in-from-bottom-2 fade-in duration-200",
        // The words are ink whatever the tone. Colour marks the message; it
        // does not set it. Medium weight, as the desk alert sets it.
        "font-medium text-[var(--sd-ink)]",
      )}
      style={{ background: tone.wash }}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color: tone.accent }} />
      <div className="min-w-0 flex-1">
        <p>{toast.text}</p>
        {toast.hint && <p className="mt-0.5 text-xs font-normal text-[var(--sd-quiet)]">{toast.hint}</p>}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="-mr-1 shrink-0 text-[var(--sd-quiet)] transition-colors hover:text-[var(--sd-ink)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
