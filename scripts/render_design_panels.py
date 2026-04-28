"""Render the HW11 design-system slides (color palette, typography,
visual hierarchy) as PNGs by laying out HTML + the Aperture design
tokens and screenshotting with Playwright.

Outputs:
    color_palette.png       — swatches with hex + role
    typography.png          — display / body / mono specimens
    visual_hierarchy.png    — annotated mock of the three reading layers

Usage:
    uv run python scripts/render_design_panels.py [--out DIR]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT.parent / "hw11" / "placeholders"
PANEL = {"width": 1600, "height": 900}


# --- Tokens, lifted from design/colors_and_type.css -------------------------

TOKENS_CSS = """
:root {
  --bg-0:#0b0b0c; --bg-1:#141416; --bg-2:#1c1c1f; --bg-3:#26262b; --bg-4:#34343a;
  --fg-0:#f4f1ea; --fg-1:#d6d2c6; --fg-2:#9a958a; --fg-3:#6b6860; --fg-4:#403e3a;
  --amber-300:#f3c67a; --amber-400:#e0a85a; --amber-500:#c08140;
  --meter-green:#7ba86f; --meter-red:#c0564a; --meter-cyan:#6faaaa;
  --font-display:'Cormorant Garamond', Georgia, serif;
  --font-body:'Inter', -apple-system, sans-serif;
  --font-mono:'JetBrains Mono', ui-monospace, monospace;
}
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500;600&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg-0); color: var(--fg-1); font-family: var(--font-body); }
body { padding: 56px 64px; }
.title { font-family: var(--font-display); font-weight: 400; font-size: 48px; color: var(--fg-0); margin: 0 0 4px; letter-spacing: -0.015em; }
.subtitle { color: var(--fg-2); font-size: 14px; letter-spacing: 0.16em; text-transform: uppercase; margin: 0 0 32px; }
"""


# --- Color palette panel ----------------------------------------------------

PALETTE_HTML = f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS_CSS}
.row {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 14px; }}
.swatch {{ border-radius: 6px; padding: 18px 16px 16px; min-height: 132px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(246,242,230,0.10); }}
.swatch .role {{ font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; }}
.swatch .name {{ font-family: var(--font-mono); font-size: 13px; }}
.swatch .hex  {{ font-family: var(--font-mono); font-size: 16px; }}
.section-h {{ font-family: var(--font-display); font-weight: 500; font-size: 22px; margin: 24px 0 12px; color: var(--fg-0); letter-spacing: -0.01em; }}
</style></head><body>
<div class='title'>Color palette</div>
<div class='subtitle'>Aperture — darkroom neutrals + safelight amber</div>

<div class='section-h'>Backgrounds (carbon, not pure black)</div>
<div class='row'>
  <div class='swatch' style='background:#0b0b0c;color:#f4f1ea'><div><div class='role'>Page</div><div class='name'>--bg-0</div></div><div class='hex'>#0B0B0C</div></div>
  <div class='swatch' style='background:#141416;color:#f4f1ea'><div><div class='role'>Panel</div><div class='name'>--bg-1</div></div><div class='hex'>#141416</div></div>
  <div class='swatch' style='background:#1c1c1f;color:#f4f1ea'><div><div class='role'>Raised</div><div class='name'>--bg-2</div></div><div class='hex'>#1C1C1F</div></div>
  <div class='swatch' style='background:#26262b;color:#f4f1ea'><div><div class='role'>Control face</div><div class='name'>--bg-3</div></div><div class='hex'>#26262B</div></div>
  <div class='swatch' style='background:#34343a;color:#f4f1ea'><div><div class='role'>Pressed</div><div class='name'>--bg-4</div></div><div class='hex'>#34343A</div></div>
</div>

<div class='section-h'>Foregrounds (light-meter scale)</div>
<div class='row'>
  <div class='swatch' style='background:#f4f1ea;color:#0b0b0c'><div><div class='role'>Display</div><div class='name'>--fg-0</div></div><div class='hex'>#F4F1EA</div></div>
  <div class='swatch' style='background:#d6d2c6;color:#0b0b0c'><div><div class='role'>Body</div><div class='name'>--fg-1</div></div><div class='hex'>#D6D2C6</div></div>
  <div class='swatch' style='background:#9a958a;color:#0b0b0c'><div><div class='role'>Secondary</div><div class='name'>--fg-2</div></div><div class='hex'>#9A958A</div></div>
  <div class='swatch' style='background:#6b6860;color:#f4f1ea'><div><div class='role'>Tertiary</div><div class='name'>--fg-3</div></div><div class='hex'>#6B6860</div></div>
  <div class='swatch' style='background:#403e3a;color:#f4f1ea'><div><div class='role'>Quaternary</div><div class='name'>--fg-4</div></div><div class='hex'>#403E3A</div></div>
</div>

<div class='section-h'>Accents (single safelight amber + meter colors)</div>
<div class='row'>
  <div class='swatch' style='background:#f3c67a;color:#0b0b0c'><div><div class='role'>Light amber</div><div class='name'>--amber-300</div></div><div class='hex'>#F3C67A</div></div>
  <div class='swatch' style='background:#e0a85a;color:#0b0b0c'><div><div class='role'>Primary accent</div><div class='name'>--amber-400</div></div><div class='hex'>#E0A85A</div></div>
  <div class='swatch' style='background:#c08140;color:#0b0b0c'><div><div class='role'>Pressed</div><div class='name'>--amber-500</div></div><div class='hex'>#C08140</div></div>
  <div class='swatch' style='background:#7ba86f;color:#0b0b0c'><div><div class='role'>Correct</div><div class='name'>--meter-green</div></div><div class='hex'>#7BA86F</div></div>
  <div class='swatch' style='background:#c0564a;color:#f4f1ea'><div><div class='role'>Wrong / warn</div><div class='name'>--meter-red</div></div><div class='hex'>#C0564A</div></div>
</div>

</body></html>"""


