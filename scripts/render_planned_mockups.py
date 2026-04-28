"""Render the HW11 graphic-design mockups (the planned upgrade over
the deployed technical prototype) as PNGs.

Two artifact families:

- **Components** — single-purpose UI primitives in isolation (dial,
  tuner). Sourced from design/components-*.html which already exist.
- **Planned screens** — full-screen mockups of how each surface in the
  flow should look once the Aperture design system is fully applied.
  These are written inline and screenshotted side-by-side with the
  deployed-prototype captures from capture_hw11_screens.py.

Outputs:
    component_dial.png
    component_tuner.png
    component_quiz_options.png
    planned_home.png
    planned_intro.png
    planned_learn.png
    planned_quiz.png
    planned_result.png

Usage:
    uv run python scripts/render_planned_mockups.py [--out DIR]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = REPO_ROOT / "design"
DEFAULT_OUT = REPO_ROOT.parent / "hw11" / "placeholders"
SCREEN = {"width": 1440, "height": 900}
COMPONENT = {"width": 720, "height": 360}


# Inline shared CSS — copies the Aperture tokens so each mockup is
# self-contained. Lifted from design/colors_and_type.css (truncated to
# the tokens the mockups actually use).
TOKENS = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
:root {
  --bg-0:#0b0b0c; --bg-1:#141416; --bg-2:#1c1c1f; --bg-3:#26262b; --bg-4:#34343a;
  --fg-0:#f4f1ea; --fg-1:#d6d2c6; --fg-2:#9a958a; --fg-3:#6b6860; --fg-4:#403e3a;
  --stroke-1:rgba(246,242,230,0.06); --stroke-2:rgba(246,242,230,0.10); --stroke-3:rgba(246,242,230,0.18);
  --amber-300:#f3c67a; --amber-400:#e0a85a; --amber-500:#c08140; --amber-glow:rgba(224,168,90,0.18);
  --meter-green:#7ba86f; --meter-green-bg:rgba(123,168,111,0.10);
  --meter-red:#c0564a;   --meter-red-bg:rgba(192,86,74,0.10);
  --font-display:'Cormorant Garamond', Georgia, serif;
  --font-body:'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono:'JetBrains Mono', ui-monospace, Menlo, monospace;
  --radius-md:6px; --radius-lg:10px; --radius-round:999px;
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; background: var(--bg-0); color: var(--fg-1); font-family: var(--font-body); }
.shell { min-height: 100vh; display: flex; flex-direction: column; padding: 28px 64px 36px; }
.chapter-nav { display:flex; gap: 28px; padding-bottom: 14px; border-bottom: 1px solid var(--stroke-1); font-family: var(--font-body); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-3); }
.chapter-nav .item { position: relative; padding-bottom: 4px; }
.chapter-nav .item.active { color: var(--fg-0); }
.chapter-nav .item.active::after { content:""; position:absolute; left:0; right:0; bottom:-15px; height:2px; background: var(--amber-400); }
.chapter-nav .item.muted { color: var(--fg-4); }
.page { flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 24px 0; }
.btn-primary { background: var(--amber-400); color: var(--bg-0); padding: 10px 20px; border-radius: var(--radius-md); font-weight: 500; letter-spacing: 0.04em; border: 0; }
.btn-secondary { background: transparent; color: var(--fg-2); border: 1px solid var(--stroke-2); padding: 10px 18px; border-radius: var(--radius-md); }
.page-nav { display: flex; justify-content: space-between; padding-top: 24px; border-top: 1px solid var(--stroke-1); }
.tech-chip { display: inline-block; font-family: var(--font-display); font-style: italic; font-size: 13px; color: var(--fg-3); border: 1px solid var(--stroke-2); padding: 3px 9px; border-radius: 999px; opacity: 0.7; }
"""


