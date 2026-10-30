"""Lip-sync app defaults from the G tests (review/lumi_story/lipsync/G/SUMMARY.md, approved 19 Oct 2026):
04b guider pinned at cfg 1.0/1.0, the articulation prompt in the speaker's own pronoun, 'cartoon, childish' out of
the 04b negative, LatentSync 50 steps, ltx_av still the default, and the rebuilt-character method
(ltx_a2v_artic -> LatentSync when fair LSE-C < 4.5 -> inner-mouth pass) as config logic. No GPU, no models."""
import json
from pathlib import Path

import pytest

from opensoul import lipsync as L

ROOT = Path(__file__).resolve().parents[1]
A2V = json.loads((ROOT / L.A2V_WORKFLOW).read_text())
LS = json.loads((ROOT / L.LATENTSYNC_WORKFLOW).read_text())
SHE = ("She speaks clearly, eyes open: her lips open and close on every syllable, teeth visible on open vowels, "
       "calm neutral expression.")


# ---------------------------------------------------------------- guider, negative, steps, backend
def test_guider_node_is_dual_cfg_and_pinned_at_1_1():
    assert L.N_GUIDER == "34" and A2V["34"]["class_type"] == "LTXVDualCFGGuider"
    assert (A2V["34"]["inputs"]["video_cfg"], A2V["34"]["inputs"]["audio_cfg"]) == (1.0, 1.0)
    st = L.a2v_stage(prompt="p", audio_s=2.0, seed=1)
    assert st["inputs"]["34"] == {"video_cfg": 1.0, "audio_cfg": 1.0}
    drifted = json.loads(json.dumps(A2V))
    drifted["34"]["inputs"].update(video_cfg=3.0, audio_cfg=3.0)  # a workflow edit can't move them
    g = L.patch_graph(drifted, st["inputs"])
    assert (g["34"]["inputs"]["video_cfg"], g["34"]["inputs"]["audio_cfg"]) == (1.0, 1.0)
    assert g["34"]["inputs"]["model"] == A2V["34"]["inputs"]["model"]  # only the cfgs are patched


def test_04b_negative_drops_cartoon_childish_and_keeps_the_rest():
    neg = A2V["21"]["inputs"]["text"]
    assert A2V["21"]["class_type"] == "CLIPTextEncode"
    assert "cartoon" not in neg and "childish" not in neg
    assert neg.startswith("pc game, console game, video game, ugly, distorted face,")
    assert "watermark" in neg and "grimace" in neg


def test_latentsync_workflow_runs_50_steps():
    assert LS["3"]["class_type"] == "OpenSoulLatentSync"
    assert LS["3"]["inputs"]["inference_steps"] == 50 == L.LATENTSYNC_STEPS
    assert LS["3"]["inputs"]["guidance_scale"] == 1.5 and LS["3"]["inputs"]["seed"] == 1247


def test_default_backend_stays_ltx_av_24fps_no_lead_in_8k_plus_1():
    assert L.DEFAULT_BACKEND == "ltx_av" and L.FPS == 24
    st = L.a2v_stage(prompt="p", audio_s=3.3, seed=1)
    f = st["frames"]
    assert (f - 1) % 8 == 0 and st["params"]["fps"] == 24
    assert st["inputs"][L.N_AUDIO_LATENT]["frame_rate"] == 24
    assert st["pad_audio_to_s"] == round(f / 24, 4)  # trailing pad only: no lead-in silence
    assert not any("lead" in k for k in st) and not any("lead" in k for k in st["params"])


# ---------------------------------------------------------------- articulation prompt + pronouns
def test_articulation_text_is_the_approved_sentence_for_she():
    assert L.articulation("she") == SHE


@pytest.mark.parametrize("pronoun,want", [
    ("she", "She speaks clearly, eyes open: her lips"), ("She/her", "She speaks clearly, eyes open: her lips"),
    ("he", "He speaks clearly, eyes open: his lips"), ("he/him", "He speaks clearly, eyes open: his lips"), (["he", "him"], "He speaks"),
    ("they", "They speak clearly, eyes open: their lips"), ("they/them", "They speak clearly, eyes open: their lips"),
    (None, "They speak clearly, eyes open: their lips"), ("", "They speak clearly, eyes open: their lips"),
    ("xe/xem", "They speak clearly, eyes open: their lips")])