# --- Typography panel -------------------------------------------------------

TYPOGRAPHY_HTML = f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS_CSS}
.specimen {{ display: grid; grid-template-columns: 200px 1fr 220px; gap: 32px; align-items: baseline; padding: 18px 0; border-top: 1px solid rgba(246,242,230,0.10); }}
.specimen .role {{ color: var(--fg-2); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; }}
.specimen .meta {{ color: var(--fg-3); font-family: var(--font-mono); font-size: 12px; text-align: right; }}
.specimen.first {{ border-top: 0; }}
.sample-display {{ font-family: var(--font-display); font-weight: 500; font-size: 56px; line-height: 1.1; letter-spacing: -0.015em; color: var(--fg-0); }}
.sample-display-italic {{ font-family: var(--font-display); font-style: italic; font-weight: 400; font-size: 28px; color: var(--fg-1); }}
.sample-body-lg {{ font-family: var(--font-body); font-weight: 400; font-size: 20px; line-height: 1.6; color: var(--fg-1); max-width: 56ch; }}
.sample-body {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 1.6; color: var(--fg-1); max-width: 70ch; }}
.sample-ui {{ font-family: var(--font-body); font-weight: 500; font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-2); }}
.sample-mono {{ font-family: var(--font-mono); font-weight: 500; font-size: 18px; color: var(--amber-400); letter-spacing: 0.04em; }}
.sample-chip {{ display: inline-block; font-family: var(--font-display); font-style: italic; font-size: 14px; color: var(--fg-3); border: 1px solid rgba(246,242,230,0.10); padding: 4px 10px; border-radius: 999px; opacity: 0.75; }}
</style></head><body>
<div class='title'>Typography</div>
<div class='subtitle'>Cormorant Garamond · Inter · JetBrains Mono</div>

