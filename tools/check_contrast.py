#!/usr/bin/env python3
"""Checks the app's colour tokens against WCAG 2.1 contrast minimums.

Not wired into CI — this is a design-review tool you run on demand
(`python3 tools/check_contrast.py`) whenever colours change. It reads the
:root token values straight out of index.html's <style> block (both the
light defaults and the prefers-color-scheme:dark overrides), so it can't
drift out of sync with what's actually shipped the way a hardcoded palette
copy would.

Checks a fixed list of (text token, background token) pairs that actually
occur together in the app's CSS/markup — not every combinatorial pair,
which would flag tokens that are never actually placed on each other.

WCAG 2.1 AA: 4.5:1 for normal text, 3:1 for large text (>=18pt, or >=14pt
bold) and for UI component / graphical-object boundaries.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"

# (text_token, bg_token, min_ratio, human label, which theme(s) it applies to)
PAIRS = [
    ("--ink", "--surface", 4.5, "body text on card"),
    ("--ink", "--surface-2", 4.5, "body text on page background"),
    ("--ink-2", "--surface", 4.5, "secondary text on card"),
    ("--muted", "--surface", 4.5, "muted/hint text on card"),
    ("--muted", "--surface-2", 4.5, "muted/hint text on page background"),
    ("--gain", "--surface", 3.0, "gain number (TW convention: red) on card"),
    ("--loss", "--surface", 3.0, "loss number (TW convention: green) on card"),
    ("--jade", "--surface", 3.0, "generic safe/good status on card"),
    ("--alarm", "--surface", 3.0, "generic warning/urgent status on card"),
    ("--caution", "--surface", 3.0, "caution number on card"),
    ("--violet", "--surface", 3.0, "violet accent on card"),
    ("--jade", "--jade-soft", 3.0, "big result number on jade-soft panel"),
    ("--jade-ink", "--jade-soft", 4.5, "result caption text on jade-soft panel"),
    ("--alarm", "--alarm-soft", 3.0, "alarm number on alarm-soft panel"),
    ("--caution", "--caution-soft", 3.0, "caution number on caution-soft panel"),
    ("--violet", "--violet-soft", 3.0, "violet number on violet-soft panel"),
    ("--on-ink", "--ink", 4.5, "active segment-button label on --ink fill"),
    ("--muted", "--surface", 3.0, "table header text (small, not body copy)"),
]


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_to_rgb(hex_a))
    lb = relative_luminance(hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def parse_hex_tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6})\s*;", block))


def parse_var_aliases(block: str) -> list[tuple[str, str]]:
    """(--token, --referenced-token) pairs, e.g. --gain:var(--alarm);"""
    return re.findall(r"(--[\w-]+)\s*:\s*var\((--[\w-]+)\)\s*;", block)


def extract_light_tokens(css: str) -> dict[str, str]:
    m = re.search(r":root\{(.*?)\}", css, re.DOTALL)
    if not m:
        raise SystemExit("Could not find :root{...} block in index.html")
    return parse_hex_tokens(m.group(1))


def extract_dark_tokens(css: str) -> dict[str, str]:
    m = re.search(
        r"@media\(prefers-color-scheme:dark\)\{\s*:root\{(.*?)\}\s*\}", css, re.DOTALL
    )
    if not m:
        raise SystemExit("Could not find the dark-mode :root override block")
    return parse_hex_tokens(m.group(1))


def run_theme(
    name: str, tokens: dict[str, str], light_tokens: dict[str, str], var_aliases: list[tuple[str, str]]
) -> bool:
    # Dark override is a partial set — anything it doesn't redefine still
    # comes from the light :root, since CSS custom properties cascade.
    merged = {**light_tokens, **tokens}
    # Aliases (--gain:var(--alarm);) resolve against the *merged* set, same
    # as real CSS custom-property resolution: --gain isn't redefined in the
    # dark block, but it tracks --alarm's dark value anyway because var()
    # resolves live against whatever --alarm currently is in that cascade.
    for var_name, ref in var_aliases:
        if ref in merged:
            merged[var_name] = merged[ref]
    print(f"\n=== {name} ===")
    all_pass = True
    for fg, bg, min_ratio, label in PAIRS:
        if fg not in merged or bg not in merged:
            print(f"  SKIP  {label}: {fg} or {bg} not defined in this theme")
            continue
        ratio = contrast_ratio(merged[fg], merged[bg])
        ok = ratio >= min_ratio
        all_pass &= ok
        status = "PASS" if ok else "FAIL"
        print(
            f"  {status}  {ratio:5.2f}:1 (need {min_ratio}:1)  {label}  "
            f"[{fg}={merged[fg]} on {bg}={merged[bg]}]"
        )
    return all_pass


def main() -> int:
    css = INDEX_HTML.read_text(encoding="utf-8")
    light = extract_light_tokens(css)
    dark = extract_dark_tokens(css)
    # Aliases are declared once in :root (e.g. --gain:var(--alarm);) and
    # never redeclared in the dark block, so scan the whole style block.
    var_aliases = parse_var_aliases(css)

    ok_light = run_theme("light (default)", {}, light, var_aliases)
    ok_dark = run_theme("dark (prefers-color-scheme)", dark, light, var_aliases)

    print()
    if ok_light and ok_dark:
        print("All checked pairs meet their WCAG 2.1 AA minimum.")
        return 0
    print("One or more pairs fail WCAG 2.1 AA — see FAIL lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
