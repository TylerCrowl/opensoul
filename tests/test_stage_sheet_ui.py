"""Storyboard: the stage-sheet UI (static checks on storyboard.js / index.html; review/stage_ui has the screenshots)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "web" / "static" / "storyboard.js").read_text()
HTML = (ROOT / "app" / "web" / "index.html").read_text()


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\(.*?\n  }\n", JS, re.S)
    assert m, name
    return m.group(0)


def test_board_has_a_stages_row_with_new_stage():
    assert 'id="sbStageList"' in HTML and "renderStages();" in _fn("render")
    r = _fn("renderStages")
    assert 'id="sbNewStage"' in r and "openStage(null)" in r and "l.readiness" in r


def test_new_stage_from_an_upload_or_a_take():
    h, w = _fn("newStageHTML"), _fn("wireNewStage")
    assert 'data-src="upload"' in h and 'data-src="take"' in h and 'id="sbStConsent"' in h
    assert 'fd.append("role", "master")' in w and "from_version: $(\"sbStTakeSel\").value" in w
    assert "already a stage called" in w  # no silent overwrite of an existing stage


def test_editor_angles_add_regenerate_rename_remove_and_build():
    h, w = _fn("stageHTMLFor") + _fn("angleTileHTML"), _fn("renderStageSheet")
    for bit in ("data-make=", "data-regen=", "data-del-angle=", 'class="sb-at-name"', 'id="sbStBuild"', "sb-check-list",
                'id="sbStEmpty"', 'id="sbStCheck"', "sheet_stale", "hints.max"):
        assert bit in h, bit
    assert "generate: true" in w and "rename: nv" in w and "`${base}/sheet`" in w and 'method: "DELETE"' in w
    assert "if (l.rendering) poll();" in w
    assert "(p.locations || []).some((l) => l.rendering)" in _fn("poll")


def test_shot_picker_links_to_the_stage_editor():
    h = _fn("stagePickHTML")
    assert 'id="sbStageNew"' in h and 'id="sbStageEdit"' in h and 'id="sbStageFromTake"' in h
    assert "openStage(null, { shot: s.id, from:" in _fn("renderSheet")


def test_no_python_join_in_js():
    assert '" ".join(' not in JS


def test_new_stage_form_survives_a_background_refresh():
    """B_02 (QA round 2): while another take/angle rendered, the 4 s poll redrew the New stage form, so the rights box
    (and the chosen picture) reset on every refresh and a master plate could never be uploaded."""
    r = _fn("renderStageSheet")
    assert 'querySelector("#sbStName[data-new-stage]")) return;' in r  # drawn once, never wiped by a refresh
    assert 'id="sbStName" data-new-stage' in _fn("newStageHTML")
    # the editor keeps a chosen-but-not-yet-confirmed master plate too, and redraws once it is uploaded
    assert "const pending = $(\"sbStBuild\") && $(\"sbStFile\")" in r and "if (pending ||" in r
    assert '$("sbStFile").value = "";' in r
    assert '$("sbSheetBody").innerHTML = "";' in _fn("openStage") and '$("sbSheetBody").innerHTML = "";' in _fn("wireNewStage")


def test_angle_counts_use_one_definition():
    """Row, shot picker and editor all show the server's angle_count (angles with a picture, master not counted)."""
    assert 'plural(l.angle_count || 0, "angle")' in _fn("renderStages")
    assert 'plural(l.angle_count, "angle")' in _fn("stagePickHTML")
    assert "Math.min(l.angle_count || 0, hints.max)} of ${hints.max}" in _fn("stageHTMLFor")
    assert "l.angles.length + 1" not in JS and "l.angles.length + (l.image_url" not in JS


def test_stage_sheet_opens_in_an_in_app_lightbox_without_server_paths():
    """QA round 2: 'Open the stage sheet' opened a raw /api/file?path=/tmp/... URL in a new tab."""
    assert 'target="_blank"' not in _fn("stageHTMLFor") and 'target="_blank"' not in _fn("stagePickHTML")
    assert 'data-lightbox="${esc(l.sheet_url)}"' in _fn("stageHTMLFor")
    assert 'data-lightbox="${esc(loc.sheet_url)}"' in _fn("stagePickHTML")
    lb = _fn("openLightbox")
    assert 'role", "dialog"' in lb and "sb-lb-close" in lb and "e.target === box" in lb  # click outside / × closes
    assert "Escape" in JS and "closeLightbox();" in JS


def test_take_picker_thumbnails_upload_thumbnail_and_rename_pencil():
    """QA round 2 (LOW): takes were a text-only select, a chosen file showed only its name, names had no rename cue."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    js, css = (root / "storyboard.js").read_text(), (root / "storyboard.css").read_text()
    assert "function takeStripHTML(" in js and js.count("${takeStripHTML(takes") + js.count("? takeStripHTML(takes") == 2  # new-stage form and editor
    assert js.count('wireFileThumb($("sbStFile")') == 2 and 'wireFileThumb($("sbCFile"), "sbCFileThumb")' in js
    assert "URL.revokeObjectURL" in js and 'sel.dispatchEvent(new Event("change"))' in js
    assert ".sb-take-pick img" in css and ".sb-file-thumb" in css
    pencil = css[css.index("input.sb-beat, input.sb-sheet-name, #sbTitle, .sb-at-name,"):]
    assert "input.sb-beat:hover" in pencil.split("{", 1)[0] and "svg" in pencil.split("}", 1)[0]
