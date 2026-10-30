/* Music tab (app/music_routes.py, docs/MUSIC.md).
   Lyrics -> song (background job) -> beat map -> shot list cut to the beat -> shots in a story -> sync sung shots to the
   vocal -> export the music video. Lives in #musicView; the "Music videos" button on the right of the top bar opens it. */
(() => {
  const $ = (id) => document.getElementById(id);
  const view = $("musicView");
  const btn = $("ufMusicBtn");
  if (!view || !btn) return;
  // Full studio only: the Shorts page (?ui=classic) never shows Music videos, not even with ?music=1.
  if (new URLSearchParams(location.search).get("ui") === "classic") { btn.remove(); view.remove(); return; }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const st = { models: null, song: null, poll: null, handoff: null, lip: {}, ar: "ar-169" };
  const SAMPLE = "[Verse]\nMy kettle hums a morning tune\nThe toast is cold, the bus is soon\n[Chorus]\nRUN RUN RUN to the bus\nNobody waits for us\n[Bridge]\nOne more stop, one more song\n[Chorus]\nRUN RUN RUN to the bus";
  const fmt = (t) => { const m = Math.floor(t / 60); const s = (t - m * 60).toFixed(1).padStart(4, "0"); return `${m}:${s}`; };

  async function api(path, body) {
    const r = await fetch(`/api/music${path}`, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong. Try again.");
    return d;
  }

  view.innerHTML = `
    <header class="mu-head">
      <div><h1 id="muH">Music videos</h1>
        <p>Write the lyrics. Make the song. OpenSoul makes a shot list that follows the beat. Send the shots to a story. Then render the sung shots with the song.</p></div>
    </header>
    <p class="mu-preview" id="muPreview" hidden>Preview mode: you hear a click track and a test tone, not a real song. Connect a studio to make real songs.</p>
    <section class="mu-card" aria-labelledby="muWriteH">
      <h2 id="muWriteH"><span class="flow-n">1</span>Song</h2>
      <div class="mu-grid">
        <div>
          <div class="field"><label for="muTitle">Title</label><input id="muTitle" type="text" maxlength="80" placeholder="e.g. Late for the Bus" autocomplete="off" /></div>
          <div class="field"><label for="muLyrics">Lyrics</label>
            <textarea id="muLyrics" rows="10" placeholder="${esc(SAMPLE)}"></textarea>
            <span class="hint">Put each part on its own line: [Verse], [Chorus], [Bridge]. Short lines (6–10 syllables) sing best. Your own words only.</span></div>
          <div class="field"><label for="muStyle">Style</label><input id="muStyle" type="text" maxlength="512" placeholder="e.g. bright synth-pop, 112 BPM, female vocal, punchy drums" autocomplete="off" />
            <span class="hint">Genre, mood, instruments, voice. Add a tempo like “112 BPM”. Describe a sound. Do not name real artists or songs.</span></div>
        </div>
        <div>
          <div class="field"><label for="muModel">Song model</label><select id="muModel"></select><span class="hint" id="muModelNote"></span></div>
          <div class="field-row">
            <div class="field"><label for="muSeconds">Length</label><select id="muSeconds"><option value="20">20 seconds</option><option value="30" selected>30 seconds</option><option value="60">1 minute</option><option value="120">2 minutes</option></select></div>
            <div class="field field-seed"><label for="muSeed">Seed</label><input id="muSeed" type="number" min="0" step="1" value="7" inputmode="numeric" /></div>
          </div>
          <div class="actions"><button class="btn btn-primary" id="muGo" type="button">Generate song</button><button class="btn-link" id="muStop" type="button" hidden>Stop</button></div>
          <p class="status" id="muStatus" role="status"></p>
          <div class="mu-earlier" id="muEarlier" hidden><span class="hint">Earlier songs:</span> <span id="muEarlierList"></span></div>
        </div>
      </div>
    </section>
    <section class="mu-card" id="muBeatCard" hidden aria-labelledby="muBeatH">
      <h2 id="muBeatH"><span class="flow-n">2</span>Beat map</h2>
      <audio id="muAudio" controls preload="metadata"></audio><p class="hint" id="muNoAudio" hidden>Preview: no audio yet.</p>
      <p class="mu-stats" id="muStats"></p>
      <div class="mu-map" id="muMap" aria-label="Sections, bars and sung lines over time"></div>
      <p class="hint" id="muBeatNote"></p>
    </section>
    <section class="mu-card" id="muCutCard" hidden aria-labelledby="muCutH">
      <h2 id="muCutH"><span class="flow-n">3</span>Shot list</h2>
      <p class="help">Every cut is on a bar line. Loud parts get shorter shots; quiet parts get longer shots. Shots with a sung line get lip-sync.</p>
      <div class="mu-cutbar">
        <div class="segmented" role="tablist" aria-label="Quality"><button role="tab" class="seg active" data-q="final" aria-selected="true" type="button">Final</button><button role="tab" class="seg" data-q="draft" aria-selected="false" type="button">Draft (4 s max)</button></div>
        <label class="mu-inline">Cut every <select id="muBars"><option value="">Auto</option><option value="1">1 bar</option><option value="2">2 bars</option><option value="4">4 bars</option></select></label>
      </div>
      <ol class="mu-shots" id="muShots"></ol>
    </section>
    <section class="mu-card" id="muSendCard" hidden aria-labelledby="muSendH">
      <h2 id="muSendH"><span class="flow-n">4</span>Make the video</h2>
      <div class="field-row">
        <div class="field"><label for="muWho">Who sings?</label><select id="muWho"></select></div>
        <div class="field"><label for="muStory">Story</label><select id="muStory"></select></div>
      </div>
      <div class="field"><label for="muIdea">Look of the video <span class="optional">(optional)</span></label><input id="muIdea" type="text" maxlength="200" placeholder="e.g. a rainy city street at night, neon reflections" autocomplete="off" /></div>
      <div class="actions"><button class="btn btn-primary" id="muSend" type="button">Make these shots</button></div>
      <p class="status" id="muSendStatus" role="status"></p>
      <div id="muAfter" hidden>
        <p class="hint mu-stemnote" id="muStemNote"></p>
        <ul class="mu-sung" id="muSung" aria-label="Sung shots"></ul>
        <label class="mu-keep"><input type="checkbox" id="muVertical" /> Vertical (9:16) <span class="hint">For a phone post. OpenSoul crops each shot to fill the tall frame. The song plays under it.</span></label>
        <label class="mu-keep"><input type="checkbox" id="muKeepLines" /> Keep the spoken lines <span class="hint">Shots with a spoken line play their own voice over the song. The song goes quieter under them.</span></label>
        <div class="actions"><button class="btn btn-outline" id="muOpenStory" type="button">Open the shots</button><button class="btn btn-primary" id="muExport" type="button">Export music video</button></div>
        <p class="status" id="muExportStatus" role="status"></p>
        <div class="mu-result" id="muResult" hidden></div>
      </div>
    </section>`;

  // ---------------------------------------------------------------- open / close
  function open() {
    document.body.classList.add("music-on");
    view.hidden = false;
    btn.classList.add("active");
    btn.setAttribute("aria-current", "page");
    document.querySelectorAll("#ufTabs [data-tab]").forEach((b) => { b.classList.remove("active"); b.removeAttribute("aria-current"); });
    const url = new URL(location.href); url.searchParams.set("music", "1"); history.replaceState(null, "", url);
    window.scrollTo({ top: 0 });
    btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (!st.models) boot();
  }
  function close() {
    document.body.classList.remove("music-on");
    view.hidden = true;
    btn.classList.remove("active");
    btn.removeAttribute("aria-current");
    const url = new URL(location.href); url.searchParams.delete("music"); history.replaceState(null, "", url);
  }
  btn.addEventListener("click", open);
  // Shots > "Start from a song": open Music with that story picked for the shots.
  window.OpenSoulMusic = { open: (opts = {}) => { st.wantStory = opts.story || ""; btn.click(); } };
  // Narrow screens: the step bar scrolls sideways; the fade on the right edge shows there is more until the end.
  const nav = $("ufTabs");
  const edge = () => nav && nav.classList.toggle("mu-more", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4);
  if (nav) { nav.addEventListener("scroll", edge, { passive: true }); window.addEventListener("resize", edge); setTimeout(edge, 0); }
  document.querySelectorAll("#ufTabs [data-tab]").forEach((b) => b.addEventListener("click", close));

  async function boot() {
    try { st.models = await api("/models"); } catch (e) { $("muStatus").textContent = e.message; return; }
    $("muPreview").hidden = !st.models.preview;
    const s = st.models.song;
    const sel = $("muModel");
    sel.innerHTML = s.options.map((o) => `<option value="${esc(o.id)}"${o.id === s.default ? " selected" : ""}>${esc(o.label)}</option>`).join("")
      + s.pending.map((p) => `<option value="${esc(p.id)}" disabled>${esc(p.label)} · not ready</option>`).join("");
    if (!s.options.length) { $("muGo").disabled = true; $("muModelNote").textContent = s.empty_reason; }
    modelNote();
    sel.addEventListener("change", modelNote);
    earlier();
  }
  function modelNote() {
    const o = (st.models.song.options || []).find((x) => x.id === $("muModel").value);
    if (!o) return;
    const bits = [];
    if (o.preview) bits.push("No model: a click track and a test tone.");
    else if (o.license) bits.push(`${o.license} license.`);
    else {
      if (st.models.preview) bits.push("Runs on your computer after you connect a studio. In Preview mode you get the click track.");
      if (o.vram_gb) bits.push(`Needs about ${o.vram_gb} GB of graphics memory.`);
      if (o.gpu_validated === false) bits.push("Not tested in OpenSoul yet.");
    }
    $("muModelNote").textContent = bits.join(" ");
  }
  async function earlier() {
    try {
      const d = await api("/songs");
      const done = (d.songs || []).filter((x) => x.state === "done").slice(0, 6);
      $("muEarlier").hidden = !done.length;
      $("muEarlierList").innerHTML = done.map((x) => `<button class="chip chip-sm" type="button" data-song="${esc(x.song_id)}">${esc(x.label)}</button>`).join(" ");
      $("muEarlierList").querySelectorAll("[data-song]").forEach((b) => b.addEventListener("click", async () => show(await api(`/songs/${b.dataset.song}`))));
    } catch (_) { /* no list is fine */ }
  }

  // ---------------------------------------------------------------- 1 · song job
  $("muGo").addEventListener("click", async () => {
    $("muStatus").textContent = "Starting…";
    $("muGo").disabled = true;
    try {
      const d = await api("/songs", { title: $("muTitle").value, lyrics: $("muLyrics").value, style: $("muStyle").value, model: $("muModel").value,
        seconds: Number($("muSeconds").value), seed: Number($("muSeed").value || 0), quality: quality() });
      track(d);
    } catch (e) { $("muStatus").textContent = e.message; $("muGo").disabled = false; }
  });
  $("muStop").addEventListener("click", async () => { if (st.song) track(await api(`/songs/${st.song.song_id}/cancel`, {})); });
  function track(d) {
    st.song = d;
    clearTimeout(st.poll);
    $("muStop").hidden = d.done;
    $("muStatus").textContent = d.state === "error" ? d.error : d.state === "cancelled" ? "Stopped." : d.done ? "" : d.stage;
    if (!d.done) { st.poll = setTimeout(async () => { try { track(await api(`/songs/${d.song_id}`)); } catch (e) { $("muStatus").textContent = e.message; } }, 900); return; }
    $("muGo").disabled = false;
    $("muGo").textContent = "Try another";
    if (d.state === "done") { show(d); earlier(); $("muSeed").value = String(Number(d.seed) + 1); }
  }

  // ---------------------------------------------------------------- 2 · beat map
  function show(d) {
    st.song = d;
    const bm = d.beatmap;
    $("muBeatCard").hidden = false;
    $("muAudio").hidden = !d.song_url;
    $("muNoAudio").hidden = !!d.song_url;
    if (d.song_url) { $("muAudio").src = d.song_url; $("muAudio").load(); } else $("muAudio").removeAttribute("src");
    const named = bm.sections.map((s) => s.name || `Section ${s.label}`);
    $("muStats").innerHTML = `<strong>${Math.round(bm.tempo_bpm)} BPM</strong> · ${bm.beats_per_bar}/4 · ${bm.bar_count} bars · ${bm.sections.length} sections · ${fmt(bm.duration_s)}`;
    const dur = bm.duration_s || 1;
    const pct = (t) => `${(100 * t / dur).toFixed(3)}%`;
    const secs = bm.sections.map((s, i) => `<div class="mu-sec e-${s.energy >= 0.66 ? "high" : s.energy >= 0.33 ? "mid" : "low"}" style="left:${pct(s.start_s)};width:${pct(s.end_s - s.start_s)}" title="${esc(named[i])}"><span>${esc(named[i])}</span></div>`).join("");
    const every = bm.bars.length > 48 ? 16 : bm.bars.length > 24 ? 8 : 4;
    const bars = bm.bars.map((t) => `<i class="mu-bar" style="left:${pct(t)}"></i>`).join("");
    const nums = bm.bars.map((t, i) => i % every === 0 ? `<span class="mu-barn" style="left:${pct(t)}">${i + 1}</span>` : "").join("");
    const beats = bm.beats.map((t) => `<i class="mu-beat" style="left:${pct(t)}"></i>`).join("");
    const lines = (d.lines || []).map((l) => `<b class="mu-line" style="left:${pct(l.start)};width:${pct(l.end - l.start)}" title="${esc(l.text)}"></b>`).join("");
    $("muMap").innerHTML = `<div class="mu-row mu-secs">${secs}</div><div class="mu-row mu-barnums" aria-hidden="true">${nums}</div><div class="mu-row mu-ticks">${beats}${bars}</div><div class="mu-row mu-lines">${lines}</div>
      <div class="mu-legend"><span><i class="k k-sec"></i>Sections</span><span><i class="k k-bar"></i>Bars</span><span><i class="k k-line"></i>Sung lines</span></div>`;
    const src = { preview: "Preview timing", model: "Line times from the song model", estimated: "Line times estimated (spread evenly)" }[d.lrc_source] || "";
    $("muBeatNote").textContent = [d.beat_backend === "beat_this" ? "Beats by beat_this." : "Beats found by OpenSoul’s built-in beat finder.", src && `${src}.`, d.stems_note].filter(Boolean).join(" ");
    cut(d);
    send().then(() => restoreHandoff(d));
  }

  // ---------------------------------------------------------------- 3 · shot list
  const quality = () => (view.querySelector("[data-q].active") || {}).dataset?.q || "final";
  view.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
    view.querySelectorAll("[data-q]").forEach((x) => { const on = x === b; x.classList.toggle("active", on); x.setAttribute("aria-selected", String(on)); });
    recut();
  }));
  $("muBars").addEventListener("change", recut);
  async function recut() {
    if (!st.song || st.song.state !== "done") return;
    try { const d = await api(`/songs/${st.song.song_id}/cut`, { quality: quality(), bars_per_shot: $("muBars").value ? Number($("muBars").value) : null }); st.song = d; cut(d); }
    catch (e) { $("muSendStatus").textContent = e.message; }
  }
  const secName = (x) => (x && x.length > 1 ? x.charAt(0).toUpperCase() + x.slice(1) : `Section ${x}`);
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  function tile(url, poster, placeholder, label) {
    // Same aspect as the story (the Shots cards); a placeholder shows a tile, never an empty black player.
    if (placeholder || !url) return `<div class="mu-tile ${st.ar}"><span>${esc(label)}</span>${url ? `<button class="btn-link mu-play" type="button" data-src="${esc(url)}">Play</button>` : ""}</div>`;
    return `<video class="mu-tile ${st.ar}" src="${esc(url)}"${poster ? ` poster="${esc(poster)}"` : ""} controls playsinline preload="metadata"></video>`;
  }
  view.addEventListener("click", (e) => {
    const b = e.target.closest(".mu-play");
    if (!b) return;
    const box = b.closest(".mu-tile");
    box.outerHTML = `<video class="mu-tile ${st.ar}" src="${esc(b.dataset.src)}" controls playsinline autoplay></video>`;
  });
  function cut(d) {
    $("muCutCard").hidden = false;
    const list = d.cut || [];
    $("muShots").innerHTML = list.map((c) => `<li class="mu-shot${c.lipsync ? " sings" : ""}">
        <span class="mu-n">${c.index}</span>
        <span class="mu-t">${fmt(c.start_s)}–${fmt(c.end_s)}<small>${(c.frames / 24).toFixed(1)} s · ${esc(c.bars_label || "")}${c.start_bar ? ` · from bar ${c.start_bar}` : ""}</small>
          <small class="mu-mobile">${esc(secName(c.section))} · ${esc(c.camera_label || c.camera)}</small></span>
        <span class="mu-sect">${esc(secName(c.section))}</span>
        <span class="mu-cam">${esc(c.camera_label || c.camera)}</span>
        <span class="mu-sing">${c.lipsync ? `<em>Sings</em> ${esc(c.lyric || "")}` : "<span class='hint'>Cutaway, no singing</span>"}</span>
      </li>`).join("");
  }

  // ---------------------------------------------------------------- 4 · hand-off, lip-sync, export
  async function send() {
    $("muSendCard").hidden = false;
    try {
      const cast = (await (await fetch("/api/cast")).json()).cast || [];
      $("muWho").innerHTML = cast.length ? cast.map((c) => `<option>${esc(c.name)}</option>`).join("") : `<option value="">Make a character first</option>`;
      $("muSend").disabled = !cast.length;
      const ps = (await (await fetch("/api/storyboard/projects")).json()).projects || [];
      $("muStory").innerHTML = `<option value="">New story</option>` + ps.filter((p) => !p.demo).map((p) => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join("");
      if (st.wantStory && ps.some((p) => p.id === st.wantStory && !p.demo)) $("muStory").value = st.wantStory;  // Shots > Start from a song
    } catch (_) { /* leave as is */ }
  }
  $("muSend").addEventListener("click", async () => {
    // OS-033: this song already has shots in the picked story. Ask before a second copy of every shot goes in.
    const pid = $("muStory").value;
    if (pid && (st.handoffs || []).some((h) => h.project_id === pid)
      && !confirm("This story already has the shots for this song. Add a second copy of every shot?")) return;
    $("muSendStatus").textContent = "Making shots…";
    try {
      const d = await api(`/songs/${st.song.song_id}/handoff`, { character: $("muWho").value, project_id: pid, idea: $("muIdea").value });
      st.handoffs = [d].concat((st.handoffs || []).filter((h) => h.project_id !== d.project_id));
      afterHandoff(d);
    } catch (e) { $("muSendStatus").textContent = e.message; }
  });
  // After "Make these shots", and after a reload when the song already has shots in a story (OS-033).
  function afterHandoff(d) {
    st.handoff = d;
    st.ar = d.aspect === "9:16" ? "ar-916" : "ar-169";
    $("muAfter").hidden = false;
    $("muResult").hidden = true;
    $("muExportStatus").textContent = "";
    const sung = d.shots.filter((s) => s.lipsync);
    $("muSendStatus").textContent = d.restored
      ? `This song has ${plural(d.shots.length, "shot")} in “${d.title}”. Render them. Then export the music video.`
      : `Made ${plural(d.shots.length, "shot")} in “${d.title}”; ${singingCount(sung.length)}.${d.note ? " " + d.note : ""}`;
    $("muSend").textContent = "Make these shots again";
    // Which audio the sync uses, next to the Sync buttons: the full mix unless the optional splitter is installed.
    const studio = (st.models && st.models.stems_studio) || {};
    $("muStemNote").textContent = (studio.available ? studio.note + " " : "This studio has no vocal-only track, so the full song drives the mouth. ")
      + "LTX audio+video renders each sung shot with its part of the song.";
    $("muStemNote").hidden = !sung.length;
    $("muSung").innerHTML = sung.length ? sung.map((s) => `<li data-shot="${esc(s.id)}"><span class="mu-sb">${esc(s.beat)}</span><span class="mu-sbtn"><button class="btn btn-ghost btn-sm" type="button" data-sync="${esc(s.id)}">Render sung take</button></span><span class="mu-lipst hint"></span><span class="mu-lipv"></span></li>`).join("")
      : `<li class="hint">No sung shots in this cut.</li>`;
    $("muSung").querySelectorAll("[data-sync]").forEach((b) => b.addEventListener("click", () => sync(b.dataset.sync, b)));
  }
  async function restoreHandoff(d) {
    st.handoff = null; st.handoffs = [];
    $("muAfter").hidden = true;
    $("muSend").textContent = "Make these shots";
    $("muSendStatus").textContent = "";
    if (!(d.handoffs || []).length) return;
    try {
      const r = await api(`/songs/${d.song_id}/handoffs`);
      st.handoffs = r.handoffs || [];
      if (!st.handoffs.length || !st.song || st.song.song_id !== d.song_id) return;
      const h = st.handoffs[0];
      const sel = $("muStory");
      if (![...sel.options].some((o) => o.value === h.project_id)) sel.insertAdjacentHTML("beforeend", `<option value="${esc(h.project_id)}">${esc(h.title)}</option>`);
      sel.value = h.project_id;
      afterHandoff(h);
    } catch (_) { /* the hand-off button still works */ }
  }
  $("muStory").addEventListener("change", () => {
    const h = (st.handoffs || []).find((x) => x.project_id === $("muStory").value);
    if (h) afterHandoff(h);
    else { st.handoff = null; $("muAfter").hidden = true; $("muSend").textContent = "Make these shots"; $("muSendStatus").textContent = ""; }
  });
  // The result line counts the Sync rows below it: "3 have singing to sync", "1 has …", "none have …".
  function singingCount(n) {
    return n === 0 ? "none have singing to sync" : n === 1 ? "1 has singing to sync" : `${n} have singing to sync`;
  }
  // OS-023: a sung shot renders with LTX audio+video from its slice of the song (no LatentSync). It is a normal
  // Final take of the shot, so it shows in Shots and Review and can be the keeper.
  async function sync(shotId, b) {
    const li = b.closest("li");
    const out = li.querySelector(".mu-lipst");
    b.disabled = true;
    try {
      const pid = st.handoff.project_id;
      const p = await (await fetch(`/api/storyboard/projects/${encodeURIComponent(pid)}`)).json();
      const shot = (p.shots || []).find((x) => x.id === shotId);
      const r = await fetch(`/api/storyboard/projects/${encodeURIComponent(pid)}/shots/${encodeURIComponent(shotId)}/regenerate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quality: "final", lipsync: true, from_version: (shot && shot.keeper) || null }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong. Try again.");
      out.textContent = "OpenSoul renders the sung take. Open the shots to see it.";
    } catch (e) { out.textContent = e.message; }
    b.disabled = false;
  }
  $("muOpenStory").addEventListener("click", () => {
    const sb = window.OpenSoulStoryboard;
    close();
    const t = document.querySelector('#ufTabs [data-tab="shots"]');
    if (sb && st.handoff) sb.api(`/projects/${encodeURIComponent(st.handoff.project_id)}`).then((p) => { sb.setProject(p); if (t) t.click(); }).catch(() => { if (t) t.click(); });
    else if (t) t.click();
  });
  $("muExport").addEventListener("click", async () => {
    $("muExportStatus").textContent = "Making the video…";
    $("muExport").disabled = true;
    try {
      const d = await api(`/songs/${st.song.song_id}/export`, { project_id: st.handoff.project_id, keep_lines: $("muKeepLines").checked, vertical: $("muVertical").checked });
      $("muExportStatus").textContent = d.note || "";
      $("muResult").hidden = false;
      const ar = st.ar; st.ar = d.aspect === "9:16" ? "ar-916" : "ar-169";  // OS-040: a vertical cut shows tall
      const t = tile(d.output_url, d.poster_url, d.preview, "Preview export"); st.ar = ar;
      $("muResult").innerHTML = `${t}<a class="btn btn-secondary btn-icon" href="${esc(d.download_url)}" download><svg><use href="#i-down"/></svg>Download MP4 · ${d.seconds} s</a>`;
    } catch (e) { $("muExportStatus").textContent = e.message; }
    $("muExport").disabled = false;
  });

  if (new URLSearchParams(location.search).get("music") === "1") setTimeout(open, 0);
})();