def test_pronoun_handling_defaults_to_they(pronoun, want):
    assert L.articulation(pronoun).startswith(want)
    assert L.articulation(pronoun).endswith("on every syllable, teeth visible on open vowels, calm neutral expression.")
    assert "jaw moving" not in L.articulation(pronoun)


def test_pronoun_from_pack_top_level_or_meta_else_they():
    assert L.pronoun_from_meta({"pronoun": "she"}) == "she"
    assert L.pronoun_from_meta({"meta": {"pronouns": "he/him"}}) == "he"
    assert L.pronoun_from_meta({"name": "Mio", "meta": {"origin": {"kind": "text"}}}) == "they"
    assert L.pronoun_from_meta(None) == "they"


def test_speaker_prompt_adds_articulation_once_and_clear_mouth_movements():
    out = L.speaker_prompt("Close-up, small natural mouth movements.", "Lumi", "Whole milk.", "she")
    assert "small natural mouth movements" not in out and "clear natural mouth movements" in out
    assert out.count(L.ARTICULATION_MARK) == 1 and SHE in out
    assert out.endswith('Lumi is the one speaking, lips moving with the words "Whole milk."; the others listen. '
                        "Before the first word, in each pause and after the last word, her lips are closed and still.")
    again = L.speaker_prompt(out, "", "", "she")
    assert again.count(L.ARTICULATION_MARK) == 1


def test_speaker_prompt_without_pronoun_uses_they_never_hardcoded_she():
    out = L.speaker_prompt("At the counter.", "Ren", "Go.")
    assert "They speak clearly, eyes open: their lips" in out and "She " not in out and " her " not in out
    assert L.speaker_prompt("x", "", "").startswith("x They speak clearly")


def test_dialogue_stages_pass_the_pronoun_into_the_a2v_prompt():
    st, _, mode = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                    speaker="Lumi", seed=1, pronoun="she")
    assert mode == "ltx_a2v" and SHE in st[1]["inputs"][L.N_PROMPT]["text"]
    assert st[1]["inputs"]["34"] == {"video_cfg": 1.0, "audio_cfg": 1.0}
    st2, _, _ = L.dialogue_stages(line="Hi.", voice="leo", quality="final", backend="ltx_av", prompt="p",
                                  speaker="Bram", seed=1)
    assert "They speak clearly" in st2[1]["inputs"][L.N_PROMPT]["text"]


# ---------------------------------------------------------------- rebuilt-character method (config logic, fake runner)
def test_rebuilt_method_config():
    m = L.rebuilt_method()
    assert m["method"] == "ltx_a2v_artic" == L.REBUILT_METHOD
    assert m["base"]["backend"] == "ltx_av" and m["base"]["fps"] == 24 and m["base"]["lead_in_s"] == 0.0
    assert (m["base"]["video_cfg"], m["base"]["audio_cfg"]) == (1.0, 1.0)
    assert m["fallback"]["when_lse_c_below"] == 4.5 == L.LATENTSYNC_FALLBACK_LSE_C
    assert m["fallback"]["backend"] == "latentsync" and m["fallback"]["steps"] == 50
    assert m["post"]["runner"].endswith("runners/ls_inner_mouth.py") and m["post"]["settings"] == "L1c2"
    assert m["post"]["tool_commit"] == "a410367"


@pytest.mark.parametrize("c,want", [(4.49, True), (4.5, False), (6.12, False), (0.68, True), (None, False)])
def test_fallback_threshold_is_4_5(c, want):
    assert L.needs_latentsync_fallback(c) is want


class FakeRunner:
    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def score(self, take):
        self.calls.append(("score", take))
        return self.scores.get(take)

    def latentsync(self, take):
        self.calls.append(("latentsync", take))
        return take + "+ls"

    def inner_mouth(self, take):
        self.calls.append(("inner_mouth", take))
        return take + "+im"

    def run(self, take="artic"):
        return L.run_rebuilt_method(take, self.score, self.latentsync, self.inner_mouth)


def test_good_artic_take_skips_latentsync_and_gets_the_inner_mouth_pass():
    r = FakeRunner({"artic": 6.12})
    out = r.run()
    assert out["take"] == "artic+im" and out["method"] == "ltx_a2v_artic" and not out["fallback_ran"]
    assert ("latentsync", "artic") not in r.calls and r.calls[-1] == ("inner_mouth", "artic")


