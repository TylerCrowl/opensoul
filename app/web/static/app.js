(() => {
  let DEMO_NAME = "Lumi";  // the main bundled demo character (from /api/bootstrap); Pixel is the second one
  const STATIC_ID = "static";
  const state = {
    step: 1,
    packDir: "",
    isDemo: false,
    demo: null,
    sheetUrl: null,
    sheetMade: false,
    dirty: false,
    busy: false,
    presets: null,
    camera: STATIC_ID,
    effect: null,
    era: "iphone_ugc",
    voice: null,
    result: null,
    look: { still: null, sheet: null, source: null, library: null },
    sessionStill: null,  // full-body front view of a sheet made in this session
    noLibrary: false,    // user chose "Start fresh" over a saved character with the same name
    savedName: "",
    cmode: "describe",  // step 1: "describe" (words only, text-only master) | "photo"
    master: null,       // { id, url, seed, label, prompt_lock, saved } from POST /api/master (a background job)
    options: null,      // "Make N options": { id, items: [{seed, url}], sig, prompt_lock, chosen } until one is picked
    masterBatch: 4,     // N (presets/text_master.json master_batch, from /api/bootstrap)
    masters: [],        // earlier masters this session (click one to go back)
    masterJob: null,    // master_id while a master is drawing (Stop cancels it)
    savedLook: null,    // the saved character's Look as filled in (a big change is a new look)
    stopped: null,      // { seed } after Stop: the header says which master is showing
  };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const charName = () => $("name").value.trim().replace(/\s+/g, " ") || "My character";
  // Same rule as opensoul/text_master.py compose(): look, age words, "wearing <outfit>", style words.
  const AGE_WORDS = { "18-25": "in their early twenties", "26-35": "in their late twenties to early thirties",
    "36-50": "in their late thirties to forties", "51-65": "in their fifties to early sixties", "65+": "in their late sixties or older" };
  const STYLE_WORDS = { natural: "natural photo look", cinematic: "cinematic film-still look, soft contrast", editorial: "soft editorial portrait look" };
  const clean = (v) => String(v || "").replace(/\s+/g, " ").trim().replace(/^[ ,.]+|[ ,.]+$/g, "");
  function composeLook() {
    const outfit = clean($("mOutfit").value);
    return [clean($("prompt").value), AGE_WORDS[$("mAge").value] || "", outfit ? `wearing ${outfit}` : "", STYLE_WORDS[$("mStyle").value] || ""]
      .filter(Boolean).join(", ");
  }
  const description = () => {
    if (state.cmode === "describe") return composeLook();
    const outfit = clean($("mOutfit").value);  // "Start from a photo": Look and Outfit, same words as Describe
    return [clean($("prompt").value), outfit ? `wearing ${outfit}` : ""].filter(Boolean).join(", ");
  };
  const hasPhoto = () => $("photos").files.length > 0;

  function setStep(n) {
    state.step = n;
    document.querySelectorAll(".step-chip").forEach((el) => {
      const on = Number(el.dataset.step) === n;
      el.classList.toggle("active", on);
      el.setAttribute("aria-current", on ? "step" : "false");
    });
    document.querySelectorAll(".panel").forEach((el) => el.classList.toggle("active", Number(el.dataset.step) === n));
    const url = new URL(location.href);
    url.searchParams.set("step", String(n));
    history.replaceState(null, "", url);
  }

  function setTab(tab) {
    document.querySelectorAll(".seg[data-tab]").forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("active", p.dataset.pane === tab));
  }

  // ---------- Character preview: always the *current* character ----------
  function nameCard(name, line) {
    return `<div class="name-card"><svg viewBox="0 0 40 72" aria-hidden="true"><use href="#i-subject"/></svg>
      <strong>${esc(name)}</strong><span>${esc(line)}</span></div>`;
  }

  /** The current character's own still (never the demo's), or null. */
  function charStill() {
    if (state.isDemo) return null;
    return state.sessionStill || state.look.still || null;
  }

  /** "Option 2 · #34": the tile's place in the grid and its variation number (what Variation # reads after Use this one). */
  function optionName(o, seed) {
    return `Option ${o.items.findIndex((x) => x.seed === seed) + 1} · #${seed}`;
  }

  function renderCharPreview() {
    const box = $("sheetPreview");
    const name = charName();
    const fromLibrary = state.look.source === "library";
    box.classList.remove("portrait");
    box.classList.remove("options");
    if (state.options && !state.isDemo) {
      // one grid, one button: tap a picture, then Use this one (the others stay with the character)
      box.classList.add("options");
      const o = state.options;
      box.innerHTML = `<div class="option-grid" role="radiogroup" aria-label="Master options">${o.items.map((x) =>
        `<button type="button" class="option-tile${o.chosen === x.seed ? " on" : ""}" role="radio" aria-checked="${o.chosen === x.seed}" data-option="${x.seed}" aria-label="${optionName(o, x.seed)}"><img src="${esc(x.url)}" alt="" /><span class="option-check" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" /></svg></span><span class="option-cap">${optionName(o, x.seed)}</span></button>`).join("")}</div>
        <div class="option-actions"><button class="btn btn-primary" id="btnUseOption" type="button"${o.chosen === null ? " disabled" : ""}>Use this one</button>
        <button class="btn-link" id="btnCancelOptions" type="button">Cancel</button></div>`;
      // once a tile is picked its own label ("Option 3 · #35") says which: no second caption under the grid
      $("sheetLabel").textContent = o.chosen === null ? `Pick the one that looks most like ${name}.` : "";
    } else if (state.master && !state.isDemo && !state.sheetUrl) {
      box.classList.add("portrait");
      box.innerHTML = `<img src="${esc(state.master.url)}" alt="Master picture of ${esc(name)}" />`;
      $("sheetLabel").textContent = state.master.label;
    } else if (state.sheetUrl) {
      box.innerHTML = `<img src="${esc(state.sheetUrl)}" alt="Character sheet of ${esc(name)}" />`;
      $("sheetLabel").textContent = state.isDemo ? "Demo character sheet" : `${name}’s character sheet`;
    } else if (!state.isDemo && state.look.sheet) {
      box.innerHTML = `<img src="${esc(state.look.sheet)}" alt="Character sheet of ${esc(name)}" />`;
      $("sheetLabel").textContent = state.look.placeholder ? `Placeholder: we are rebuilding ${name}` : `${name}’s character sheet${fromLibrary ? " (saved character)" : ""}`;
    } else if (charStill()) {
      box.classList.add("portrait");
      box.innerHTML = `<img src="${esc(charStill())}" alt="Reference picture of ${esc(name)}" />`;
      $("sheetLabel").textContent = state.look.placeholder && !state.sessionStill ? `Placeholder: we are rebuilding ${name}`
        : `${name}’s reference picture${fromLibrary ? " (saved character)" : ""}. Make a character sheet for six locked angles.`;
    } else if (!$("name").value.trim() && !description()) {
      box.innerHTML = '<div class="empty">Your character sheet appears here</div>';
      $("sheetLabel").textContent = "";
    } else {
      box.innerHTML = nameCard(name, "No character sheet yet");
      $("sheetLabel").textContent = "Placeholder until you make a character sheet.";
    }
    const typed = $("name").value.trim();
    $("charHeading").textContent = state.isDemo ? "Demo character" : (typed || "New character");
    $("charIntro").innerHTML = introHTML(typed);
    fitMasterProgress();
    $("demoLegal").hidden = !state.isDemo;
    fitPreview(box);
  }

  /** A wide sheet (e.g. the 16:9 demo sheet) fills the frame's width instead of floating small in a tall grey box. */
  function fitPreview(box) {
    box.classList.remove("wide");
    const img = box.querySelector("img");
    if (!img) return;
    const fit = () => box.classList.toggle("wide", img.naturalWidth > img.naturalHeight * 1.15);
    if (img.complete && img.naturalWidth) fit(); else img.addEventListener("load", fit, { once: true });
  }

  /** Step 1 intro that reads naturally for each state (empty, named, master, sheet ready, demo). Only says "six
   * angles" once a sheet exists, and never shows a saved character's state for a new master under the same name. */
  function introHTML(typed) {
    const who = esc(typed || "your character");
    if (!$("masterProgress").hidden) return `Drawing ${esc(charName())}’s master…`;
    if (state.isDemo) return `${esc(demoName())} is ready. Continue to <strong>Choose a shot</strong>, or make your own character with a new name and description.`;
    const fresh = state.noLibrary || !!state.master || bigLookChange();  // a new look under this name: ignore the saved sheet
    if (state.sheetMade) return `<strong>${who} is ready.</strong> Next, choose a shot.`;
    if (state.look.placeholder && !fresh && (state.look.sheet || charStill()))  // an old design, hidden until the rebuild
      return `OpenSoul added <strong>${who}</strong>’s saved description. Their picture is a placeholder until we rebuild ${who}.`;
    if (state.look.library && !fresh && state.cmode === "describe" && (state.look.sheet || charStill()))
      return `<strong>${who}</strong> is ready for a shot.`;
    if (state.look.sheet && !fresh) return `<strong>${who} is ready.</strong> Next, choose a shot.`;
    if (state.stopped) return state.stopped.seed !== null
      ? `Stopped. Showing your last master (seed ${state.stopped.seed}).`
      : "Stopped. OpenSoul did not make a master. Your description is still here.";
    if (needsMaster() && state.master && state.master.url) return `You changed ${who}’s description. Click <strong>1 · ${makeOptions()}</strong> to make it again.`;
    if (state.master && state.master.url) return `${who}’s master is ready. Click <strong>2 · Make character sheet</strong> for six matching angles, or <strong>Try another</strong>.`;
    if (state.cmode === "photo") {
      if (charStill()) return `${who}’s picture is ready. Click <strong>Make character sheet</strong> to lock the look from six angles. Or go to <strong>Choose a shot</strong>.`;
      return `Add a photo of your own original character. Describe their look and outfit. Then click <strong>Make character sheet</strong>.`;
    }
    if (typed || description()) return `Describe how ${who} looks. Then click <strong>1 · ${makeOptions()}</strong>. No photo needed.`;
    return `Give your character a name. Describe how they look. Then click <strong>1 · ${makeOptions()}</strong>. No photo needed.`;
  }

  // ---------- Tiles ----------
  function placeholder() {
    return `<div class="ph"><div class="scene"></div><div class="subj"><svg><use href="#i-subject"/></svg></div></div><span class="example-badge soon">Preview coming</span>`;
  }

  function tileLabel(p) { return p.id === STATIC_ID ? "None / static" : p.label; }

  /** Tile media: the current character moving the way the preset does (CSS preview of the move);
   *  the demo's rendered sample clip only when there is no character picture (labelled Example);
   *  a grey "Preview coming" placeholder when neither exists. */
  const isMainDemo = () => state.isDemo && demoName().toLowerCase() === DEMO_NAME.toLowerCase();

  function tileMedia(p) {
    const still = charStill();
    if (still) {
      return `<span class="move-preview mv-${esc(p.id)}"><img src="${esc(still)}" alt="" loading="lazy" /></span>
        <span class="example-badge you">${esc(charName())}</span>`;
    }
    if (p.thumb_ready) {
      // The example clips are of the main demo; say so whenever someone else is starring.
      const badge = isMainDemo() ? "" : `<span class="example-badge" title="This preview clip shows ${esc(DEMO_NAME)}; your shot uses your character">Shows ${esc(DEMO_NAME)}</span>`;
      return `<video src="${esc(p.thumbnail)}" autoplay muted loop playsinline preload="metadata"></video>${badge}`;
    }
    return placeholder();
  }

  function renderTileMedia() {
    if (!state.presets) return;
    const all = [...state.presets.camera, ...state.presets.effects];
    document.querySelectorAll(".tile").forEach((t) => {
      const p = all.find((x) => x.id === t.dataset.id);
      const media = t.querySelector(".media");
      if (!p || !media) return;
      media.innerHTML = tileMedia(p);
      const v = media.querySelector("video");
      if (v) v.addEventListener("error", () => { media.innerHTML = placeholder(); }, { once: true });
    });
    renderStarring();
  }

  /** "Starring" chip on the Shot step: who is in the shot, at a glance. */
  function renderStarring() {
    // The second demo (Pixel) shows its own picture, never the main demo's poster.
    const demoPic = isMainDemo() ? (state.demo?.card_url || state.demoPoster || state.demo?.sheet_url) : state.sheetUrl;
    const still = charStill() || (state.isDemo ? demoPic : null);
    $("starring").innerHTML = `${still ? `<img src="${esc(still)}" alt="" />` : `<svg viewBox="0 0 40 72" aria-hidden="true"><use href="#i-subject"/></svg>`}
      <span>Starring <strong>${esc(state.isDemo ? demoName() : charName())}</strong></span>`;
  }

  function tileHTML(p, kind) {
    const blurb = p.id === STATIC_ID ? "No camera move. Holds still." : p.blurb;
    return `<button type="button" class="tile m-${esc(p.id)}" role="radio" aria-checked="false" data-kind="${kind}" data-id="${esc(p.id)}">
      <span class="frame"><span class="media"></span><span class="picked" aria-hidden="true">✓ Selected</span>${window.OpenSoulTiles ? window.OpenSoulTiles.tag(p) + window.OpenSoulTiles.glyph(p) : ""}</span>
      <span class="name">${esc(tileLabel(p))}</span>
      <span class="blurb">${esc(blurb)}</span>
    </button>`;
  }

  function renderTiles() {
    // "None / static" first, so "no move" is an explicit, obvious choice.
    const cams = [...state.presets.camera].sort((a, b) => (a.id === STATIC_ID ? -1 : b.id === STATIC_ID ? 1 : 0));
    $("cameraTiles").innerHTML = cams.map((p) => tileHTML(p, "camera")).join("");
    $("effectTiles").innerHTML = state.presets.effects.map((p) => tileHTML(p, "effect")).join("");
    renderTileMedia();
    document.querySelectorAll(".tile").forEach((t) => {
      t.addEventListener("click", () => {
        const { kind, id } = t.dataset;
        // Effects replace the camera move (matches build_shot_plan: the effect drives the shot).
        if (kind === "camera") { state.camera = id; state.effect = null; }
        else if (state.effect === id) { state.effect = null; state.camera = STATIC_ID; }
        else { state.effect = id; state.camera = null; }
        syncSelection();
      });
    });
    $("voiceChips").innerHTML = state.presets.voices
      .map((v) => `<button type="button" class="chip" role="radio" aria-checked="false" data-voice="${esc(v.id)}">${esc(v.label)}</button>`).join("");
    $("voiceChips").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { state.voice = c.dataset.voice; syncSelection(); }));
    $("eraToggle").innerHTML = state.presets.eras
      .map((e) => `<button type="button" role="radio" aria-checked="false" data-era="${esc(e.id)}">${esc(e.label)}</button>`).join("");
    $("eraToggle").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state.era = b.dataset.era; syncSelection(); }));
    if (!state.voice) state.voice = state.presets.voices[0]?.id;
  }

  function findPreset(list, id) { return list.find((p) => p.id === id); }

  function current() {
    return state.effect ? findPreset(state.presets.effects, state.effect) : findPreset(state.presets.camera, state.camera || STATIC_ID);
  }

  function summaryText() {
    const line = $("line").value.trim();
    const era = findPreset(state.presets.eras, state.era);
    const voice = findPreset(state.presets.voices, state.voice);
    const parts = [];
    if (state.effect) parts.push(`<strong>${esc(findPreset(state.presets.effects, state.effect)?.label || state.effect)}</strong> effect (no camera move)`);
    else parts.push(`<strong>${esc(tileLabel(findPreset(state.presets.camera, state.camera || STATIC_ID) || { id: STATIC_ID }))}</strong> camera`);
    if (era) parts.push(esc(era.label));
    parts.push(line ? `with voice${voice ? ` (${esc(voice.label)})` : ""}` : "no voice");
    return parts.join(" · ");
  }

  function syncSelection() {
    document.querySelectorAll(".tile").forEach((t) => {
      const on = (t.dataset.kind === "camera" && t.dataset.id === state.camera) || (t.dataset.kind === "effect" && t.dataset.id === state.effect);
      t.setAttribute("aria-checked", String(on));
    });
    document.querySelectorAll("#voiceChips .chip").forEach((c) => c.setAttribute("aria-checked", String(c.dataset.voice === state.voice)));
    document.querySelectorAll("#eraToggle button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.era === state.era)));
    // Tab labels show what is picked in each, so the summary never surprises.
    document.querySelector('.seg[data-tab="camera"]').textContent = state.effect ? "Camera moves" : `Camera moves · ${tileLabel(current() || { id: STATIC_ID })}`;
    document.querySelector('.seg[data-tab="effects"]').textContent = state.effect ? `Viral effects · ${current()?.label || ""}` : "Viral effects";
    document.querySelector('.seg[data-tab="speak"]').textContent = $("line").value.trim() ? "Speak · on" : "Speak";
    $("shotSummary").innerHTML = summaryText();
    const p = current();
    if (p) {
      $("advDuration").value = p.defaults.duration_s;
      $("advSteps").value = p.defaults.steps;
      $("advCfg").value = p.defaults.cfg;
    }
  }

  // ---------- Character ----------
  function applyCharacter(c, { demo }) {
    state.isDemo = demo;
    state.packDir = c.pack_dir || "";
    state.sheetUrl = c.sheet_url || null;
    state.sheetMade = demo && !!c.sheet_url;
    state.sessionStill = null;
    state.noLibrary = false;
    state.look = { still: null, sheet: null, source: null, library: null };
    state.savedName = c.name || "";
    $("name").value = c.name || "";
    $("prompt").value = c.prompt_lock || "";
    $("mOutfit").value = ""; $("mAge").value = ""; $("mStyle").value = "";
    closeOptions();
    state.master = null; state.masters = []; state.stopped = null;
    syncMasterButtons(); renderMasterRow();
    clearPhotos();
    state.dirty = false;
    $("sheetDownload").hidden = true;
    $("sheetProgress").hidden = true;
    $("charStatus").textContent = demo ? (c.status || "") : "";
    resetResult();
    renderCharPreview();
    syncSheetButton();
    refreshLook();
  }

  let lookTimer = null;
  let lookSeq = 0;
  function refreshLookSoon() { clearTimeout(lookTimer); lookTimer = setTimeout(refreshLook, 300); }

  /** Ask the server for the current character's own pictures (its pack, then its saved-character folder). */
  async function refreshLook() {
    const seq = ++lookSeq;
    const typed = $("name").value.trim();
    if (state.isDemo || (!typed && !state.packDir)) {
      state.look = { still: null, sheet: null, source: null, library: null };
    } else {
      const q = new URLSearchParams({ name: typed, pack_dir: state.packDir || "", library: state.noLibrary ? "0" : "1" });
      try {
        const res = await fetch(`/api/look?${q}`);
        if (!res.ok || seq !== lookSeq) return;
        const d = await res.json();
        state.look = { still: d.still_url, sheet: d.sheet_url, source: d.source, library: d.library, placeholder: !!d.placeholder };
      } catch { return; }
      // Auto-fill a saved character's description when the user hasn't typed one: Look and Outfit separately when
      // they were saved that way; an older character's whole description goes in Look (Outfit: "Included above").
      const lib = state.look.library;
      const f = lib && lib.fields;
      state.savedLook = lib ? ((f && f.look) || lib.prompt_lock || "") : null;
      if (lib && !state.noLibrary && !description() && (f || lib.prompt_lock)) {
        $("prompt").value = f ? f.look : lib.prompt_lock;
        if (f) {
          $("mOutfit").value = f.outfit || "";
          if (f.age) $("mAge").value = f.age;
          if (f.style) $("mStyle").value = f.style;
        }
        state.savedLook = $("prompt").value;
        state.dirty = true;
      }
      // an older saved character keeps its outfit inside the Look; once the Look is edited, Outfit is its own field again
      $("mOutfit").placeholder = lib && !f && !state.noLibrary && clean($("prompt").value) === clean(lib.prompt_lock) ? "Included above" : OUTFIT_HINT;
      loadCharVoice(lib && !state.noLibrary ? lib.name || typed : "");
      $("libraryNote").hidden = !(state.look.source === "library");
      if (state.look.source === "library") $("libraryName").textContent = lib?.name || typed;
      $("libraryUsing").textContent = state.look.placeholder ? "description; picture is a placeholder" : "picture and description";
      const vars = (state.look.source === "library" && lib?.variants) || [];
      $("libraryVariants").textContent = vars.length ? ` Using the main version; ${vars.length} other saved version${vars.length > 1 ? "s" : ""} of this name.` : "";
    }
    if (state.isDemo || !state.look.library) $("libraryNote").hidden = true;
    syncNewLookNote();
    renderCharPreview();
    renderTileMedia();
    syncSheetButton();
  }

  // Create: a visible picker for characters you already have (saved library folders + ones made in the app).
  // OS-049: a saved character's voice, on the character itself (used for every line they speak).
  const VOICE_HINT = "This character speaks with this voice in every shot.";
  async function loadCharVoice(name) {
    const box = $("voiceField");
    box.hidden = !name;
    box.dataset.name = name || "";
    if (!name) return;
    try {
      const d = await (await fetch(`/api/voices?name=${encodeURIComponent(name)}`)).json();
      if (box.dataset.name !== name) return;
      $("charVoice").innerHTML = d.voices.map((v) => `<option value="${v.id}" ${v.id === d.character_voice ? "selected" : ""} ${v.available ? "" : "disabled"}>` +
        `${v.label} · ${v.gender === "male" ? "man" : "woman"}, ${v.blurb}${v.available ? "" : " (not on your studio)"}</option>`).join("");
      $("charVoiceHint").textContent = VOICE_HINT;
    } catch { box.hidden = true; }
  }
  async function saveCharVoice() {
    const name = $("voiceField").dataset.name, sel = $("charVoice");
    if (!name) return;
    try {
      const r = await fetch(`/api/storyboard/cast/${encodeURIComponent(name)}/voice`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voice: sel.value }) });
      const d = await r.json();
      $("charVoiceHint").textContent = r.ok ? `${name} now speaks with ${sel.options[sel.selectedIndex].text.split(" · ")[0]} in every shot.` : (d.detail || "Couldn't save the voice.");
    } catch { $("charVoiceHint").textContent = "Couldn't save the voice. Try again."; }
  }
  async function playVoiceSample() {
    const btn = $("btnVoiceSample");
    btn.disabled = true; btn.textContent = "Making the sample…";
    try {
      const r = await fetch("/api/voices/sample", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voice: $("charVoice").value }) });
      const d = await r.json();
      if (!r.ok) { $("charVoiceHint").textContent = d.detail || "Couldn't make the sample."; return; }
      const au = $("voiceSampleAudio");
      au.src = d.audio_url; au.play().catch(() => {});
      if (d.placeholder) $("charVoiceHint").textContent = "Preview mode plays a tone. Studio mode plays the real voice.";
    } finally { btn.disabled = false; btn.textContent = "Play a sample"; }
  }
  async function loadCharPick() {
    let cast = [];
    try { cast = (await (await fetch("/api/storyboard/cast")).json()).cast || []; } catch { cast = []; }
    state.myCast = cast;
    renderCharPick();
  }

  function renderCharPick() {
    const cast = state.myCast || [];
    $("charPick").hidden = !cast.length;
    const typed = $("name").value.trim().toLowerCase();
    $("charPickList").innerHTML = cast.map((c) => {
      const pic = c.picture_url ? `<img src="${esc(c.card_url || c.picture_url)}" alt="" />` : `<span class="ini">${esc((c.name || "?").slice(0, 1).toUpperCase())}</span>`;
      const on = !state.isDemo && typed === c.name.toLowerCase();
      return `<button type="button" class="pick" data-name="${esc(c.name)}" aria-pressed="${on}">${pic}${esc(c.name)}</button>`;
    }).join("");
    $("charPickList").querySelectorAll(".pick").forEach((b) => b.addEventListener("click", () => pickCharacter(b.dataset.name)));
  }

  function pickCharacter(name) {
    $("name").value = name;
    state.isDemo = false;
    state.packDir = "";
    state.sheetUrl = null;
    state.sheetMade = false;
    state.savedName = "";
    state.noLibrary = false;
    $("prompt").value = "";  // the picked character's own description fills in from the lookup
    $("sheetDownload").hidden = true;
    onCharacterEdited();
    renderCharPick();
  }

  const OUTFIT_HINT = "e.g. green apron over a cream sweater";
  const lookWords = (s) => new Set(clean(s).toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2));
  /** The Look under a saved name now says something quite different (under half the words shared). */
  function bigLookChange() {
    const lib = state.look && state.look.library;
    if (!lib || state.noLibrary || state.isDemo || !state.savedLook) return false;
    const a = lookWords(state.savedLook), b = lookWords($("prompt").value);
    if (!b.size) return false;
    let same = 0;
    b.forEach((w) => { if (a.has(w)) same += 1; });
    return same / Math.max(a.size, b.size) < 0.5;
  }
  function syncNewLookNote() {
    const big = bigLookChange();
    $("newLookNote").hidden = !big;
    if (!big) return;
    const n = state.look.library.name || charName();
    $("newLookText").textContent = `New look for ${n}; your saved ${n} stays.`;
    $("libraryNote").hidden = true;
  }
  function renameNewLook() {
    const v = $("newLookName").value.trim().replace(/\s+/g, " ");
    if (!v) { $("newLookName").focus(); return; }
    $("name").value = v;
    $("newLookName").value = "";
    onCharacterEdited({ target: $("name") });
    renderCharPick();
  }

  function startFresh() {
    state.noLibrary = true;
    state.packDir = state.sheetMade ? state.packDir : "";
    $("prompt").value = "";
    $("mOutfit").placeholder = OUTFIT_HINT;
    $("libraryNote").hidden = true;
    $("charStatus").textContent = "New version: describe your character. Then click Make character sheet.";
    refreshLook();
  }

  async function loadBootstrap() {
    const data = await (await fetch("/api/bootstrap")).json();
    state.demo = data.character;
    if (data.character && data.character.name) DEMO_NAME = data.character.name;
    state.demos = data.demos || [];
    state.demoPoster = data.video?.poster_url || null;
    state.bootVersion = data.version;
    state.dryRun = !!data.dry_run;
    state.masterBatch = Math.max(2, Math.min(8, Number(data.master_batch) || 4));
    if ($("btnMasterOptions")) $("btnMasterOptions").textContent = `1 · ${makeOptions()}`;
    syncExportLabel(state.dryRun);
    syncDemoButtons();
    return data;
  }

  // Advanced → engine pickers: only installed options are listed (from the model registry).
  async function loadBackends() {
    try {
      const data = await (await fetch("/api/backends")).json();
      let shown = 0;
      for (const row of data.stages || []) {
        const sel = document.querySelector(`#backendPickers select[data-stage="${row.stage}"]`);
        if (!sel) continue;
        sel.innerHTML = (row.options || []).map((o) =>
          `<option value="${esc(o.id)}"${o.id === row.default ? " selected" : ""}>${esc(o.label)}${o.available ? "" : " (not installed)"}</option>`).join("");
        sel.disabled = (row.options || []).length < 2;
        sel.title = sel.disabled ? "Only one engine is installed for this step." : "";
        shown++;
      }
      $("backendPickers").hidden = shown === 0;
    } catch (_) {
      $("backendPickers").hidden = true;
    }
  }

  const demoName = () => state.demoName || DEMO_NAME;
  // A release archive leaves the Lumi sample pack out (opensoul/export_guard.py DERIVED_DIRS): only the demos the server
  // lists (bootstrap.demos) are offered, so a missing sample is hidden, never an empty character.
  const hasDemo = (n) => (state.demos || []).some((d) => d.name.toLowerCase() === String(n || "").toLowerCase());
  function syncDemoButtons() {
    const main = hasDemo(DEMO_NAME), pixel = hasDemo("Pixel");
    $("btnLoadDemo").hidden = !main;
    const b2 = $("btnLoadDemo2");
    if (b2) { b2.hidden = !pixel; b2.textContent = main ? "or try Pixel" : "Try the demo character (Pixel)"; }
    const wrap = document.querySelector(".demo-pick");
    if (wrap) wrap.hidden = !main && !pixel;
  }
  function loadDemo(which) {
    if (!state.demo) return;
    let want = typeof which === "string" ? which : DEMO_NAME;
    if (!hasDemo(want)) {
      const first = (state.demos || [])[0];
      if (!first) { newCharacter(); return; }
      want = first.name;
    }
    const alt = (state.demos || []).find((d) => d.name.toLowerCase() === want.toLowerCase());
    const pick = !alt || alt.name.toLowerCase() === (state.demo.name || DEMO_NAME).toLowerCase()
      ? { ...state.demo, name: state.demo.name || DEMO_NAME }
      : { ...state.demo, ...alt, status: `${alt.name} (demo character) is ready. You can edit the description or continue.` };
    state.demoName = pick.name;
    applyCharacter(pick, { demo: true });
    setCharMode("describe");  // the judge demo opens on the Describe path too
  }

  function newCharacter(boot) {
    applyCharacter(boot?.new_character || { name: "", prompt_lock: "", status: "" }, { demo: false });
    setCharMode("describe");  // first run and every new character start on Describe (words first, photo optional)
    // OS-047: a new character starts from a new roll, not from the seed of the last character
    if (!boot) { $("mSeed").value = String(Math.floor(Math.random() * 1000000)); $("mSeedNote").hidden = true; }
  }

  function onCharacterEdited(e) {
    if (e && e.target && e.target.id === "mSeed") {  // just the next number; with the grid open, typing an option's seed selects it
      $("mSeedNote").hidden = true;
      if (state.options) {
        const v = Number($("mSeed").value), hit = state.options.items.find((x) => x.seed === v);
        state.options.chosen = hit ? hit.seed : null;
        renderCharPreview(); syncSheetButton();
      }
      return;
    }
    state.stopped = null;
    if (state.options && e && e.target && e.target.id !== "name") { closeOptions(); renderCharPreview(); }  // options for old words
    if (state.master && !state.master.saved && e && e.target && e.target.id !== "name") {
      closeOptions(); state.master = null; state.masters = [];  // the words changed: the shown masters no longer match them
      syncMasterButtons(); renderMasterRow();
    }
    const renamedDemo = state.isDemo && $("name").value.trim().toLowerCase() !== demoName().toLowerCase();
    if (renamedDemo) {
      // Auto-correct: a renamed demo is a new character, so it must not keep the demo's pictures.
      state.isDemo = false;
      state.packDir = "";
      state.sheetUrl = null;
      state.sheetMade = false;
      $("sheetDownload").hidden = true;
      $("charStatus").textContent = "New character: OpenSoul removed the demo pictures. Make a character sheet for this one.";
      resetResult();
    }
    const typed = $("name").value.trim();
    if (!state.isDemo && !state.sheetMade && state.packDir && typed.toLowerCase() !== state.savedName.toLowerCase()) {
      state.packDir = "";  // a different name is a different character: don't show the old one's pictures
    }
    if (typed.toLowerCase() !== state.savedName.toLowerCase()) state.noLibrary = false;
    state.dirty = true;
    if (!state.busy && /^Demo character ready|^New character\./.test($("charStatus").textContent)) $("charStatus").textContent = "";
    refreshLookSoon();
    renderCharPreview();
    syncSheetButton();
  }

  function clearPhotos() {
    $("photos").value = "";
    syncPhotos();
  }

  function syncPhotos() {
    const f = $("photos").files;
    $("fileName").textContent = f.length ? Array.from(f).map((x) => x.name).join(", ") : "No photo chosen";  // the hint under the button says what to do
    $("clearPhotos").hidden = !f.length;
    $("consentRow").hidden = !f.length;
    if (!f.length) $("consent").checked = false;
    state.dirty = true;
    syncSheetButton();
  }

  /** The words the shown master was drawn from (look, outfit, age, style). */
  function masterSig() {
    return [clean($("prompt").value), clean($("mOutfit").value), $("mAge").value, $("mStyle").value].join("|");
  }
  /** Describe: the current Look has no real master yet. The picture is a pre-rebuild placeholder, or the words
   * changed since the master that's showing (or since the saved look). Step 1 comes first then, never a sheet. */
  function needsMaster() {
    if (state.cmode !== "describe" || state.isDemo || hasPhoto() || state.sheetMade || state.sessionStill) return false;
    if (state.master && state.master.url) return !!state.master.sig && state.master.sig !== masterSig();
    return !!state.look.placeholder || bigLookChange();
  }

  /** A talking shot on the default LTX audio+video path renders with workflow 04b, whose guidance is pinned at 1/1
   * (opensoul/lipsync.py GUIDER_CFG): Prompt strength has no effect there, so the field says so. */
  function syncCfgNote() {
    const talking = !!$("line").value.trim();
    const backend = $("advLipsync").value || "ltx_av";  // empty = the default engine (LTX joint audio+video)
    const unused = talking && backend === "ltx_av";
    $("advCfgNote").hidden = !unused;
    $("advCfg").disabled = unused;  // visibly greyed out; re-enabled when the line is removed or another engine is picked
    $("advCfg").title = unused ? "Not used for talking shots (except with LatentSync)" : "";
  }

  /** Why can't the user make a sheet / save right now? "" means they can. */
  function blockReason() {
    if (state.busy) return "Working on it…";
    if (hasPhoto() && !$("consent").checked) return "Select the permission box to use this photo.";
    if (state.options && state.cmode === "describe") return state.options.chosen === null
      ? "Pick one of the options. Then click Use this one." : "Click Use this one to continue.";
    if (needsMaster()) return state.master && state.master.url ? "Step 1 first: your description changed, so generate a new master."
      : "Step 1 first: generate a master from the description.";
    if (state.cmode === "photo" && !hasPhoto() && !state.isDemo) return "Add a photo to start.";
    if (hasPhoto() || state.isDemo) return "";
    if (state.cmode === "describe" && !(state.master && state.master.url) && !charStill()) return "Do step 1 first: click Make 4 options to make a master.";
    if (!description()) return "Describe your character first: a few words about their look and outfit.";
    if (description().length < 8) return "Add a few more words (hair, outfit) so the sheet knows who to draw.";
    return "";
  }

  function syncSheetButton() {
    const why = blockReason();
    $("btnSheet").disabled = !!why;
    $("btnSaveCharacter").disabled = state.busy || !!why;
    $("sheetReason").textContent = why === "Working on it…" ? "" : why;  // a calm grey hint; errors only after a click
    if (state.isDemo && state.demo && state.demo.card_placeholder && !hasPhoto()) {
      // the demo's pictures are a pre-rebuild placeholder: no new sheet from them (the server refuses too)
      $("btnSheet").disabled = true;
      $("sheetReason").textContent = "The demo is ready: its pictures are placeholders until we rebuild it.";
    }
    const done = !!state.sheetMade;
    $("btnSheet").textContent = done ? "Redo sheet" : state.cmode === "describe" ? "2 · Make character sheet" : "Make character sheet";
    // Step 1 is the next tap (no master for this Look yet): Make N options is the primary button, as while drawing.
    const step1 = !done && /^Step 1 first/.test(why);
    // filled only when it's the next tap; disabled (step 1 first, or a grid open) it's an outline, as in the fresh state
    const sheetNext = !done && !step1 && !$("btnSheet").disabled;
    $("btnSheet").classList.toggle("btn-primary", sheetNext);
    $("btnSheet").classList.toggle("btn-outline", !sheetNext);
    // Make N options is the primary step-1 button (the reliable path); the single draw is a text link beside it.
    $("btnMasterOptions").classList.toggle("btn-primary", step1);
    $("btnMasterOptions").classList.toggle("btn-outline", !step1);
    $("btnMasterOptions").classList.toggle("dim", done);
    $("btnMaster").classList.toggle("dim", done);
    // Choose a shot needs a character to put in the shot: gated like the sheet button, with the same hint
    // (the demo, or a saved character that wasn't edited, can always go on).
    const shotWhy = state.isDemo || (state.packDir && !state.dirty) ? "" : why;
    $("toStep2").disabled = !!shotWhy;
    $("toStep2").title = shotWhy === "Working on it…" ? "" : shotWhy;
    $("shotReason").textContent = shotWhy === "Working on it…" ? "" : shotWhy;  // the same small grey line as under the sheet button
    // One reason line: when the footer (next to Choose a shot) shows the same words, the one under the step buttons
    // stays empty. It still shows a reason only it has (e.g. the demo's placeholder pictures), and in the six-tab
    // shell, which has no Choose a shot footer.
    const footer = !document.body.classList.contains("ui-unified");
    if (footer && $("sheetReason").textContent && $("sheetReason").textContent === $("shotReason").textContent) $("sheetReason").textContent = "";
  }

  // ---------- Describe your character: text-only master (POST /api/master, no photo, no rights tick) ----------
  function setCharMode(mode) {
    state.cmode = mode === "photo" ? "photo" : "describe";
    document.querySelectorAll(".seg[data-cmode]").forEach((b) => {
      const on = b.dataset.cmode === state.cmode;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    $("describeFields").hidden = state.cmode !== "describe";
    $("photoField").hidden = state.cmode !== "photo";
    $("promptLabel").textContent = "Look";
    if (state.cmode === "describe") clearPhotos();
    else { closeOptions(); if (state.master && !state.master.saved) { state.master = null; state.masters = []; syncMasterButtons(); renderMasterRow(); } }
    renderCharPreview();
    syncSheetButton();
  }

  /** The progress card sits exactly over the preview card (same box), opaque, with the spinner and Stop. */
  function fitMasterProgress() {
    const ov = $("masterProgress"), box = $("sheetPreview");
    if (ov.hidden || !box) return;
    Object.assign(ov.style, { top: `${box.offsetTop}px`, left: `${box.offsetLeft}px`, width: `${box.offsetWidth}px`, height: `${box.offsetHeight}px` });
  }
  function showMasterProgress(on, text) {
    const was = !$("masterProgress").hidden;
    $("masterProgress").hidden = !on;
    if (text) $("masterProgressText").textContent = text;
    fitMasterProgress();
    if (was !== on) $("charIntro").innerHTML = introHTML($("name").value.trim());  // "Drawing <Name>'s master…" while it runs
  }
  window.addEventListener("resize", fitMasterProgress);

  async function generateMaster(seed, n = 1) {
    if (state.busy) return;
    const look = clean($("prompt").value), outfit = clean($("mOutfit").value);
    if ((look + outfit).length < 8) {  // P2-03: the message sits with the field, and focus goes there
      $("charStatus").textContent = "Describe your character in a few words (look, hair, outfit).";
      $("prompt").setAttribute("aria-invalid", "true");
      $("prompt").setAttribute("aria-describedby", "charStatus");
      $("prompt").focus();
      return;
    }
    $("prompt").removeAttribute("aria-invalid");
    const s = Number.isFinite(seed) ? seed : Math.max(0, Math.floor(Number($("mSeed").value) || 0));
    // what Variation # read before this grid opened (a re-run from an open grid keeps the first one): restored on Cancel
    const prevSeed = state.options ? state.options.prevSeed : $("mSeed").value;
    $("mSeed").value = String(s);
    $("mSeedNote").hidden = true;
    const fd = new FormData();
    fd.append("name", charName());
    fd.append("look", look); fd.append("outfit", outfit);
    fd.append("age", $("mAge").value); fd.append("style", $("mStyle").value);
    fd.append("seed", String(s));
    if (n > 1) fd.append("options", String(n));
    state.busy = true;
    state.stopped = null;
    syncSheetButton();
    $("btnMaster").disabled = true;
    $("btnMasterOptions").disabled = true;
    $("charStatus").textContent = "";
    const who = charName();
    const sig = masterSig();  // the words this master is drawn from
    showMasterProgress(true, `Drawing ${who}’s master…`);
    try {
      const res = await fetch("/api/master", { method: "POST", body: fd });
      let m = await res.json();
      if (!res.ok) throw new Error(m.detail || "Couldn’t draw the master. Try again.");
      state.masterJob = m.master_id;
      const t0 = Date.now();
      // a background job, like a take: poll until done / error / stopped; the panel shows a spinner and the estimate
      while (!m.done) {
        const left = m.eta_s ? Math.max(1, Math.round(m.eta_s - (Date.now() - t0) / 1000)) : 0;
        const what = n > 1 && m.stage && /^Drawing option/.test(m.stage) ? m.stage.replace(/…$/, "") : `Drawing ${who}’s master`;
        showMasterProgress(true, `${what}…${left ? ` about ${left} s` : ""}`);
        await new Promise((r) => setTimeout(r, 700));
        const r2 = await fetch(`/api/master/${encodeURIComponent(m.master_id)}`);
        m = await r2.json();
        if (!r2.ok) throw new Error(m.detail || "Couldn’t draw the master. Try again.");
      }
      if (m.state === "cancelled") {
        // back to the master that's showing (or mark the typed variation as not drawn)
        state.stopped = { seed: state.master && state.master.url ? state.master.seed : null };
        if (state.stopped.seed !== null) $("mSeed").value = String(state.stopped.seed);
        else $("mSeedNote").hidden = false;
        return;
      }
      if (m.state !== "done") throw new Error(m.error || "Couldn’t draw the master. Try again.");
      state.isDemo = false;
      state.sheetUrl = null; state.sheetMade = false;
      state.packDir = "";  // a new master is a new character until it's saved
      state.noLibrary = true;  // a new master is a new look: never swap in a saved character's picture
      $("libraryNote").hidden = true;
      if (m.options) {
        const items = m.options.filter((x) => x.state === "done" && x.url).map((x) => ({ seed: x.seed, url: x.url }));
        state.options = { id: m.master_id, items, sig, prompt_lock: m.prompt_lock, chosen: null, prevSeed };
        $("mSeed").value = prevSeed;  // nothing picked yet: Variation # follows the selected tile from here on
      } else {
        state.options = null;
        state.master = { id: m.master_id, url: m.url, seed: m.seed, label: m.label, prompt_lock: m.prompt_lock, saved: false, sig };
        state.masters = (state.masters || []).concat([state.master]).slice(-6);
      }
      $("sheetDownload").hidden = true;
      $("charStatus").textContent = m.preview ? (m.options ? "Preview mode: these cards are placeholders for the options." : "Preview mode: this card is a placeholder for the master.") : "";
      resetResult();
    } catch (e) {
      $("charStatus").textContent = e.message;
    } finally {
      state.busy = false;
      state.masterJob = null;
      showMasterProgress(false);
      $("btnMaster").disabled = false;
      $("btnMasterOptions").disabled = false;
      renderCharPreview();
      renderMasterRow();
      syncMasterButtons();
      syncSheetButton();
    }
  }

  async function stopMaster() {
    if (!state.masterJob) return;
    $("btnMasterStop").disabled = true;
    showMasterProgress(true, "Stopping…");
    try { await fetch(`/api/master/${encodeURIComponent(state.masterJob)}/cancel`, { method: "POST" }); }
    finally { $("btnMasterStop").disabled = false; }
  }

  /** Tap a tile: it's selected (badge, aria-checked, caption under the grid) and Variation # shows its seed. */
  function selectOption(seed) {
    state.options.chosen = seed;
    $("mSeed").value = String(seed);
    $("mSeedNote").hidden = true;
    renderCharPreview(); syncSheetButton();
  }

  /** Close the grid without picking (Cancel, or the words / character / mode changed): Variation # goes back to what
   * it read before the grid opened. */
  function closeOptions() {
    if (!state.options) return;
    if (state.options.prevSeed !== undefined && state.options.prevSeed !== null) $("mSeed").value = state.options.prevSeed;
    state.options = null;
  }

  /** The first variation a new draw starts from: after the open grid's last option, else the typed number (or the
   * next one when it is the master showing). */
  function nextSeed() {
    if (state.options && state.options.items.length) return Math.max(...state.options.items.map((x) => x.seed)) + 1;
    const typed = Math.max(0, Math.floor(Number($("mSeed").value) || 0));
    return state.master && state.master.url && typed === state.master.seed ? typed + 1 : typed;
  }

  /** Use this one: the chosen option becomes the master (POST /api/master/{id}/pick); the other options are kept and
   * go into the character's folder when it's saved. */
  async function useOption() {
    const o = state.options;
    if (!o || o.chosen === null || state.busy) return;
    const fd = new FormData();
    fd.append("seed", String(o.chosen));
    const res = await fetch(`/api/master/${encodeURIComponent(o.id)}/pick`, { method: "POST", body: fd });
    const m = await res.json();
    if (!res.ok) { $("charStatus").textContent = m.detail || "Couldn’t use that option. Try again."; return; }
    state.options = null;
    state.master = { id: m.master_id, url: `${m.url}&v=${m.seed}`, seed: m.seed, label: m.label, prompt_lock: m.prompt_lock, saved: false, sig: o.sig };
    state.masters = (state.masters || []).concat([state.master]).slice(-6);
    $("mSeed").value = String(m.seed);
    $("charStatus").textContent = "";
    renderCharPreview(); renderMasterRow(); syncMasterButtons(); syncSheetButton();
    if (window.OpenSoulStoryboard) window.OpenSoulStoryboard.loadCast();
  }
  $("sheetPreview").addEventListener("click", (e) => {
    const t = e.target.closest("[data-option]");
    if (t && state.options) { selectOption(Number(t.dataset.option)); return; }
    if (e.target.closest("#btnUseOption")) useOption();
    if (e.target.closest("#btnCancelOptions")) { closeOptions(); $("charStatus").textContent = ""; renderCharPreview(); syncSheetButton(); }
  });

  function makeOptions() { return `Make ${state.masterBatch || 4} options`; }

  /** Once a master exists the single-draw link reads "Try another" (next variation); earlier masters stay one tap away. */
  function syncMasterButtons() {
    const has = !!(state.master && state.master.url);
    $("btnMaster").textContent = has ? "Try another" : "Generate one";
    $("btnMasterOptions").textContent = `1 · ${makeOptions()}`;
  }

  /** Every master drawn this session; the one showing has a ring. Tapping one shows it, sets Variation # to it, and
   * the sheet is then built from that one (makeSheet sends its master_id). */
  function renderMasterRow() {
    const row = $("masterRow");
    if (!row) return;
    const all = state.masters || [];
    row.hidden = all.length < 2;
    row.replaceChildren();
    if (all.length < 2) return;
    const lab = document.createElement("span");
    lab.className = "hint";
    lab.textContent = "Your masters:";
    row.appendChild(lab);
    for (const x of all) {
      const on = !!state.master && x.id === state.master.id;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "master-thumb" + (on ? " on" : "");
      b.dataset.master = x.id;
      b.setAttribute("aria-pressed", String(on));
      b.title = on ? `Seed ${x.seed} (showing)` : `Show seed ${x.seed}`;
      b.setAttribute("aria-label", b.title);
      const img = document.createElement("img");
      img.src = x.url; img.alt = "";
      b.appendChild(img);
      b.addEventListener("click", () => {
        if (state.busy || on) return;
        state.master = { ...x, saved: false };
        state.packDir = ""; state.sheetUrl = null; state.sheetMade = false; state.stopped = null;
        $("mSeed").value = String(x.seed);
        $("mSeedNote").hidden = true;
        $("charStatus").textContent = "";
        resetResult(); renderCharPreview(); renderMasterRow(); syncMasterButtons(); syncSheetButton();
      });
      row.appendChild(b);
    }
  }

  /** The shown master becomes the character's pack (refs/ref_00, origin "text"); the sheet then starts from it. */
  async function saveMaster() {
    if (!state.master || state.master.saved) return true;
    const fd = new FormData();
    fd.append("name", charName());
    const res = await fetch(`/api/master/${encodeURIComponent(state.master.id)}/save`, { method: "POST", body: fd });
    const d = await res.json();
    if (!res.ok) { $("charStatus").textContent = d.detail || "Couldn’t save the master. Try again."; return false; }
    state.master.saved = true;
    state.packDir = d.pack_dir;
    state.savedName = d.name;
    state.dirty = false;
    $("charStatus").textContent = d.status;
    loadCharPick();
    return true;
  }

  async function saveCharacter({ quiet = false } = {}) {
    const why = blockReason();
    if (why) { $("charStatus").textContent = why; return false; }
    if (state.isDemo) { if (!quiet) $("charStatus").textContent = "The demo character is ready. Next, choose a shot."; return true; }
    if (state.master && state.cmode === "describe") {
      const ok = await saveMaster();
      syncSheetButton();
      return ok;
    }
    const fd = new FormData();
    fd.append("name", charName());
    fd.append("prompt_lock", description());
    fd.append("look", clean($("prompt").value));
    fd.append("outfit", clean($("mOutfit").value));
    fd.append("seed", "42");
    fd.append("use_library", state.noLibrary || bigLookChange() ? "false" : "true");
    for (const f of $("photos").files) fd.append("images", f);
    $("btnSaveCharacter").disabled = true;
    try {
      const res = await fetch("/api/character", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not save your character. Try again.");
      state.packDir = data.pack_dir;
      state.dirty = false;
      if (!quiet) $("charStatus").textContent = data.status || "Character saved. Next, choose a shot.";
      loadCharPick();
      state.savedName = data.name || charName();
      await refreshLook();
      if (window.OpenSoulStoryboard) window.OpenSoulStoryboard.loadCast();  // the cast grid shows the new card now (P2-04)
      return true;
    } catch (e) {
      $("charStatus").textContent = e.message;
      return false;
    } finally {
      syncSheetButton();
    }
  }

  // ---------- Character sheet (one tap) ----------
  const VIEW_STATUS = { queued: "Waiting", rendering: "Rendering", retrying: "Retrying", done: "Done", failed: "Failed" };

  function checkList(v) {
    const cs = v.checks || [];
    if (!cs.length) return "";
    const items = cs.map((c) => {
      const mark = c.passed === true ? "✓" : c.passed === false ? "✗" : "·";
      return `<span class="ck ${c.passed === false ? "bad" : c.passed ? "ok" : ""}" title="${esc(c.question)}">${mark} ${esc(c.label)}</span>`;
    }).join("");
    return `<span class="cks">${items}</span>`;
  }

  function renderSheetProgress(job) {
    state.sheetJob = job.job_id;
    const pct = Math.round((100 * job.done) / (job.total || 6));
    $("sheetBar").style.width = `${Math.max(6, job.state === "done" ? 100 : pct)}%`;
    $("sheetText").textContent = job.stage || "Working…";
    $("sheetViews").innerHTML = (job.views || []).map((v) => {
      // Per-view warnings only for real (studio) problems; a preview's stand-in comparisons get one calm line.
      const flag = v.flag_source ? v.flag_source === "studio" : (v.flagged || !!v.note);
      const st = flag ? "Needs a look" : (VIEW_STATUS[v.status] || v.status);
      const face = v.arcface != null ? ` · face ${Number(v.arcface).toFixed(2)}` : "";
      const tries = v.attempts > 1 ? ` · fixed in ${v.attempts} tries` : "";
      const regen = job.state !== "running" && v.status === "done"
        ? `<button type="button" class="regen" data-view="${esc(v.id)}">Regenerate</button>` : "";
      const why = v.flag_reason || v.note || "";
      return `<li class="vc s-${esc(v.status)} ${flag ? "flag" : ""}"${flag ? ` aria-label="${esc(v.label)}: needs a look"` : ""}><strong>${flag ? "⚠ " : ""}${esc(v.label)}</strong>
        <span>${esc(st)}${esc(face)}${esc(tries)}</span>${checkList(v)}
        ${flag && why ? `<em class="vnote">${esc(why)}</em>` : ""}${regen}</li>`;
    }).join("");
    if (job.preview_note) $("sheetViews").insertAdjacentHTML("beforeend", `<li class="vc-preview">${esc(job.preview_note)}</li>`);
    $("sheetViews").querySelectorAll(".regen").forEach((b) => b.addEventListener("click", () => regenerate(b.dataset.view)));
  }

  async function pollSheet(job) {
    renderSheetProgress(job);
    while (job.state === "running") {
      await new Promise((r) => setTimeout(r, 1500));
      const r2 = await fetch(`/api/sheet/${job.job_id}`);
      job = await r2.json();
      if (!r2.ok) throw new Error(job.detail || "The sheet status is not available. Try again.");
      renderSheetProgress(job);
    }
    if (job.state !== "done") throw new Error(job.error || "Couldn’t make the sheet.");
    state.packDir = job.pack_dir;
    state.isDemo = false;
    state.sheetUrl = job.sheet_url;
    state.sheetMade = true;
    state.savedName = charName();
    const front = (job.views || []).find((v) => v.id === "full_front" && v.url) || (job.views || []).find((v) => v.url);
    state.sessionStill = front && !job.dry_run ? front.url : null;
    $("libraryNote").hidden = true;
    renderTileMedia();
    state.dirty = false;
    resetResult();
    renderCharPreview();
    $("sheetDownload").href = job.download_url;
    $("sheetDownload").hidden = false;
    const flagged = (job.studio_flagged || (job.views || []).filter((v) => v.note).map((v) => v.id)).length;
    $("charStatus").textContent = flagged
      ? `Character sheet ready. ${flagged} view(s) can have errors: click Regenerate on them, or continue.`
      : "";  // the intro above says "<name> is ready. Next, choose a shot." (one ready line, not three)
    loadCharPick();
    return job;
  }

  async function regenerate(viewId) {
    try {
      const res = await fetch(`/api/sheet/${state.sheetJob}/regenerate/${viewId}`, { method: "POST" });
      const job = await res.json();
      if (!res.ok) throw new Error(job.detail || "Couldn’t regenerate that view.");
      await pollSheet(job);
    } catch (e) {
      $("charStatus").textContent = e.message;
    }
  }

  async function makeSheet() {
    const why = blockReason();
    if (why) { $("charStatus").textContent = why; return; }
    if (state.master && state.cmode === "describe" && !(await saveMaster())) return;
    const fd = new FormData();
    const file = $("photos").files[0];
    fd.append("consent", file ? String($("consent").checked) : "false");
    fd.append("name", charName());
    fd.append("prompt_lock", description());
    fd.append("look", clean($("prompt").value));
    fd.append("outfit", clean($("mOutfit").value));
    fd.append("style", $("mStyle").value);  // OS-006/OS-010: the sheet follows the style (anime stays anime)
    // A text-only new character starts fresh; the demo keeps its own pack (never modified on disk).
    fd.append("pack_dir", state.isDemo || state.packDir ? state.packDir : "");
    fd.append("use_library", state.noLibrary || bigLookChange() ? "false" : "true");
    if (state.master && state.cmode === "describe" && !file) fd.append("master_id", state.master.id);  // the one showing
    if (file) fd.append("image", file);
    state.busy = true;
    syncSheetButton();
    $("sheetDownload").hidden = true;
    $("sheetProgress").hidden = false;
    $("sheetText").textContent = file ? "Starting…" : `Drawing ${charName()} from your description…`;
    $("charStatus").textContent = "";
    try {
      const res = await fetch("/api/sheet", { method: "POST", body: fd });
      const job = await res.json().catch(() => ({}));
      if (!res.ok) {
        // OS-046: the sheet did not start. Clear "Drawing …" and tell the user what to do.
        $("sheetProgress").hidden = true;
        $("sheetText").textContent = "";
        const changed = res.status === 409 && /description changed/i.test(job.detail || "");
        throw new Error(changed
          ? "Your Look changed after this master was made, so the sheet was not redone. Click 1 · Make 4 options to draw the new Look, pick one, then click Make character sheet."
          : (typeof job.detail === "string" && job.detail) || "Couldn’t start the sheet. Try again.");
      }
      await pollSheet(job);
    } catch (e) {
      $("charStatus").textContent = e.message;
    } finally {
      state.busy = false;
      syncSheetButton();
    }
  }

  // ---------- Generate ----------
  const STAGES = ["Locking identity…", "Making the views…", "Adding the look…", "Finishing…"];

  /** Make sure the shot uses the character on screen (auto-saves a new or edited one). */
  async function ensureCharacter() {
    if (state.isDemo) return true;
    if (state.packDir && (!state.dirty || state.sheetMade)) return true;
    if (!description() && !hasPhoto()) {
      $("progressText").textContent = hasDemo(DEMO_NAME) ? `Describe your character in step 1 first, or click Use the demo character (${DEMO_NAME}).` : "Describe your character in step 1 first.";
      return false;
    }
    const ok = await saveCharacter({ quiet: true });
    if (!ok) $("progressText").textContent = $("charStatus").textContent || "Save your character in step 1 first.";
    return ok;
  }

  function resetResult() {
    state.result = null;
    $("shotResult").hidden = true;
    $("shotPreview").innerHTML = "";
    $("resultPreview").innerHTML = '<div class="empty">Generate a shot to see it here</div>';
    $("resultTitle").textContent = "";
    $("resultNote").textContent = "";
    $("promptView").textContent = "Generate once to see the exact prompt sent to the video model.";
  }

  async function generate() {
    const btn = $("btnGenerate");
    btn.disabled = true;
    $("progress").hidden = false;
    $("progressBar").style.width = "4%";
    $("progressText").textContent = "Getting your character ready…";
    let timer = null;
    let failed = false;
    try {
      if (!(await ensureCharacter())) { failed = true; return; }
      let i = 0;
      const tick = () => {
        $("progressText").textContent = STAGES[Math.min(i, STAGES.length - 1)];
        $("progressBar").style.width = `${Math.min(92, (i + 1) * 24)}%`;
        i++;
      };
      tick();
      timer = setInterval(tick, 450);
      const line = $("line").value.trim();
      const body = {
        camera: state.effect ? null : (state.camera || STATIC_ID),
        effect: state.effect,
        era: state.era,
        line,
        voice: line ? state.voice : null,
        pack_dir: state.packDir,
        name: state.isDemo ? demoName() : charName(),
        seed: Number($("advSeed").value) || 42,
        tts_backend: line ? ($("advTts").value || undefined) : undefined,
        lipsync_backend: line ? ($("advLipsync").value || undefined) : undefined,
        advanced: {
          duration_s: Number($("advDuration").value) || undefined,
          steps: Number($("advSteps").value) || undefined,
          cfg: $("advCfg").disabled ? undefined : Number($("advCfg").value) || undefined,
        },
      };
      const [res] = await Promise.all([
        fetch("/api/shot", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
        new Promise((r) => setTimeout(r, 1500)),
      ]);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Couldn’t make that shot. Try another tile.");
      state.result = data;
      $("progressBar").style.width = "100%";
      showResult(data);
    } catch (e) {
      failed = true;
      $("progressText").textContent = e.message;
    } finally {
      if (timer) clearInterval(timer);
      btn.disabled = false;
      if (!failed) setTimeout(() => { $("progress").hidden = true; }, 300);
    }
  }

  function mediaHTML(data, alt) {
    if (data.video_url) return `<video src="${esc(data.video_url)}" autoplay muted loop playsinline controls></video>`;
    if (data.poster_url) return `<img src="${esc(data.poster_url)}" alt="${esc(alt)}" />`;
    return nameCard(charName(), "Preview");
  }

  function showResult(data) {
    const title = `${charName()} · ${data.plan.title}`;
    // Result stays on the Shot step, with the full prompt visible, then a clear Next: Share.
    $("shotPreview").innerHTML = mediaHTML(data, `Preview of ${charName()}`);
    $("shotResultTitle").textContent = title;
    $("shotResultNote").textContent = data.note || "";
    $("shotResult").hidden = false;
    $("promptView").textContent = data.plan.prompt;
    // The video prompt drops <sigh>/<chuckle>; show the line exactly as the voice engine gets it, tags included.
    const voiceStage = (data.plan.stages || []).find((st) => st.stage === "voice");
    const spoken = voiceStage && voiceStage.inputs ? voiceStage.inputs.text : "";
    $("lineViewRow").hidden = !spoken;
    $("lineView").textContent = spoken || "";
    setAdvanced(true);
    $("shotResult").scrollIntoView({ behavior: "smooth", block: "nearest" });
    // Share step gets the same result.
    $("resultPreview").innerHTML = mediaHTML(data, `Preview of ${charName()}`);
    $("resultTitle").textContent = title;
    $("resultNote").textContent = data.note || "";
    syncExportLabel(data.dry_run);
    $("caption").value = `${charName()} — ${data.plan.title}. Made with OpenSoul. Videos made with OpenSoul are AI-generated. #OpenSoul #AIvideo`;  // AI label (LTX license)
  }

  function setAdvanced(open) {
    $("advancedBody").hidden = !open;
    syncCfgNote();
    $("advancedToggle").setAttribute("aria-expanded", String(open));
    $("advancedToggleText").textContent = open ? "· Hide" : "· Show";
  }

  function syncExportLabel(placeholder) {
    $("btnExportText").textContent = placeholder ? "Export preview (placeholder)" : "Export vertical MP4";
    $("exportNotice").hidden = !placeholder;
  }

  async function exportMp4() {
    const btn = $("btnExport");
    if (!state.result) { $("shareStatus").textContent = "Generate a shot first (step 2). Then export it."; return; }
    btn.disabled = true;
    $("shareStatus").textContent = "Preparing your vertical video…";
    try {
      const res = await fetch("/api/share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_url: state.result?.video_url || "", title: state.result?.plan?.title || "", name: charName(), pack_dir: state.packDir,
          camera: state.result?.plan?.camera || null, effect: state.result?.plan?.effect || null,
        }),
      });
      const data = await res.json();
      if (!data.mp4_url) throw new Error(data.note || "Export failed. Try again.");
      const a = document.createElement("a");
      a.href = data.mp4_url;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      $("shareStatus").textContent = data.placeholder
        ? `Saved ${data.filename} (9:16 preview placeholder).`
        : `Saved ${data.filename} (9:16).`;
    } catch (e) {
      $("shareStatus").textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function copyCaption() {
    const text = $("caption").value;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      $("caption").select();
      document.execCommand("copy");
    }
    $("shareStatus").textContent = "Caption copied.";
  }

  async function shuffle() {
    const s = await (await fetch("/api/shuffle")).json();
    state.effect = s.effect || null;
    state.camera = state.effect ? null : (s.camera || STATIC_ID);
    state.era = s.era;
    $("advSeed").value = s.seed;
    setTab(state.effect ? "effects" : "camera");
    syncSelection();
  }

  // ---------- System status ----------
  async function toggleStatus(force) {
    const panel = $("statusPanel");
    const open = typeof force === "boolean" ? force : panel.hidden;
    panel.hidden = !open;
    $("advancedLink").setAttribute("aria-expanded", String(open));
    if (!open) return;
    $("statusLines").innerHTML = "<li>Checking…</li>";
    try {
      const h = await (await fetch("/api/health")).json();
      const lines = h.summary || [
        { label: "Mode", value: h.dry_run ? "Preview mode" : "Studio" },
        { label: "OpenSoul version", value: h.version },
      ];
      const stages = Array.isArray(h.stages) ? h.stages : [];
      const stageLabels = new Set(stages.map((s) => s.label));
      const general = stages.length ? lines.filter((l) => !stageLabels.has(l.label)) : lines;
      let html = general.map((l) => `<li><span>${esc(l.label)}</span><strong>${esc(l.value)}</strong></li>`).join("");
      if (stages.length) {
        // One row per pipeline stage from the model registry (local file checks only).
        const word = { installed: "Ready", optional_installed: "Ready (optional)", optional_missing: "Optional, not installed", missing: "Missing" };
        html += `<li class="status-sub"><span>Models per stage</span></li>`;
        html += stages.map((s) => {
          const b = (s.backends || []).find((x) => x.id === s.default_backend) || {};
          const ok = s.status === "installed" || s.status === "optional_installed";
          const tone = ok ? "ok" : (s.status === "missing" ? "bad" : "warn");
          const hint = !ok && s.download_hint ? `<code class="stage-hint">${esc(s.download_hint)}</code>` : "";
          return `<li class="stage-row"><span>${esc(s.label)}<small>${esc(b.label || s.default_backend || "")}</small></span>` +
            `<strong class="stage-${tone}">${esc(word[s.status] || s.status)}${hint}</strong></li>`;
        }).join("");
      }
      $("statusLines").innerHTML = html;
      $("advancedBox").textContent = JSON.stringify(h, null, 2);
    } catch {
      $("statusLines").innerHTML = "<li>Could not load system status. Is the app still running?</li>";
    }
  }

  // ---------- Stale-server banner ----------
  // /api/health build: "stale" = the repo moved on after this server started (it still runs the old code), and a
  // changed sha under an open page = the server was restarted, so this page's scripts are the old ones.
  const pageBuild = { sha: null };
  function staleBannerHTML(b, first) {
    const short = (x) => esc(String(x || "").slice(0, 7));
    if (first && b.sha && first !== b.sha)
      return `<p><strong>OpenSoul restarted with newer code</strong> (${short(b.sha)}). This page still runs the old version.</p>
        <button class="btn btn-primary btn-sm" type="button" data-stale="reload">Reload the page</button>`;
    if (!b.stale || b.app_changed === false) return "";
    if (sessionStorage.getItem(`opensoul.staleDismissed.${b.head_sha}`)) return "";
    const n = b.changed_count ? ` (${b.changed_count} file${b.changed_count === 1 ? "" : "s"} changed)` : "";
    return `<p><strong>This server runs older code.</strong> It started on ${short(b.sha)}; the code is now at ${short(b.head_sha)}${n}.         Restart OpenSoul to see the latest changes.</p>
      <button class="btn btn-ghost btn-sm" type="button" data-stale="dismiss">Dismiss</button>`;
  }
  async function checkBuild() {
    let b;
    try { b = (await (await fetch("/api/health", { cache: "no-store" })).json()).build; } catch { return; }
    if (!b) return;
    if (!pageBuild.sha) pageBuild.sha = b.sha;
    const box = $("staleBanner");
    if (!box) return;
    const html = staleBannerHTML(b, pageBuild.sha);
    box.hidden = !html;
    box.innerHTML = html;
    document.body.classList.toggle("has-stale-banner", !!html);
    const rl = box.querySelector('[data-stale="reload"]');
    if (rl) rl.addEventListener("click", () => location.reload());
    const d = box.querySelector('[data-stale="dismiss"]');
    if (d) d.addEventListener("click", () => { sessionStorage.setItem(`opensoul.staleDismissed.${b.head_sha}`, "1"); box.hidden = true; box.innerHTML = ""; });
  }
  checkBuild();
  setInterval(() => { if (!document.hidden) checkBuild(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkBuild(); });

  // ---------- Wiring ----------
  document.querySelectorAll(".step-chip").forEach((el) => el.addEventListener("click", () => setStep(Number(el.dataset.step))));
  document.querySelectorAll(".seg[data-tab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  document.querySelectorAll(".seg[data-cmode]").forEach((b) => b.addEventListener("click", () => setCharMode(b.dataset.cmode)));
  // "Try another" = the next variation number (unless the user typed a different one)
  $("btnMaster").addEventListener("click", () => generateMaster(nextSeed()));
  $("btnMasterStop").addEventListener("click", stopMaster);
  // "Make N options": N variations from the typed number on, shown as one pick-one grid
  $("btnMasterOptions").addEventListener("click", () => generateMaster(nextSeed(), state.masterBatch));
  $("toDescribe").addEventListener("click", () => setCharMode("describe"));
  ["mOutfit", "mAge", "mStyle"].forEach((id) => $(id).addEventListener(id === "mOutfit" ? "input" : "change", onCharacterEdited));
  $("mSeed").addEventListener("input", onCharacterEdited);  // with the grid open, typing an option's number selects that tile
  $("toStep2").addEventListener("click", () => setStep(2));
  // The six-tab shell (unified.js) reuses this character editor in its Characters tab.
  window.OpenSoulCreate = { pickCharacter: (n) => pickCharacter(n), loadDemo: (w) => loadDemo(w), newCharacter: () => newCharacter(),
    setStep: (n) => setStep(n), refreshPick: () => loadCharPick() };
  $("toStep3").addEventListener("click", () => setStep(3));
  $("back1").addEventListener("click", () => setStep(1));
  $("back2").addEventListener("click", () => setStep(2));
  $("btnSaveCharacter").addEventListener("click", () => saveCharacter());
  $("prompt").addEventListener("input", () => $("prompt").removeAttribute("aria-invalid"));
  $("btnSheet").addEventListener("click", makeSheet);
  $("consent").addEventListener("change", syncSheetButton);
  $("btnLoadDemo").addEventListener("click", () => loadDemo(DEMO_NAME));
  if ($("btnLoadDemo2")) $("btnLoadDemo2").addEventListener("click", () => loadDemo("Pixel"));
  if ($("btnCredits")) $("btnCredits").addEventListener("click", () => {
    const d = $("creditsCard");
    if (d.showModal) d.showModal(); else d.setAttribute("open", "");
  });
  if ($("creditsCard")) $("creditsCard").addEventListener("click", (e) => {
    const r = e.currentTarget.getBoundingClientRect();  // a click on the backdrop (outside the card) closes it
    if (e.target === e.currentTarget && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) e.currentTarget.close();
  });
  $("btnGenerate").addEventListener("click", generate);
  $("btnRegenerate").addEventListener("click", generate);
  $("btnShuffle").addEventListener("click", shuffle);
  $("btnExport").addEventListener("click", exportMp4);
  $("btnCopy").addEventListener("click", copyCaption);
  $("name").addEventListener("input", onCharacterEdited);
  $("name").addEventListener("input", () => renderCharPick());
  $("prompt").addEventListener("input", onCharacterEdited);
  $("prompt").addEventListener("input", () => {
    if ($("mOutfit").placeholder === "Included above") $("mOutfit").placeholder = OUTFIT_HINT;  // edited: Outfit is its own field again
    syncNewLookNote();
  });
  $("line").addEventListener("input", () => { $("lineCount").textContent = $("line").value.length; syncSelection(); syncCfgNote(); });
  $("advLipsync").addEventListener("change", syncCfgNote);
  // Emotion tags: insert <sigh> etc. at the cursor (Orpheus reads them; the video prompt and captions drop them).
  document.querySelectorAll("#tagBar [data-tag]").forEach((b) => b.addEventListener("click", () => {
    const ta = $("line"), tag = `<${b.dataset.tag}>`;
    const a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
    const before = ta.value.slice(0, a), after = ta.value.slice(z);
    const ins = (before && !/\s$/.test(before) ? " " : "") + tag + (after && !/^\s/.test(after) ? " " : "");
    if ((before + ins + after).length > 280) return;
    ta.value = before + ins + after;
    ta.focus(); ta.selectionStart = ta.selectionEnd = before.length + ins.length;
    ta.dispatchEvent(new Event("input"));
  }));
  // The character's own voice (saved per character) is the default voice chip.
  fetch(`/api/voices?name=${encodeURIComponent(charName())}`).then((r) => r.json()).then((d) => {
    if (d.character_voice && state.presets && state.presets.voices.some((v) => v.id === d.character_voice)) { state.voice = d.character_voice; syncSelection(); }
  }).catch(() => {});
  $("photos").addEventListener("change", syncPhotos);
  $("clearPhotos").addEventListener("click", clearPhotos);
  $("btnStartFresh").addEventListener("click", startFresh);
  $("charVoice").addEventListener("change", saveCharVoice);
  $("btnVoiceSample").addEventListener("click", playVoiceSample);
  $("btnNewLookName").addEventListener("click", renameNewLook);
  $("newLookName").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); renameNewLook(); } });
  $("advancedToggle").addEventListener("click", () => setAdvanced($("advancedBody").hidden));
  $("advancedLink").addEventListener("click", () => toggleStatus());
  $("statusClose").addEventListener("click", () => toggleStatus(false));
  $("statusDetailsToggle").addEventListener("click", () => {
    const open = $("advancedBox").hidden;
    $("advancedBox").hidden = !open;
    $("statusDetailsToggle").setAttribute("aria-expanded", String(open));
    $("statusDetailsToggle").textContent = open ? "Hide details" : "Show details";
  });

  (async () => {
    const [boot, presets] = await Promise.all([loadBootstrap(), fetch("/api/presets").then((r) => r.json())]);
    loadBackends();
    state.presets = presets;
    renderTiles();
    syncSelection();
    const params = new URLSearchParams(location.search);
    const dq = (params.get("demo") || "").toLowerCase();
    const named = (state.demos || []).find((d) => d.name.toLowerCase() === dq);
    const demo = ["1", "true", "yes"].includes(dq) || !!named;
    if (demo) loadDemo(named ? named.name : DEMO_NAME); else newCharacter(boot);
    loadCharPick();
    const tab = params.get("tab");
    if (tab) setTab(tab);
    const step = Number(params.get("step") || "1");
    if (step === 3 && demo) { setStep(2); await generate(); setStep(3); }  // demo video: straight to a result
    else if (step >= 1 && step <= 3) setStep(step);
  })();
})();