def _chapter_nav(active: str = "iris") -> str:
    items = [("intro","Intro"),("iris","Iris"),("duration","Duration"),("sensitivity","Sensitivity"),("triangle","Triangle"),("quizzes","Quizzes"),("result","Result")]
    bits = []
    for slug, label in items:
        cls = "item active" if slug == active else ("item muted" if slug in ("result",) and active != "result" else "item")
        bits.append(f'<span class="{cls}">{label}</span>')
    return f'<nav class="chapter-nav">{"".join(bits)}</nav>'


# ---------------------------------------------------------------- components

QUIZ_OPTIONS_HTML = f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
body {{ padding: 36px; }}
.label {{ font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-3); margin-bottom: 10px; }}
.opt-list {{ display: flex; flex-direction: column; gap: 10px; max-width: 520px; }}
.opt {{ padding: 12px 16px; border-radius: var(--radius-md); border: 1px solid var(--stroke-2); color: var(--fg-1); background: var(--bg-1); }}
.opt.disabled-wrong {{ background: rgba(224,168,90,0.10); border-color: rgba(224,168,90,0.45); color: var(--amber-300); }}
.opt.incorrect    {{ background: var(--meter-red-bg); border-color: rgba(192,86,74,0.55); color: var(--meter-red); text-decoration: line-through; }}
.opt.correct      {{ background: var(--meter-green-bg); border-color: rgba(123,168,111,0.55); color: var(--meter-green); }}
.row {{ display: flex; gap: 36px; align-items: flex-start; }}
.col h3 {{ font-family: var(--font-display); font-weight: 500; font-size: 18px; color: var(--fg-0); margin: 0 0 12px; }}
</style></head><body>
<div class='row'>
  <div class='col'>
    <h3>Initial</h3>
    <div class='label'>4 options · neutral</div>
    <div class='opt-list'>
      <div class='opt'>Wide open Camera Iris</div>
      <div class='opt'>Very closed Camera Iris</div>
      <div class='opt'>Moderate Camera Iris</div>
    </div>
  </div>
  <div class='col'>
    <h3>First wrong (try again)</h3>
    <div class='label'>amber gray-out · others stay live</div>
    <div class='opt-list'>
      <div class='opt'>Wide open Camera Iris</div>
      <div class='opt disabled-wrong'>Very closed Camera Iris</div>
      <div class='opt'>Moderate Camera Iris</div>
    </div>
  </div>
  <div class='col'>
    <h3>Locked</h3>
    <div class='label'>second wrong · reveal correct</div>
    <div class='opt-list'>
      <div class='opt correct'>Wide open Camera Iris</div>
      <div class='opt incorrect'>Very closed Camera Iris</div>
      <div class='opt incorrect'>Moderate Camera Iris</div>
    </div>
  </div>
