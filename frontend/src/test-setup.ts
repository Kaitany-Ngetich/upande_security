/**
 * What jsdom does not implement and Radix needs.
 *
 * `Select`, `Dialog` and the rest are built on pointer capture and on scrolling
 * an option into view. jsdom has neither, so a component that works in every
 * browser throws "target.hasPointerCapture is not a function" the moment a test
 * opens a dropdown. These are the three standard shims, not a workaround for
 * anything this app does: the alternative is to stop testing the pickers, which
 * is how a farm ends up with a dropdown nobody can open.
 */
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
