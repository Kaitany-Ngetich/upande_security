/**
 * Server messages may carry markup (Frappe's `frappe.throw` takes HTML). Turn
 * block tags into line breaks and drop the rest; never render it as HTML.
 */
const BLOCK_BREAK = /<\/?(br|p|div|li|h[1-6])[^>]*>/gi;
const ANY_TAG = /<[^>]+>/g;

export function plainText(value: string): string {
  if (!value.includes("<")) return value;
  return value
    .replace(BLOCK_BREAK, "\n")
    .replace(ANY_TAG, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