</div>
</body></html>"""


# ---------------------------------------------------------------- screens

def planned_home() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
.shell {{ padding: 0; }}
.page {{ padding: 0; min-height: 100vh; }}
.brand {{ position: absolute; top: 28px; left: 64px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-3); }}
.brand b {{ color: var(--amber-400); font-weight: 500; }}
.title {{ font-family: var(--font-display); font-weight: 400; font-size: 72px; color: var(--fg-0); letter-spacing: -0.015em; margin: 0 0 6px; }}
.subtitle {{ font-family: var(--font-display); font-style: italic; font-size: 22px; color: var(--fg-2); margin: 0 0 36px; }}
.lede {{ font-family: var(--font-body); font-size: 18px; color: var(--fg-1); margin: 0 0 32px; }}
.lede b {{ color: var(--amber-300); font-weight: 500; }}
.three {{ display: grid; grid-template-columns: repeat(3, 240px); gap: 18px; margin: 0 0 36px; }}
.pillar {{ background: var(--bg-1); border: 1px solid var(--stroke-2); border-radius: var(--radius-lg); padding: 22px 18px 20px; text-align: left; }}
.pillar .icon {{ width: 32px; height: 32px; color: var(--amber-400); margin-bottom: 12px; }}
.pillar .name {{ font-family: var(--font-display); font-size: 22px; color: var(--fg-0); margin: 0 0 4px; }}
.pillar .tag {{ font-family: var(--font-body); font-size: 13px; color: var(--fg-2); margin: 0; }}
.tagline {{ color: var(--fg-2); font-size: 14px; max-width: 56ch; margin: 0 0 28px; }}
.cta {{ display: inline-block; background: var(--amber-400); color: var(--bg-0); padding: 14px 36px; border-radius: var(--radius-md); font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; font-size: 13px; }}
.center {{ text-align: center; }}
.foot {{ position: absolute; bottom: 24px; left: 64px; font-family: var(--font-mono); font-size: 11px; color: var(--fg-3); letter-spacing: 0.08em; }}
</style></head><body>
<div class='shell'>
  <div class='brand'><b>APERTURE</b> · the exposure triangle</div>
  <div class='page center'>
    <h1 class='title'>The Exposure Triangle</h1>
    <p class='subtitle'>An interactive lesson on how light becomes a photograph</p>
    <p class='lede'>Think of your camera's sensor as a <b>bucket</b> collecting rain.</p>
    <div class='three'>
      <div class='pillar'>
        <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><circle cx='12' cy='12' r='9'/><path d='M12 3 L21 12 L12 21 L3 12 Z' opacity='.5'/></svg>
        <div class='name'>Camera Iris</div>
        <p class='tag'>How wide is the opening?</p>
      </div>
      <div class='pillar'>
        <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><circle cx='12' cy='13' r='8'/><path d='M12 9 v4 l2.5 2.5'/><path d='M9 2 h6'/></svg>
        <div class='name'>Capture Duration</div>
        <p class='tag'>How long is it left out?</p>
      </div>
      <div class='pillar'>
        <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><path d='M13 2 L3 14 h7 l-1 8 L19 10 h-7 z'/></svg>
        <div class='name'>Sensor Sensitivity</div>
        <p class='tag'>How big is the bucket?</p>
      </div>
    </div>
    <p class='tagline'>Overfill the bucket = too bright. Underfill = too dark.<br/>Three controls, one light budget. Let's learn each one.</p>
    <div><span class='cta'>Begin →</span></div>
  </div>
  <div class='foot'>BLAKE VENTE (rv2459) · COMSW4170</div>
</div>
</body></html>"""


def planned_intro() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
.title {{ font-family: var(--font-display); font-weight: 400; font-size: 64px; color: var(--fg-0); letter-spacing: -0.015em; margin: 0 0 24px; }}
.lede  {{ font-family: var(--font-body); font-size: 18px; color: var(--fg-1); line-height: 1.6; max-width: 62ch; margin: 0 0 24px; }}
.lede b  {{ color: var(--amber-300); font-weight: 500; }}
.beats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 24px 0 32px; max-width: 880px; }}
.beat {{ background: var(--bg-1); border: 1px solid var(--stroke-2); border-radius: var(--radius-lg); padding: 14px 14px 12px; }}
.beat .ord {{ font-family: var(--font-mono); font-size: 10px; color: var(--amber-400); letter-spacing: 0.16em; text-transform: uppercase; margin-bottom: 6px; }}
.beat .what {{ font-family: var(--font-display); font-size: 17px; color: var(--fg-0); margin-bottom: 4px; }}
.beat .when {{ font-family: var(--font-mono); font-size: 11px; color: var(--fg-3); }}
.aside {{ font-family: var(--font-display); font-style: italic; font-size: 18px; color: var(--fg-2); border-left: 2px solid var(--amber-400); padding-left: 14px; max-width: 60ch; margin-bottom: 36px; }}
</style></head><body>
<div class='shell'>
  {_chapter_nav('iris')}
  <div class='page' style='align-items: flex-start; max-width: 940px; margin: 0 auto;'>
    <h1 class='title'>Press the shutter</h1>
    <p class='lede'>One press. The <b>iris</b> snaps to its diameter; the <b>shutter</b> lifts; light rains into a grid of millions of tiny <b>buckets</b> on the sensor; the curtain falls. All in milliseconds.</p>
    <div class='beats'>
      <div class='beat'><div class='ord'>Beat 1</div><div class='what'>Iris snaps</div><div class='when'>0 ms</div></div>
      <div class='beat'><div class='ord'>Beat 2</div><div class='what'>Shutter lifts</div><div class='when'>+0.2 ms</div></div>
      <div class='beat'><div class='ord'>Beat 3</div><div class='what'>Buckets fill</div><div class='when'>0.2 → 8 ms</div></div>
      <div class='beat'><div class='ord'>Beat 4</div><div class='what'>Curtain falls</div><div class='when'>+8 ms</div></div>
    </div>
    <p class='aside'>The page is dark for a reason — your eyes are doing photography too. A wider iris in low light is more sensitive to subtle tone.</p>
  </div>
  <div class='page-nav'><span class='btn-secondary'>← Previous</span><span class='btn-primary'>Continue →</span></div>
