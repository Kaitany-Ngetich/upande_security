/**
 * The one way this app talks to Frappe.
 *
 * Two things it deliberately does NOT do:
 *
 *  * It does not translate the server's words. Every production endpoint returns
 *    `{"error": "..."}` in the body rather than raising (see
 *    serverscripts/common/envelope.py: `run`), and those messages are written
 *    for a farm worker — a refused backdated feed run names each short item and
 *    the earliest date that would work. Callers surface `error` unchanged.
 *  * It does not convert units. Quantities cross this boundary in whatever unit
 *    the server named; see lib/feeding.ts.
 */

import { requestFinished, requestStarted } from "@/lib/splash";

export interface SecurityBootstrap {
  user: string;
  full_name: string;
  user_image: string;
  site_name: string;
  roles: string[];
}

declare global {
  interface Window {
    SECURITY?: {
      csrf_token?: string;
      bootstrap?: Partial<SecurityBootstrap> & Record<string, unknown>;
    };
    csrf_token?: string;
  }
}

function csrf(): string {
  return window.SECURITY?.csrf_token || window.csrf_token || "";
}

export function bootstrap(): SecurityBootstrap {
  const raw = window.SECURITY?.bootstrap || {};
  return {
    user: typeof raw.user === "string" ? raw.user : "",
    full_name: typeof raw.full_name === "string" ? raw.full_name : "",
    user_image: typeof raw.user_image === "string" ? raw.user_image : "",
    site_name: typeof raw.site_name === "string" ? raw.site_name : "",
    roles: Array.isArray(raw.roles) ? (raw.roles as string[]) : [],
  };
}

/** Anything an endpoint may answer with. `error` is the refusal channel. */
export type Envelope<T> = (T & { ok?: boolean; error?: string }) | { error: string };

export function isError<T>(r: Envelope<T> | null | undefined): r is { error: string } {
  return !!r && typeof (r as { error?: unknown }).error === "string" && !!(r as { error: string }).error;
}

/** The first message frappe.throw queued, as plain text, if any. */
function serverMessage(body: unknown): string {
  if (!body || typeof body !== "object" || !("_server_messages" in body)) return "";
  try {
    const list = JSON.parse(String((body as { _server_messages: unknown })._server_messages));
    const first = Array.isArray(list) && list.length ? list[0] : null;
    if (!first) return "";
    let text = String(first);
    try {
      const obj = JSON.parse(text);
      if (obj && typeof obj.message === "string") text = obj.message;
    } catch {
      /* already plain text */
    }
    const div = document.createElement("div");
    div.innerHTML = text;
    return (div.textContent || "").trim();
  } catch {
    return "";
  }
}

/**
 * POST a whitelisted method and hand back its `message`.
 *
 * A transport failure is folded into the same `{error}` shape the endpoints
 * use, so every caller has exactly one thing to check. Nothing here throws.
 */
export async function call<T>(
  method: string,
  args: Record<string, unknown> = {},
): Promise<Envelope<T>> {
  // Bracketed so the loading cover knows whether the app is still waiting on
  // anything. Every endpoint comes through here, which is why no page has to
  // say a word about it. The finally is what makes the count trustworthy: a
  // request that throws still has to decrement, or the cover waits out its
  // whole cap on a request that is already over.
  requestStarted();
  try {
    const res = await fetch(`/api/method/${method}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Frappe-CSRF-Token": csrf(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(args),
    });
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    const message =
      body && typeof body === "object" && "message" in body
        ? (body as { message: unknown }).message
        : null;
    if (message && typeof message === "object") {
      return message as Envelope<T>;
    }
    if (!res.ok) {
      // frappe.throw puts its human sentence in _server_messages; prefer it
      // over the exception line ("frappe.exceptions.ValidationError: ...").
      const said = serverMessage(body);
      if (said) return { error: said };
      // A raise that escaped the envelope (a 403 from the framework itself,
      // a stale CSRF token on a page left open overnight). Say which.
      const exc =
        body && typeof body === "object" && "exception" in body
          ? String((body as { exception: unknown }).exception)
          : "";
      if (res.status === 403 || res.status === 401) {
        return { error: exc || "Your session has expired. Reload the page and sign in again." };
      }
      return { error: exc || res.statusText || "The server refused that request." };
    }
    return { error: "No response from the server." };
  } catch {
    return { error: "Network error — the request did not reach the server." };
  } finally {
    requestFinished();
  }
}

/**
 * Link-field search, through the framework's own autosuggest endpoint.
 *
 * `frappe.desk.search.search_link` is what every desk Link field calls, and it
 * applies the same permission check: a user who may not list Warehouse gets an
 * empty list, not somebody else's warehouses. Using it here means the settings
 * page offers only records that exist — the alternative, a text box, is how a
 * feed warehouse ends up spelled two ways and a month of postings lands
 * nowhere.
 *
 * Returns `null` — not `[]` — when the call itself failed, so a picker can say
 * "could not search" instead of "no matches", which are different problems.
 */
export async function searchLink(
  doctype: string,
  term: string,
  pageLength = 20,
): Promise<Array<{ value: string; description: string; label?: string }> | null> {
  try {
    const res = await fetch("/api/method/frappe.desk.search.search_link", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Frappe-CSRF-Token": csrf(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ doctype, txt: term, page_length: pageLength }),
    });
    if (!res.ok) return null;
    const body = await res.json();
    const rows = body?.message;
    return Array.isArray(rows) ? rows : null;
  } catch {
    return null;
  }
}

/** Item-master search, through the same whitelisted read every desk Link field
 *  uses. Every livestock role already reads the item master, so this needs no
 *  endpoint of its own. */
export async function searchItems(
  term: string,
): Promise<Array<{ name: string; item_name: string; stock_uom: string }>> {
  try {
    const res = await fetch("/api/method/frappe.client.get_list", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Frappe-CSRF-Token": csrf(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({
        doctype: "Item",
        filters: [["item_name", "like", `%${term}%`]],
        fields: ["name", "item_name", "stock_uom"],
        limit_page_length: 20,
        order_by: "item_name asc",
      }),
    });
    const body = await res.json();
    return body?.message || [];
  } catch {
    return [];
  }
}

/**
 * Upload a file the way the desk does (`upload_file`, multipart) and hand back
 * its URL, or `{error}`. Public, like the calf photo: an <img> loads it with no
 * further ceremony. Attaching it to something is the caller's next call.
 */
export async function uploadFile(
  file: File,
  opts: { isPrivate?: boolean; doctype?: string; docname?: string; fieldname?: string } = {},
): Promise<{ file_url: string } | { error: string }> {
  try {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("is_private", opts.isPrivate ? "1" : "0");
    // Attached to a record, a private file is readable by whoever may read
    // that record - not only by its uploader.
    if (opts.doctype && opts.docname) {
      form.append("doctype", opts.doctype);
      form.append("docname", opts.docname);
      if (opts.fieldname) form.append("fieldname", opts.fieldname);
    }
    const res = await fetch("/api/method/upload_file", {
      method: "POST",
      credentials: "include",
      headers: { "X-Frappe-CSRF-Token": csrf(), "X-Requested-With": "XMLHttpRequest" },
      body: form,
    });
    const body = await res.json().catch(() => null);
    const url = body?.message?.file_url;
    if (typeof url === "string" && url) return { file_url: url };
    return { error: "The picture did not upload." };
  } catch {
    return { error: "Network error — the picture did not reach the server." };
  }
}
