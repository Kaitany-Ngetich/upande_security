"""Generate the Security mark's SVGs.

    python3 scripts/build_security_logo.py

Same pattern as upande_production (scripts/build_production_logo.py). At rest the mark
IS the Upande mark (white disc with its thin rim, the arrow where upande_logo.png has it
on a 689 canvas). On hover the arrow shrinks into the centre and the security round plays:

1. Gate check - a staff badge is scanned, ticked green, and the boom barrier lifts.
2. Patrol     - the guard's route draws itself and each checkpoint lights as it is reached.
3. Secured    - a shield lands, a check draws inside it and a ring pulses out.

It loops while the pointer stays and eases back out on leave. Keyframes are written once
and emitted both as CSS (security_logo_loader.svg, a standalone looping preview/splash)
and as JSON in <metadata> (read by public/js/security_logo_motion.js on the desk).
"""

from __future__ import annotations

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP / "upande_security" / "public" / "images"
FRONTEND_ASSETS = APP / "frontend" / "src" / "assets"

# -- palette ------------------------------------------------------------------

INK = "#45433f"
ACCENT = "#3f7d3a"   # cleared / secure
ALERT = "#b23a2e"    # the boom barrier
PALE = "#d6d1c8"
MID = "#a9a49b"

SHOW = {"transform": "scale(1)", "opacity": 1}
HIDE = {"transform": "scale(.86)", "opacity": 0}
STAGE_ORIGIN = "view-box|344px 380px"

# -- artwork (689 x 689, the PNG's own canvas) --------------------------------

ARROW = """<g class="arrow">
    <g transform="translate(169 165)">
      <path fill="#625d59" d="M0 0 H272 V85 H0 Z"/>
      <path fill="#45433f" d="M272 0 H359 V364 H272 Z"/>
      <path fill="#1a1917" d="M246 85 H272 V161 L246 187 Z"/>
      <path fill="#45433f" d="M198 85 H246 V187 L69 364 H0 V283 Z"/>
    </g>
  </g>"""

# 1. gate check: badge (top right) with a scan bar, then the boom lifts --------
PIVOT = (186, 400)
BOOM_LEN = 340
STRIPES = "".join(
    f'<rect x="{PIVOT[0] + 30 + i * 64}" y="{PIVOT[1] - 12}" width="30" height="24" fill="#ffffff"/>'
    for i in range(5)
)

GATE = f"""<g class="gate">
    <g class="badge">
      <rect class="card" x="360" y="200" width="170" height="110" rx="12" fill="{PALE}"/>
      <rect x="376" y="218" width="46" height="56" rx="6" fill="{MID}"/>
      <circle cx="399" cy="236" r="11" fill="#ffffff"/>
      <path d="M383 268 Q399 248 415 268 Z" fill="#ffffff"/>
      <rect x="436" y="224" width="76" height="13" rx="3" fill="{INK}"/>
      <rect x="436" y="246" width="60" height="11" rx="3" fill="{MID}"/>
      <rect x="436" y="266" width="66" height="11" rx="3" fill="{MID}"/>
      <rect x="376" y="288" width="136" height="8" rx="3" fill="{MID}"/>
      <rect class="scan" x="352" y="198" width="186" height="8" rx="4" fill="{ACCENT}"/>
    </g>
    <g class="ok">
      <circle cx="526" cy="206" r="26" fill="{ACCENT}"/>
      <path d="M513 207 L522 216 L540 196" fill="none" stroke="#ffffff" stroke-width="7"
            stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <rect x="{PIVOT[0] + BOOM_LEN - 32}" y="{PIVOT[1] + 12}" width="14" height="136" fill="{MID}"/>
    <rect x="168" y="372" width="36" height="176" rx="4" fill="{INK}"/>
    <rect x="146" y="540" width="80" height="14" rx="3" fill="{INK}"/>
    <g class="boom">
      <rect x="{PIVOT[0]}" y="{PIVOT[1] - 12}" width="{BOOM_LEN}" height="24" rx="5" fill="{ALERT}"/>
      {STRIPES}
    </g>
    <circle cx="{PIVOT[0]}" cy="{PIVOT[1]}" r="20" fill="{INK}"/>
    <circle cx="{PIVOT[0]}" cy="{PIVOT[1]}" r="7" fill="{PALE}"/>
  </g>"""