</div>
</body></html>"""


def planned_learn() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
.layout {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 40px; align-items: center; max-width: 1240px; margin: 0 auto; }}
.media {{ aspect-ratio: 4/3; background: linear-gradient(140deg, #0b1820, #1c0e08 60%, #2a1308); border-radius: var(--radius-lg); border: 1px solid var(--stroke-2); display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; }}
.media::after {{ content:''; position:absolute; inset:auto; width:120px; height:120px; border-radius:50%; background: radial-gradient(circle, rgba(243,198,122,0.55) 0%, rgba(243,198,122,0) 65%); top: 30%; left: 28%; filter: blur(6px); }}
.media .placeholder {{ color: var(--fg-3); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; z-index: 1; }}
.title {{ font-family: var(--font-display); font-weight: 500; font-size: 44px; color: var(--fg-0); letter-spacing: -0.015em; margin: 0 0 6px; }}
.copy {{ font-family: var(--font-body); font-size: 16px; color: var(--fg-1); line-height: 1.6; max-width: 46ch; margin: 0 0 28px; }}
.tuner {{ background: var(--bg-1); border: 1px solid var(--stroke-2); border-radius: var(--radius-lg); padding: 16px 18px 14px; box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 -1px 0 rgba(0,0,0,0.4) inset, 0 1px 2px rgba(0,0,0,0.5); }}
.tuner-head {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }}
.tuner-read {{ font-family: var(--font-display); font-size: 22px; color: var(--fg-0); }}
.tuner-strip {{ position: relative; height: 48px; background: var(--bg-0); border-radius: var(--radius-md); border: 1px solid var(--stroke-1); }}
.tuner-ticks {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: space-between; padding: 0 12px; }}
.tuner-tick {{ width: 1px; background: var(--fg-4); }}
.tuner-tick.major {{ background: var(--fg-3); }}
.tuner-needle {{ position: absolute; top: 4px; bottom: 4px; width: 2px; background: var(--amber-400); left: 30%; box-shadow: 0 0 8px var(--amber-glow); }}
.tuner-labels {{ display: flex; justify-content: space-between; margin-top: 8px; font-family: var(--font-mono); font-size: 10px; color: var(--fg-3); letter-spacing: 0.08em; text-transform: uppercase;}}
.label-plate {{ font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-3); }}
.chip-row {{ display: flex; gap: 8px; margin-bottom: 12px; }}
</style></head><body>
<div class='shell'>
  {_chapter_nav('iris')}
  <div class='page' style='align-items: stretch;'>
    <div class='layout'>
      <div class='media'><span class='placeholder'>render — bokeh f/1.8</span></div>
      <div>
        <div class='chip-row'><span class='tech-chip'>aperture · f-stop</span></div>
        <h1 class='title'>Camera Iris</h1>
        <p class='copy'>The iris controls how wide your camera's pupil opens. Wider = more light in <em>and</em> shallower focus, so the background falls into bokeh while the subject stays sharp.</p>
        <div class='tuner'>
          <div class='tuner-head'>
            <span class='label-plate'>Camera Iris · f-stop</span>
            <span class='tuner-read'>f/1.8</span>
          </div>
          <div class='tuner-strip'>
            <div class='tuner-ticks'>
              <span class='tuner-tick major' style='height:22px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick major' style='height:22px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick major' style='height:22px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick' style='height:10px'></span>
              <span class='tuner-tick major' style='height:22px'></span>
            </div>
            <div class='tuner-needle'></div>
          </div>
          <div class='tuner-labels'><span>f/1.4</span><span>f/2.8</span><span>f/5.6</span><span>f/11</span><span>f/22</span></div>
        </div>
      </div>
    </div>
  </div>
  <div class='page-nav'><span class='btn-secondary'>← Previous</span><span class='btn-primary'>Continue →</span></div>
</div>
</body></html>"""