def test_weak_artic_take_runs_latentsync_and_keeps_the_better_one():
    r = FakeRunner({"artic": 2.97, "artic+ls": 6.64})
    out = r.run()
    assert out["fallback_ran"] and out["method"] == "latentsync" and out["take"] == "artic+ls+im"
    assert out["lse_c"] == 6.64 and out["lse_c_artic"] == 2.97


def test_weak_artic_take_kept_when_latentsync_scores_lower():
    r = FakeRunner({"artic": 4.0, "artic+ls": 3.5})
    out = r.run()
    assert out["fallback_ran"] and out["method"] == "ltx_a2v_artic" and out["take"] == "artic+im"
    assert [c[0] for c in r.calls] == ["score", "latentsync", "score", "inner_mouth"]


def test_exactly_at_threshold_no_fallback():
    out = FakeRunner({"artic": 4.5}).run()
    assert not out["fallback_ran"] and out["take"] == "artic+im"


def test_storyboard_reads_the_speakers_pronoun_from_their_pack(monkeypatch, tmp_path):
    from app import storyboard_api as api

    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "pack.json").write_text(json.dumps({"name": "Ava", "meta": {"pronoun": "she/her"}}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "pack.json").write_text(json.dumps({"name": "Bo", "meta": {}}))
    packs = {"ava": {"pack_dir": str(tmp_path / "a")}, "bo": {"pack_dir": str(tmp_path / "b")}}
    monkeypatch.setattr(api, "_resolve_pack", lambda name, packs_=None: packs.get(name.lower()))
    assert api._speaker_pronoun("Ava") == "she"
    assert api._speaker_pronoun("Bo") == "they"
    assert api._speaker_pronoun("Nobody") == "they" and api._speaker_pronoun("") == "they"


# ---------------------------------------------------------------- shot-plan route (opensoul/presets.build_shot_plan)
def _plan_prompt(**kw):
    from opensoul.presets import build_shot_plan

    plan = build_shot_plan(camera="static", quality="final", **kw)
    return next(s for s in plan["stages"] if s["stage"] == "video")["inputs"]


def test_shot_plan_with_a_line_gets_the_articulation_in_the_speakers_pronoun():
    from opensoul.presets import NODE_TEXT

    ins = _plan_prompt(line="Whole milk.", character_prompt="Lumi, small natural mouth movements", pronoun="she")
    text = ins[L.N_PROMPT]["text"] if L.N_PROMPT in ins else ins[NODE_TEXT]["text"]
    assert SHE in text and text.count(L.ARTICULATION_MARK) == 1
    assert "clear natural mouth movements" in text and "small natural mouth movements" not in text
    assert ins.get("34") == {"video_cfg": 1.0, "audio_cfg": 1.0}  # ltx_av: the a2v stage


def test_shot_plan_pronoun_from_pack_dir_else_they(tmp_path):
    (tmp_path / "pack.json").write_text(json.dumps({"name": "Ren", "pronoun": "he"}))
    t = json.dumps(_plan_prompt(line="Hi.", character_prompt="Ren", pack_dir=str(tmp_path)))
    assert "He speaks clearly, eyes open: his lips" in t
    t2 = json.dumps(_plan_prompt(line="Hi.", character_prompt="Someone"))
    assert "They speak clearly, eyes open: their lips" in t2


def test_shot_plan_with_an_assigned_speaker_but_no_line_gets_it_too():
    from opensoul.presets import NODE_TEXT

    ins = _plan_prompt(character_prompt="Mio at the door", speaker="Mio", pronoun="she")
    assert SHE in ins[NODE_TEXT]["text"]
    ins2 = _plan_prompt(character_prompt="Mio at the door", speaks=True)
    assert "They speak clearly" in ins2[NODE_TEXT]["text"]


def test_shot_plan_without_dialogue_or_speaker_is_unchanged():
    from opensoul.presets import NODE_TEXT

    ins = _plan_prompt(character_prompt="Lumi doodles, small natural mouth movements", pronoun="she")
    text = ins[NODE_TEXT]["text"]
    assert L.ARTICULATION_MARK not in text and "small natural mouth movements" in text
    assert "speaks clearly" not in text and "34" not in ins


# ---------------------------------------------------------------- repo demo characters
@pytest.mark.parametrize("path,want", [("assets/demo_samples/lumi_pack/pack.json", "she"),
                                       ("assets/lumi/character.json", "she"), ("assets/mio/character.json", "she"),
                                       ("assets/ren/character.json", "he"), ("assets/demo_samples/pixel_pack/pack.json", "they")])
def test_repo_demo_characters_pronouns(path, want):
    f = ROOT / path
    if not f.is_file():  # lumi_pack is export-ignored: not in a release tree
        pytest.skip(f"{path} not in this tree")
    assert L.pronoun_from_meta(json.loads(f.read_text())) == want


# ---------------------------------------------------------------- the scorer is run_rebuilt_method's default
def test_run_rebuilt_method_uses_the_configured_scorer_by_default(monkeypatch):
    from opensoul import lipsync_scorer as S

    seen = {}

    def fake_scorer(ref=None, cfg=None):
        seen["ref"] = ref
        return lambda take: {"artic": 6.0}.get(take)

    monkeypatch.setattr(S, "scorer", fake_scorer)
    out = L.run_rebuilt_method("artic", run_latentsync=lambda t: t + "+ls", run_inner_mouth=lambda t: t + "+im",
                               ref="raw.mp4")
    assert out["take"] == "artic+im" and seen["ref"] == "raw.mp4"


def test_run_rebuilt_method_without_a_scorer_says_it_isnt_set_up(monkeypatch):
    from opensoul import lipsync_scorer as S

    for k in (S.ENV_CLI, S.ENV_PY, S.ENV_TIMEOUT):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(S.ScorerError) as e:
        L.run_rebuilt_method("artic", run_latentsync=lambda t: t, run_inner_mouth=lambda t: t)
    assert e.value.code == "not_configured"


def test_unscored_artic_take_is_flagged_not_sent_to_latentsync():
    r = FakeRunner({})                                        # score() -> None (no face / no result)
    out = r.run()
    assert out["take"] == "artic+im" and out["scorer_failed"] and out["flag"] and not out["fallback_ran"]
    assert [c[0] for c in r.calls] == ["score", "inner_mouth"]
    good = FakeRunner({"artic": 6.12}).run()
    assert good["scorer_failed"] is False and good["flag"] is None


def test_unscorable_latentsync_take_never_wins():
    from opensoul.lipsync_scorer import ScorerError

    def score(t):
        if t == "artic":
            return 2.0
        raise ScorerError("no_face", "no face")
    out = L.run_rebuilt_method("artic", score, lambda t: t + "+ls", lambda t: t + "+im")
    assert out["fallback_ran"] and out["take"] == "artic+im" and out["lse_c_latentsync"] is None


def test_inner_mouth_pass_uses_auto_face_style_for_stylised_characters():
    args = L.rebuilt_method()["post"]["args"]
    assert args[args.index("--face-style") + 1] == "auto" and "--lip-color-fix" in args


def test_oom_message_says_your_computer():
    msg = L.LipSyncError.MESSAGES["oom"]
    assert "studio computer" not in msg and "Your computer" in msg


# ---------------------------------------------------------------- soft wording (G2nd), full sentence per pronoun
SOFT = {
    "she": "She speaks clearly, eyes open: her lips open and close on every syllable, teeth visible on open vowels, calm neutral expression.",
    "he": "He speaks clearly, eyes open: his lips open and close on every syllable, teeth visible on open vowels, calm neutral expression.",
    "they": "They speak clearly, eyes open: their lips open and close on every syllable, teeth visible on open vowels, calm neutral expression.",
}


@pytest.mark.parametrize("pronoun,key", [("she", "she"), ("he", "he"), ("they", "they"), (None, "they")])
def test_soft_sentence_in_speaker_prompt_and_shot_plan(pronoun, key):
    from opensoul.presets import NODE_TEXT

    p = L.speaker_prompt("Lumi at the till", "Lumi", "Whole milk.", pronoun)
    assert SOFT[key] in p and p.count(L.ARTICULATION_MARK) == 1 and "jaw moving" not in p
    ins = _plan_prompt(character_prompt="Lumi at the till", speaker="Lumi", pronoun=pronoun)
    text = ins[L.N_PROMPT]["text"] if L.N_PROMPT in ins else ins[NODE_TEXT]["text"]
    assert SOFT[key] in text and "jaw moving" not in text
    if key == "they":
        assert "They speaks" not in p and "They speak clearly" in p