<div class='specimen first'>
  <div class='role'>Display</div>
  <div class='sample-display'>The Exposure Triangle</div>
  <div class='meta'>Cormorant Garamond<br>500 · 56px · -1.5%</div>
</div>
<div class='specimen'>
  <div class='role'>Display italic</div>
  <div class='sample-display-italic'>Three controls, one light budget.</div>
  <div class='meta'>Cormorant Garamond<br>400 italic · 28px</div>
</div>
<div class='specimen'>
  <div class='role'>Body — lead</div>
  <div class='sample-body-lg'>Think of your camera's sensor as a bucket collecting rain. Each control changes how the bucket is filled.</div>
  <div class='meta'>Inter<br>400 · 20px · 1.6</div>
</div>
<div class='specimen'>
  <div class='role'>Body — copy</div>
  <div class='sample-body'>A wide-open Camera Iris creates shallow depth of field and bokeh. Closed or moderate would keep more of the scene in focus.</div>
  <div class='meta'>Inter<br>400 · 15px · 1.6</div>
</div>
<div class='specimen'>
  <div class='role'>UI label</div>
  <div class='sample-ui'>Iris &nbsp;·&nbsp; Duration &nbsp;·&nbsp; Sensitivity</div>
  <div class='meta'>Inter<br>500 · 12px · uppercase 0.16em</div>
</div>
<div class='specimen'>
  <div class='role'>Numeric readout</div>
  <div class='sample-mono'>f/1.8 &nbsp; 1/500 s &nbsp; ISO 100</div>
  <div class='meta'>JetBrains Mono<br>500 · 18px · tabular figs</div>
</div>
<div class='specimen'>
  <div class='role'>Technical chip</div>
  <div class='sample-chip'>aperture &nbsp;·&nbsp; f-stop</div>
  <div class='meta'>Cormorant Italic<br>400 · 14px · 75% opacity</div>
</div>

