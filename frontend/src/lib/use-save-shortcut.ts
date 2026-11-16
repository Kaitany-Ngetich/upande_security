import { useEffect, useRef } from "react";

/**
 * Ctrl+S — and ⌘S — do what the page's save button does.
 *
 * The desk has trained everyone on this farm to press it, and a page that
 * answered with the browser's "Save page as…" dialog is a page that taught them
 * their work was not saved. So the default is prevented whether or not this
 * page has anything to save; swallowing the shortcut and doing nothing is the
 * lesser of the two surprises, and doing nothing is still what happens when the
 * button would have been disabled.
 *
 * THE ACTION IS THE PAGE'S OWN. There is no global "save" on this app — the
 * culling board posts a cull, the movement page moves a batch, the ration
 * editor supersedes a recipe — so each page hands in the one thing its primary
 * button does, and `enabled` is the same condition that button is disabled by.
 * A shortcut that could do something the button would refuse is a way to get
 * around a guard by keyboard.
 *
 * The handler is kept in a ref so a page can pass a fresh closure on every
 * render — which every page does, since the action closes over its form state —
 * without re-binding a document listener thirty times a second.
 */
export function useSaveShortcut(action: () => void, enabled = true) {
	const latest = useRef(action);
	latest.current = action;
	const on = useRef(enabled);
	on.current = enabled;

	useEffect(() => {
		function handle(e: KeyboardEvent) {
			if (e.key !== "s" && e.key !== "S") return;
			if (!e.ctrlKey && !e.metaKey) return;
			if (e.altKey) return;
			// Always swallowed: see above. The browser's save dialog over a farm
			// record is worse than a keystroke that quietly did nothing.
			e.preventDefault();
			if (on.current) latest.current();
		}
		// Capture, because the app runs inside a Frappe page that binds its own
		// shortcuts, and the desk's handler would otherwise see it first.
		document.addEventListener("keydown", handle, { capture: true });
		return () => document.removeEventListener("keydown", handle, { capture: true });
	}, []);
}
