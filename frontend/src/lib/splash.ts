/**
 * The cover that holds the screen while the app gets on its feet.
 *
 * Frappe shows one on every desk navigation; crossing between the desk and
 * this app is a full document load in both directions, and without a cover
 * that crossing is a flash of half-painted page. The markup and the styling
 * live in `www/security-dashboard-v2.html` so the cover is on screen in the first
 * frame, before this bundle — or its stylesheet — has loaded. This module only
 * decides when it comes down.
 *
 * Coming IN is the only direction that needs one. Leaving for the desk raises
 * Frappe's own splash the moment /app starts loading, and two covers handing
 * over to each other is one more than the crossing needs.
 *
 * WHEN IT COMES DOWN. Three conditions, in order:
 *
 *  1. React has painted. Uncovering a root React has been handed but not yet
 *     drawn shows the blank frame the cover exists to hide.
 *  2. MIN_MS has passed: long enough not to flicker, short enough not to be
 *     a wait.
 *  3. The first data has landed. Every endpoint goes through `call` in
 *     lib/frappe, so the count of requests in flight is known here without a
 *     single page having to say anything; the cover waits for that count to
 *     reach zero rather than handing over a screen of empty figures.
 *
 * And a cap, because condition 3 is a promise this module cannot keep on its
 * own: an endpoint that hangs would otherwise trap the operator behind a logo
 * with no way past it. At the cap the cover comes down regardless and the page
 * shows whatever state it is in — which is at worst the same empty screen,
 * with the controls to do something about it.
 */

const ID = "sec-splash";
const FADE_MS = 280;
/** The floor: just long enough that the cover does not flicker on a fast
 *  load. Production holds a full 4 s pass of its loader; for a gate dashboard
 *  that is opened all day that was a wait people noticed, so the cover now
 *  comes down as soon as the first data is in. */
const MIN_MS = 600;
/** The ceiling, when a request never comes back. */
const CAP_MS = 2500;

const openedAt =
  typeof performance !== "undefined" ? performance.now() : Date.now();

let painted = false;
let inFlight = 0;
let dismissed = false;
let timer: number | undefined;

function since(): number {
  const now = typeof performance !== "undefined" ? performance.now() : Date.now();
  return now - openedAt;
}

function hide(): void {
  if (dismissed) return;
  dismissed = true;
  const el = document.getElementById(ID);
  if (!el) return;
  el.classList.add("sec-leaving");
  window.setTimeout(() => el.remove(), FADE_MS + 40);
}

/** Re-evaluate the three conditions, and schedule the next look if it is not
 *  time yet. */
function settle(): void {
  if (dismissed || !painted) return;
  window.clearTimeout(timer);

  const waited = since();
  if (waited < MIN_MS) {
    timer = window.setTimeout(settle, MIN_MS - waited);
    return;
  }
  if (inFlight > 0 && waited < CAP_MS) {
    // Nothing to do: the request that finishes will call back in here. The
    // timer is only the backstop for one that never does.
    timer = window.setTimeout(settle, CAP_MS - waited);
    return;
  }
  hide();
}

/** Called once React has actually drawn something. */
export function markPainted(): void {
  painted = true;
  settle();
}

/** Bracketing for lib/frappe's `call`, so the cover knows what is outstanding. */
export function requestStarted(): void {
  inFlight += 1;
}

export function requestFinished(): void {
  inFlight = Math.max(0, inFlight - 1);
  settle();
}