</body></html>"""


# --- Visual hierarchy panel -------------------------------------------------

HIERARCHY_HTML = f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS_CSS}
body {{ padding: 40px 56px; }}
.lede {{ color: var(--fg-2); max-width: 64ch; line-height: 1.6; margin-bottom: 28px; font-size: 14px; }}
.diagram {{ display: grid; grid-template-columns: 1fr 280px; gap: 32px; align-items: stretch; }}
.mock {{ background: var(--bg-1); border-radius: 10px; padding: 18px 24px; position: relative; min-height: 540px; display: flex; flex-direction: column; gap: 14px; border: 1px solid rgba(246,242,230,0.10); }}
.mock .frame-top {{ display: flex; gap: 14px; color: var(--fg-3); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; padding-bottom: 8px; border-bottom: 1px solid rgba(246,242,230,0.06); }}
.mock .frame-top .here {{ color: var(--fg-0); }}
.mock .body-title {{ font-family: var(--font-display); font-weight: 500; font-size: 38px; color: var(--fg-0); margin: 14px 0 4px; letter-spacing: -0.01em; }}
.mock .body-prompt {{ font-family: var(--font-body); font-size: 18px; color: var(--fg-1); max-width: 56ch; line-height: 1.55; }}
.mock .body-vis {{ background: var(--bg-2); border-radius: 8px; height: 180px; display: flex; align-items: center; justify-content: center; color: var(--fg-3); font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase; }}
.mock .margin-chip {{ position: absolute; top: 18px; right: 24px; font-family: var(--font-display); font-style: italic; font-size: 13px; color: var(--fg-3); opacity: 0.65; border: 1px solid rgba(246,242,230,0.10); padding: 3px 9px; border-radius: 999px; }}
.mock .cta-row {{ margin-top: auto; display: flex; justify-content: space-between; align-items: center; }}
.mock .cta-prev {{ color: var(--fg-3); font-size: 13px; }}
.mock .cta-next {{ background: var(--amber-400); color: #0b0b0c; padding: 10px 18px; border-radius: 6px; font-weight: 500; font-size: 14px; letter-spacing: 0.04em; }}
.legend {{ display: flex; flex-direction: column; gap: 16px; }}
.legend .item {{ background: var(--bg-1); border-radius: 8px; padding: 14px 16px; border: 1px solid rgba(246,242,230,0.10); }}
.legend .item .num {{ display: inline-block; width: 22px; height: 22px; border-radius: 999px; background: var(--amber-400); color: #0b0b0c; font-weight: 600; text-align: center; line-height: 22px; font-size: 12px; margin-right: 8px; }}
.legend .item .name {{ font-family: var(--font-display); font-size: 18px; font-weight: 500; color: var(--fg-0); }}
.legend .item p {{ margin: 6px 0 0; font-size: 13px; color: var(--fg-2); line-height: 1.55; }}
.callout {{ position: absolute; border: 1px dashed rgba(224,168,90,0.55); border-radius: 6px; pointer-events: none; }}
.cf-frame {{ inset: 14px 18px auto 18px; height: 28px; }}
.cf-body  {{ inset: 64px 18px 70px 18px; }}
.cf-margin {{ top: 14px; right: 18px; width: 130px; height: 28px; }}
</style></head><body>
<div class='title'>Visual hierarchy</div>
<div class='subtitle'>Three reading layers · conceptual grouping</div>
<p class='lede'>Every flow page resolves to three layers the reader processes in order:
the <em>frame</em> (where am I in the flow), the <em>body</em> (what am I learning right now),
and the <em>margins</em> (parenthetical detail for advanced readers).
Color, weight, and contrast carry the layer assignment — not borders or boxes.</p>
<div class='diagram'>
  <div class='mock'>
    <div class='callout cf-frame'></div>
    <div class='callout cf-body'></div>
    <div class='callout cf-margin'></div>
    <div class='frame-top'>
      <span>Intro</span><span class='here'>Iris</span><span>Duration</span><span>Sensitivity</span><span>Triangle</span><span>Quizzes</span><span>Result</span>
    </div>
    <div class='margin-chip'>aperture · f-stop</div>
    <div class='body-title'>Camera Iris</div>
    <div class='body-prompt'>Drag the dial to widen or narrow the iris. Notice how the bokeh in the background changes shape and softness with the opening.</div>
    <div class='body-vis'>image / control widget</div>
    <div class='cta-row'>
      <span class='cta-prev'>← Previous</span>
      <span class='cta-next'>Next →</span>
    </div>
  </div>
  <div class='legend'>
    <div class='item'><span class='num'>1</span><span class='name'>Frame</span><p>Chapter strip + page-nav. Low-contrast typography (uppercase tracking 0.14em, fg-3) so it stays subordinate. Active chapter takes fg-0 only.</p></div>
    <div class='item'><span class='num'>2</span><span class='name'>Body</span><p>Title (display serif) → prompt (body sans) → visual → primary CTA in accent amber. Highest contrast lives here.</p></div>
    <div class='item'><span class='num'>3</span><span class='name'>Margins</span><p>Technical-term chips, captions, secondary nav. Italic display at 65% opacity — present without pulling focus.</p></div>
  </div>
</div>
</body></html>"""


def render(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    panels = [
        ("color_palette.png", PALETTE_HTML),
        ("typography.png", TYPOGRAPHY_HTML),
        ("visual_hierarchy.png", HIERARCHY_HTML),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=PANEL, device_scale_factor=2)
        page = context.new_page()
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            for name, html in panels:
                f = tdir / name.replace(".png", ".html")
                f.write_text(html)
                page.goto(f.as_uri(), wait_until="networkidle")
                # web fonts: give them a moment past networkidle.
                page.wait_for_timeout(800)
                target = out_dir / name
                page.screenshot(path=str(target), full_page=False)
                print(f"  -> {target}")
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    render(args.out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