# 2. patrol: a route through four checkpoints -----------------------------------
CP = [(196, 452), (290, 290), (432, 340), (492, 492)]
ROUTE_D = "M" + " L".join(f"{x} {y}" for x, y in CP)
_seg = [((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(CP, CP[1:])]
_total = sum(_seg)
CP_AT = [0.0] + [sum(_seg[: i + 1]) / _total for i in range(len(_seg))]   # 0 .. 1 along the route
DRAW_LO, DRAW_HI = 0.40, 0.62


def checkpoint(i: int) -> str:
    x, y = CP[i]
    return (f'<circle class="cp cp{i}" cx="{x}" cy="{y}" r="28" fill="{PALE}"/>'
            f'<circle cx="{x}" cy="{y}" r="10" fill="#ffffff"/>')


PATROL = f"""<g class="patrol">
    <path d="{ROUTE_D}" fill="none" stroke="{PALE}" stroke-width="12" stroke-dasharray="4 22"
          stroke-linecap="round" stroke-linejoin="round"/>
    <path class="route" d="{ROUTE_D}" fill="none" stroke="{INK}" stroke-width="12"
          stroke-linejoin="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    {"".join(checkpoint(i) for i in range(len(CP)))}
  </g>"""

# 3. secured: shield with a check, and a pulse ring --------------------------------
SHIELD_D = ("M344 222 L476 272 V378 C476 462 414 516 344 548 "
            "C274 516 212 462 212 378 V272 Z")

SHIELD = f"""<g class="secured">
    <circle class="pulse" cx="344" cy="384" r="176" fill="none" stroke="{ACCENT}" stroke-width="10"/>
    <path d="{SHIELD_D}" fill="{INK}"/>
    <path d="M344 254 L448 294 V378 C448 446 400 490 344 516 Z" fill="#625d59"/>
    <path class="check" d="M286 388 L330 432 L408 344" fill="none" stroke="#ffffff" stroke-width="26"
          stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
  </g>"""

SCENE = f"""{GATE}
  {PATROL}
  {SHIELD}"""


def body(rest_hidden: bool) -> str:
    hide = ' opacity="0"' if rest_hidden else ""
    return f"""  <clipPath id="security-disc"><circle cx="344.5" cy="344.5" r="336"/></clipPath>
  <!-- the white disc of upande_logo.png, with its thin dark rim -->
  <circle cx="344.5" cy="344.5" r="340" fill="#ffffff" stroke="#1c1b19" stroke-opacity=".3" stroke-width="7"/>
  <g clip-path="url(#security-disc)">
  <g class="scene"{hide}>
  {SCENE}
  </g>
  </g>
  {ARROW}
"""


# -- motion --------------------------------------------------------------------
# Each entry: selector, transform-origin ("box|x y", bare = view-box px), keyframes [offset, props].

ARROW_HOME = "translate(0px, 0px) scale(1)"
ARROW_GONE = "translate(0px, 0px) scale(0)"

ENTER = [
    (".arrow", "348.5px 347px", [
        (0, {"transform": ARROW_HOME, "opacity": 1}),
        (0.45, {"transform": ARROW_GONE, "opacity": 0}),
        (1, {"transform": ARROW_GONE, "opacity": 0}),
    ]),
    (".scene", None, [
        (0, {"opacity": 0}),
        (0.2, {"opacity": 1}),
        (1, {"opacity": 1}),
    ]),
]


def _dash(lo, hi, reset):
    return [(0, {"strokeDashoffset": 1}), (lo, {"strokeDashoffset": 1}), (hi, {"strokeDashoffset": 0}),
            (reset, {"strokeDashoffset": 0}), (reset + 0.01, {"strokeDashoffset": 1}), (1, {"strokeDashoffset": 1})]


def _fill(at, off, on, reset):
    return [(0, {"fill": off}), (at, {"fill": off}), (min(at + 0.02, reset), {"fill": on}),
            (reset, {"fill": on}), (reset + 0.01, {"fill": off}), (1, {"fill": off})]


LOOP = [
    # 1. gate check (0 - .36)
    (".gate", STAGE_ORIGIN, [
        (0, {"transform": "scale(.96)", "opacity": 0}),
        (0.03, SHOW), (0.33, SHOW), (0.38, HIDE), (1, HIDE),
    ]),
    (".scan", None, [
        (0, {"transform": "translateY(0px)", "opacity": 0}),
        (0.04, {"transform": "translateY(0px)", "opacity": 1}),
        (0.13, {"transform": "translateY(104px)", "opacity": 1}),
        (0.15, {"transform": "translateY(104px)", "opacity": 0}),
        (1, {"transform": "translateY(0px)", "opacity": 0}),
    ]),
    (".card", None, _fill(0.14, PALE, "#cfe0cb", 0.36)),
    (".ok", "view-box|526px 206px", [
        (0, {"transform": "scale(0)", "opacity": 0}), (0.15, {"transform": "scale(0)", "opacity": 0}),
        (0.19, {"transform": "scale(1)", "opacity": 1}), (0.36, {"transform": "scale(1)", "opacity": 1}),
        (0.37, {"transform": "scale(0)", "opacity": 0}), (1, {"transform": "scale(0)", "opacity": 0}),
    ]),
    (".boom", f"view-box|{PIVOT[0]}px {PIVOT[1]}px", [
        (0, {"transform": "rotate(0deg)"}), (0.20, {"transform": "rotate(0deg)"}),
        (0.29, {"transform": "rotate(-80deg)"}), (0.36, {"transform": "rotate(-80deg)"}),
        (0.37, {"transform": "rotate(0deg)"}), (1, {"transform": "rotate(0deg)"}),
    ]),
    # 2. patrol (.36 - .70): the route draws, checkpoints light as it reaches them
    (".patrol", STAGE_ORIGIN, [
        (0, HIDE), (0.36, HIDE), (0.40, SHOW), (0.68, SHOW), (0.73, HIDE), (1, HIDE),
    ]),
    (".route", None, _dash(DRAW_LO, DRAW_HI, 0.72)),
    *[
        (f".cp{i}", None, _fill(round(DRAW_LO + (DRAW_HI - DRAW_LO) * f, 3), PALE, ACCENT, 0.72))
        for i, f in enumerate(CP_AT)
    ],
    # 3. secured (.72 - .97)
    (".secured", STAGE_ORIGIN, [
        (0, HIDE), (0.71, HIDE), (0.76, SHOW), (0.93, SHOW), (0.98, HIDE), (1, HIDE),
    ]),
    (".check", None, _dash(0.77, 0.84, 0.97)),
    (".pulse", "view-box|344px 384px", [
        (0, {"transform": "scale(.7)", "opacity": 0}), (0.83, {"transform": "scale(.7)", "opacity": 0}),
        (0.85, {"transform": "scale(.8)", "opacity": 1}), (0.95, {"transform": "scale(1.15)", "opacity": 0}),
        (1, {"transform": "scale(1.15)", "opacity": 0}),
    ]),
]

LOOP_MS = 5600

# One splash pass: enter 0-18 %, the round 18-82 %, back out 82-100 %.
CYCLE_MS = 5000
ENTER_PCT, EXIT_PCT = 14.0, 86.0
ENTER_MS = 720
EASE = "cubic-bezier(.3,.7,.2,1)"


# -- emit ---------------------------------------------------------------------

def _css_props(props: dict) -> str:
    names = {"strokeDashoffset": "stroke-dashoffset", "strokeWidth": "stroke-width"}
    return "; ".join(f"{names.get(k, k)}: {v}" for k, v in props.items())


def _origin(origin: str) -> tuple[str, str]:
    box, _, at = origin.rpartition("|")
    return (box or "view-box", at)


def loader_css() -> str:
    a, b = ENTER_PCT, EXIT_PCT
    lines = ["  <style>"]
    for sel, origin, _ in ENTER + LOOP:
        if origin:
            box, at = _origin(origin)
            lines.append(f"    {sel} {{ transform-box: {box}; transform-origin: {at}; }}")
    keyframes = []
    for i, (sel, _o, frames) in enumerate(ENTER):
        steps = {}
        for off, props in frames:
            steps[round(off * a, 2)] = props
            steps[round(100 - off * (100 - b), 2)] = props
        keyframes.append((sel, f"security-in-{i}", sorted(steps.items())))
    for i, (sel, _o, frames) in enumerate(LOOP):
        first = frames[0][1]
        steps = {0.0: first}
        for off, props in frames:
            steps[round(a + off * (b - a), 2)] = props
        steps[100.0] = first
        keyframes.append((sel, f"security-round-{i}", sorted(steps.items())))
    for sel, name, _ in keyframes:
        lines.append(f"    {sel} {{ animation: {name} {CYCLE_MS}ms linear infinite both; }}")
    for _sel, name, steps in keyframes:
        lines.append(f"    @keyframes {name} {{")
        for pct, props in steps:
            lines.append(f"      {pct:g}% {{ {_css_props(props)}; }}")
        lines.append("    }")
    lines += [
        "    @media (prefers-reduced-motion: reduce) {",
        "      .arrow, .scene, .scene * { animation: none !important; }",
        "      .scene { opacity: 0; }",
        "    }",
        "  </style>",
    ]
    return "\n".join(lines)


def motion_json() -> str:
    def tracks(t):
        return [
            {
                "sel": sel,
                "box": _origin(origin)[0] if origin else None,
                "origin": _origin(origin)[1] if origin else None,
                "frames": [dict(offset=o, **p) for o, p in frames],
            }
            for sel, origin, frames in t
        ]

    return json.dumps(
        {"enterMs": ENTER_MS, "loopMs": LOOP_MS, "ease": EASE, "enter": tracks(ENTER), "loop": tracks(LOOP)},
        separators=(",", ":"),
    )


HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 689 689" width="689" height="689" role="img" aria-label="{label}">'


def check(tracks) -> None:
    """Browsers reject keyframes whose offsets go backwards."""
    for sel, _origin_, frames in tracks:
        offs = [o for o, _ in frames]
        if any(o < 0 or o > 1 for o in offs) or any(y < x for x, y in zip(offs, offs[1:])):
            raise SystemExit(f"{sel} offsets out of order: {offs}")


def main():
    check(ENTER + LOOP)
    ROOT.mkdir(parents=True, exist_ok=True)
    desk = "\n".join([
        HEAD.format(label="Security"),
        "  <!-- Generated by scripts/build_security_logo.py — edit there.",
        "       At rest this is the Upande mark; the security round plays on hover. -->",
        f'  <metadata id="security-motion">{motion_json()}</metadata>',
        body(rest_hidden=True) + "</svg>",
        "",
    ])
    (ROOT / "security_logo.svg").write_text(desk)
    FRONTEND_ASSETS.mkdir(parents=True, exist_ok=True)
    (FRONTEND_ASSETS / "security_logo.svg").write_text(desk)
    loader = "\n".join([
        HEAD.format(label="Upande Security"),
        "  <!-- Generated by scripts/build_security_logo.py — edit there.",
        "       Looping preview / splash: in, the security round, out. Pure CSS. -->",
        loader_css(),
        body(rest_hidden=False) + "</svg>",
        "",
    ])
    (ROOT / "security_logo_loader.svg").write_text(loader)
    print("wrote security_logo.svg, security_logo_loader.svg")


if __name__ == "__main__":
    main()