def planned_quiz() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
.q-head {{ display: flex; justify-content: space-between; max-width: 880px; margin: 0 auto 12px; font-family: var(--font-mono); font-size: 11px; color: var(--fg-3); letter-spacing: 0.12em; text-transform: uppercase; }}
.q-frame {{ max-width: 880px; margin: 0 auto; }}
.media {{ aspect-ratio: 16/9; background: linear-gradient(160deg, #14191a, #0e1314); border-radius: var(--radius-lg); margin-bottom: 18px; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; }}
.media::after {{ content: ''; position: absolute; left: 30%; top: 30%; width: 36%; height: 60%; border-radius: 50%; background: radial-gradient(circle, rgba(243,198,122,0.35) 0%, rgba(243,198,122,0) 70%); }}
.media .ph {{ color: var(--fg-3); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; z-index: 2; }}
.setup {{ font-family: var(--font-body); font-size: 15px; color: var(--fg-2); max-width: 64ch; margin: 0 0 12px; line-height: 1.55; }}
.prompt {{ font-family: var(--font-display); font-weight: 500; font-size: 28px; color: var(--fg-0); margin: 0 0 18px; letter-spacing: -0.01em; }}
.opt {{ display: block; padding: 14px 18px; border-radius: var(--radius-md); border: 1px solid var(--stroke-2); background: var(--bg-1); color: var(--fg-1); margin-bottom: 8px; font-size: 15px; }}
.opt:hover {{ border-color: var(--stroke-3); }}
.opt.selected-correct {{ background: var(--meter-green-bg); border-color: rgba(123,168,111,0.55); color: var(--meter-green); }}
.feedback {{ display: flex; gap: 12px; align-items: center; padding: 12px 16px; border-radius: var(--radius-md); background: var(--meter-green-bg); border: 1px solid rgba(123,168,111,0.45); color: var(--meter-green); font-family: var(--font-body); font-size: 14px; margin-top: 16px; }}
.feedback .mark {{ font-family: var(--font-mono); font-size: 13px; }}
</style></head><body>
<div class='shell'>
  {_chapter_nav('quizzes')}
  <div class='page' style='align-items: stretch;'>
    <div class='q-frame'>
      <div class='q-head'><span>Question 4 of 8</span><span>Category: combo</span></div>
      <div class='media'><span class='ph'>render — bokeh f/1.8 daylight</span></div>
      <p class='setup'>Look at this photo carefully. The foreground subject is in focus, the background is blurry with bokeh, and there is no motion streaking or noise.</p>
      <h2 class='prompt'>Which settings produced this?</h2>
      <div>
        <div class='opt selected-correct'>Wide open Camera Iris, short Capture Duration, low Sensor Sensitivity</div>
        <div class='opt'>Very closed Camera Iris, long Capture Duration, high Sensor Sensitivity</div>
        <div class='opt'>Moderate Camera Iris, medium Capture Duration, medium Sensor Sensitivity</div>
      </div>
      <div class='feedback'><span class='mark'>✓</span><span><b>Correct.</b> Blurry background = wide-open Iris. No motion streaking = short Capture Duration. No grain = low Sensitivity.</span></div>
    </div>
  </div>
  <div class='page-nav'><span class='btn-secondary'>← Previous</span><span class='btn-primary'>Continue →</span></div>
</div>
</body></html>"""


def planned_result() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>{TOKENS}
.frame {{ max-width: 920px; margin: 0 auto; width: 100%; }}
.score {{ font-family: var(--font-display); font-weight: 400; font-size: 44px; color: var(--fg-0); margin: 0 0 4px; letter-spacing: -0.015em; }}
.score b {{ color: var(--amber-400); font-weight: 500; }}
.subscore {{ font-family: var(--font-mono); font-size: 13px; color: var(--fg-2); margin: 0 0 22px; letter-spacing: 0.08em; }}
.banner {{ background: rgba(224,168,90,0.10); border: 1px solid rgba(224,168,90,0.45); border-radius: var(--radius-md); padding: 14px 18px; margin: 0 0 24px; color: var(--amber-300); font-size: 14px; line-height: 1.55; }}
.banner b {{ color: var(--amber-400); }}
.section-h {{ font-family: var(--font-display); font-weight: 500; font-size: 22px; color: var(--fg-0); margin: 0 0 14px; }}
.row {{ background: var(--bg-1); border: 1px solid var(--stroke-2); border-radius: var(--radius-md); padding: 14px 16px; margin-bottom: 10px; }}
.row .top {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
.row .qid {{ font-family: var(--font-display); font-weight: 500; font-size: 17px; color: var(--fg-0); }}
.row .cat {{ font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--fg-3); margin-left: 8px; }}
.row .badges {{ display: flex; gap: 6px; }}
.badge {{ font-family: var(--font-mono); font-size: 11px; padding: 2px 10px; border-radius: 999px; }}
.badge.green {{ background: var(--meter-green-bg); color: var(--meter-green); border: 1px solid rgba(123,168,111,0.45); }}
.badge.red   {{ background: var(--meter-red-bg);   color: var(--meter-red);   border: 1px solid rgba(192,86,74,0.45); }}
.badge.gray  {{ background: var(--bg-3); color: var(--fg-2); border: 1px solid var(--stroke-1); }}
.badge.bonus {{ background: rgba(224,168,90,0.10); color: var(--amber-400); border: 1px solid rgba(224,168,90,0.45); }}
.row .prompt {{ font-family: var(--font-display); font-style: italic; font-size: 15px; color: var(--fg-1); margin-bottom: 6px; }}
.row .ans {{ font-size: 14px; color: var(--fg-1); margin-bottom: 4px; }}
.row .ans .yes {{ color: var(--meter-green); }}
.row .ans .no  {{ color: var(--meter-red); }}
.row .why {{ font-size: 13px; color: var(--fg-2); border-top: 1px solid var(--stroke-1); padding-top: 8px; margin-top: 8px; line-height: 1.5; }}
.row .why b {{ color: var(--fg-1); }}
</style></head><body>
<div class='shell'>
  {_chapter_nav('result')}
  <div class='page' style='align-items: stretch;'>
    <div class='frame'>
      <p class='score'>Your score · <b>9 / 10</b></p>
      <p class='subscore'>FIRST-TRY CORRECT · 9 / 10</p>
      <div class='banner'><b>★ Bonus round unlocked.</b> 5 of 5 first-try through the burn-in window — threshold was 4. Two bonus questions added to your score line.</div>
      <h2 class='section-h'>Per-question review</h2>

      <div class='row'>
        <div class='top'><span><span class='qid'>Q1</span><span class='cat'>iris</span></span><span class='badges'><span class='badge green'>correct</span><span class='badge gray'>1 attempt</span><span class='badge gray'>4.2 s</span></span></div>
        <div class='prompt'>Which Camera Iris setting was used?</div>
        <div class='ans'>Your answer: <span class='yes'>Wide open Camera Iris ✓</span></div>
        <div class='why'><b>Why:</b> A wide-open Camera Iris creates shallow depth of field and bokeh. Closed or moderate would keep more of the scene in focus.</div>
      </div>

      <div class='row'>
        <div class='top'><span><span class='qid'>Q7</span><span class='cat'>sensitivity</span></span><span class='badges'><span class='badge red'>wrong</span><span class='badge gray'>2 attempts</span><span class='badge gray'>9.1 s</span></span></div>
        <div class='prompt'>What's the tradeoff when you raise Sensor Sensitivity to brighten the image?</div>
        <div class='ans'>Your answer: <span class='no'>Nothing — Sensor Sensitivity is free to raise ✗</span></div>
        <div class='ans'>Correct: <span class='yes'>Visible grain / noise increases</span></div>
        <div class='why'><b>Why:</b> Grain. Depth of field is controlled by the Iris, not by sensitivity. Higher sensitivity = more light captured per unit of real light = more visible noise.</div>
      </div>

      <div class='row'>
        <div class='top'><span><span class='qid'>Q9</span><span class='cat'>iris · bonus</span><span class='badge bonus' style='margin-left: 8px'>★ bonus</span></span><span class='badges'><span class='badge green'>correct</span><span class='badge gray'>1 attempt</span><span class='badge gray'>5.5 s</span></span></div>
        <div class='prompt'>Which photo used the wider Camera Iris?</div>
        <div class='ans'>Your answer: <span class='yes'>Subject sharp, background dissolves into soft bokeh ✓</span></div>
        <div class='why'><b>Why:</b> The one with bokeh. Wide Iris = shallow depth of field = blurry background behind the sharp subject.</div>
      </div>
    </div>
  </div>
  <div class='page-nav'><span class='btn-secondary'>← Previous</span><span class='btn-primary'>Reference card →</span></div>
</div>
</body></html>"""


# ---------------------------------------------------------------- driver

def render(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    component_jobs = [
        ("component_dial.png",         (DESIGN_DIR / "components-dial.html").as_uri(),  COMPONENT, False),
        ("component_tuner.png",        (DESIGN_DIR / "components-tuner.html").as_uri(), COMPONENT, False),
        ("component_quiz_options.png", QUIZ_OPTIONS_HTML,                                {"width": 1300, "height": 360}, True),
    ]
    screen_jobs = [
        ("planned_home.png",   planned_home(),   SCREEN),
        ("planned_intro.png",  planned_intro(),  SCREEN),
        ("planned_learn.png",  planned_learn(),  SCREEN),
        ("planned_quiz.png",   planned_quiz(),   SCREEN),
        ("planned_result.png", planned_result(), SCREEN),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            # components
            for name, url_or_html, viewport, inline in component_jobs:
                ctx = browser.new_context(viewport=viewport, device_scale_factor=2)
                page = ctx.new_page()
                if inline:
                    f = tdir / name.replace(".png", ".html")
                    f.write_text(url_or_html)
                    page.goto(f.as_uri(), wait_until="networkidle")
                else:
                    page.goto(url_or_html, wait_until="networkidle")
                page.wait_for_timeout(700)
                page.screenshot(path=str(out_dir / name), full_page=False)
                ctx.close()
                print(f"  -> {out_dir / name}")
            # screens
            for name, html, viewport in screen_jobs:
                ctx = browser.new_context(viewport=viewport, device_scale_factor=2)
                page = ctx.new_page()
                f = tdir / name.replace(".png", ".html")
                f.write_text(html)
                page.goto(f.as_uri(), wait_until="networkidle")
                page.wait_for_timeout(800)
                page.screenshot(path=str(out_dir / name), full_page=False)
                ctx.close()
                print(f"  -> {out_dir / name}")
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    render(args.out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
