// The Security tile on the desk's apps screen, animated on hover.
//
// At rest the tile is the plain Upande mark (security_logo.svg draws exactly
// upande_logo.png, same as Production's tile). On hover the arrow shrinks away
// and the security round plays: a staff badge is scanned and cleared, the gate
// boom lifts; a patrol route draws through its checkpoints; a shield lands and
// is checked. It loops while the pointer (or keyboard focus) stays and eases
// back to the plain mark on leave.
//
// The desk draws app tiles as <img>, and hover never reaches an SVG inside an
// <img>, so the <img> is swapped for the same file inlined and the Web
// Animations API drives it with keyframes from the file's own <metadata>
// (written by scripts/build_security_logo.py). If anything fails the <img>
// stays: the plain mark.
(function () {
	var SRC = "/assets/upande_security/images/security_logo.svg";
	var svgText = null;
	var loading = null;

	if (typeof Element === "undefined" || !Element.prototype.animate) return;
	if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

	function fetchSvg() {
		if (svgText) return Promise.resolve(svgText);
		if (!loading) {
			loading = fetch(SRC, { credentials: "same-origin" })
				.then(function (r) {
					if (!r.ok) throw new Error(r.status);
					return r.text();
				})
				.then(function (t) {
					svgText = t;
					return t;
				});
		}
		return loading;
	}

	function build(svg, tracks, timing) {
		var out = [];
		tracks.forEach(function (t) {
			var els = svg.querySelectorAll(t.sel);
			for (var i = 0; i < els.length; i++) {
				var el = els[i];
				if (t.origin) {
					el.style.transformBox = t.box || "view-box";
					el.style.transformOrigin = t.origin;
				}
				var a = el.animate(t.frames, timing);
				a.pause();
				a.currentTime = 0;
				out.push(a);
			}
		});
		return out;
	}

	function wire(svg, tile, spec) {
		var enter = build(svg, spec.enter, {
			duration: spec.enterMs,
			easing: spec.ease,
			fill: "both",
		});
		var loop = build(svg, spec.loop, {
			duration: spec.loopMs,
			easing: "ease-in-out",
			iterations: Infinity,
			fill: "both",
		});
		var hovered = false;

		function at(anims) {
			return anims.length ? Number(anims[0].currentTime) || 0 : 0;
		}
		function run(anims, forward) {
			anims.forEach(function (a) {
				var t = Number(a.currentTime) || 0;
				// play() on a finished animation seeks to the far end; at the end it
				// is heading for already, it stays put instead of jumping.
				if (forward ? t >= spec.enterMs : t <= 0) {
					a.pause();
					return;
				}
				a.playbackRate = forward ? 1 : -1;
				a.play();
			});
		}

		enter.forEach(function (a) {
			a.onfinish = function () {
				// Fully in and still hovered: start the scouting round.
				if (hovered && a === enter[0] && at(enter) >= spec.enterMs) {
					loop.forEach(function (l) {
						l.play();
					});
				}
			};
		});

		function on() {
			hovered = true;
			// A round only ever starts from its beginning (badge unscanned, boom down).
			if (at(enter) <= 0) {
				loop.forEach(function (l) {
					l.pause();
					l.currentTime = 0;
				});
			}
			run(enter, true);
		}
		function off() {
			hovered = false;
			// The round holds where it is; the scene fades out around it as the
			// enter timeline reverses, and the next hover starts it afresh.
			loop.forEach(function (l) {
				l.pause();
			});
			run(enter, false);
		}
		tile.addEventListener("mouseenter", on);
		tile.addEventListener("mouseleave", off);
		tile.addEventListener("focusin", on);
		tile.addEventListener("focusout", off);
	}

	function upgrade(img) {
		if (img.dataset.securityMotion) return;
		img.dataset.securityMotion = "1";
		fetchSvg()
			.then(function (text) {
				if (!img.isConnected) return;
				var holder = document.createElement("div");
				holder.innerHTML = text;
				var svg = holder.querySelector("svg");
				var meta = svg && svg.querySelector("#security-motion");
				if (!svg || !meta) return;
				var spec = JSON.parse(meta.textContent);

				var box = img.getBoundingClientRect();
				var cs = getComputedStyle(img);
				svg.setAttribute("class", img.className || "app-icon");
				svg.setAttribute("aria-label", img.alt || "Security");
				svg.removeAttribute("width");
				svg.removeAttribute("height");
				// Exactly the <img>'s size: the same tile as before.
				svg.style.width = box.width ? box.width + "px" : cs.width;
				svg.style.height = box.height ? box.height + "px" : cs.height;
				svg.style.display = "block";
				svg.style.overflow = "visible";
				img.replaceWith(svg);

				wire(svg, svg.closest(".desktop-icon") || svg.parentElement, spec);
			})
			.catch(function () {
				// Keep the <img>: the plain mark.
			});
	}

	function scan() {
		var imgs = document.querySelectorAll('.desktop-icon img.app-icon[src*="security_logo.svg"]');
		for (var i = 0; i < imgs.length; i++) {
			// Not laid out yet (hidden page): try again on the next mutation.
			if (!imgs[i].getBoundingClientRect().width) continue;
			upgrade(imgs[i]);
		}
	}

	// The apps screen re-renders on navigation and edits; watch for tiles.
	var queued = false;
	function onMutate() {
		if (queued) return;
		queued = true;
		requestAnimationFrame(function () {
			queued = false;
			scan();
		});
	}
	function start() {
		scan();
		new MutationObserver(onMutate).observe(document.body, {
			childList: true,
			subtree: true,
			attributes: true,
			attributeFilter: ["class", "style"],
		});
	}
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
	else start();
})();
