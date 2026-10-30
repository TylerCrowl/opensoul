"""Prompt strength is greyed out on the talk path (and back when the line goes); the Music result counts the Sync rows;
the Stages meta never splits '6 shots'; skipped Export tiles carry a faint clapper, not a second status."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
MUSIC = (ROOT / "app/web/static/music.js").read_text(encoding="utf-8")
SB = (ROOT / "app/web/static/storyboard.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def _fn(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


def _node(js: str):
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


@needs_node
def test_prompt_strength_is_disabled_for_a_talking_shot_and_back_when_the_line_goes():
    js = """
const els = {line: {value: ""}, advLipsync: {value: ""}, advCfgNote: {hidden: true}, advCfg: {disabled: false, title: ""}};
const $ = (id) => els[id];
%s
const out = [];
const snap = () => out.push([els.advCfg.disabled, els.advCfgNote.hidden]);
snap();                                                        // no line
els.line.value = "Morning!"; syncCfgNote(); snap();            // spoken line, default engine (LTX audio+video)
els.advLipsync.value = "latentsync"; syncCfgNote(); snap();    // another engine: the strength is used again
els.advLipsync.value = "ltx_av"; syncCfgNote(); snap();
els.line.value = "   "; syncCfgNote(); snap();                 // line removed
console.log(JSON.stringify(out));
""" % _fn(APP, "syncCfgNote")
    assert _node(js) == [[False, True], [True, False], [False, True], [True, False], [False, True]]
    # a disabled field is not sent, looks disabled, and keeps its note under it
    assert 'cfg: $("advCfg").disabled ? undefined :' in APP
    css = (ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    assert 'input[type="number"]:disabled {' in css and "not-allowed" in css.split('input[type="number"]:disabled {')[1].split("}")[0]
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    assert 'id="advCfg"' in html and html.index('id="advCfg"') < html.index('id="advCfgNote"')


@needs_node
def test_music_result_counts_the_shots_with_singing():
    js = _fn(MUSIC, "singingCount") + "\nconsole.log(JSON.stringify([0, 1, 3].map(singingCount)));"
    assert _node(js) == ["none have singing to sync", "1 has singing to sync", "3 have singing to sync"]
    assert '`Made ${plural(d.shots.length, "shot")} in “${d.title}”; ${singingCount(sung.length)}.' in MUSIC
    assert MUSIC.index("const sung = d.shots.filter((s) => s.lipsync);") < MUSIC.index("${singingCount(sung.length)}")


def test_stage_counts_stay_on_one_line_and_skipped_tiles_show_a_faint_clapper():
    card = SB[SB.index('class="sb-stage-card'):SB.index('id="sbNewStage"')]
    assert '<span class="sb-stage-s">${esc(state)}</span>' in card and 'class="sb-stage-s sb-stage-c"' in card
    css = (ROOT / "app/web/static/storyboard.css").read_text(encoding="utf-8")
    assert "white-space: nowrap" in css.split(".sb-stage-c {")[1].split("}")[0]
    assert "opacity: .35" in css.split(".sb-reel-ph {")[1].split("}")[0]
    reel = SB[SB.index('$("sbReel").innerHTML = p.shots.map'):SB.index("async function exportStory()")]
    assert ": CLAPPER;" in reel and reel.count("Skipped · ${why}") == 1 and '"No approved take"' not in reel
