/* Storyboard + Export. Flow: Create (characters) → Storyboard (shots) → Export (keepers stitched in order).
   Every shot is the user's own: name/rename inline, add, delete (with Undo), reorder, cast from their own characters. */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const API = "/api/storyboard";
  const sb = { projects: [], project: null, openShot: null, viewing: null, cameras: [], dragId: null, mode: null, quality: "draft",
    cast: [], templates: [], view: "create", draft: null, returnTo: null };
  const same = (a, b) => String(a).toLowerCase() === String(b).toLowerCase();
  const listNames = (a) => a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  // P2-13 / P2-14: a slow answer gets a "still working" note; a stopped server gets a plain message, not "Failed to fetch".
  const OFFLINE = "OpenSoul isn’t answering. Is it still running? Open it again. Then try again.";
  async function api(path, opts = {}) {
    const isForm = opts.body instanceof FormData;
    const slow = opts.method && opts.method !== "GET" ? setTimeout(() => toast("Still working… Long renders can take several minutes.", true), 15000) : null;
    let r;
    try { r = await fetch(API + path, { ...(isForm ? {} : { headers: { "Content-Type": "application/json" } }), ...opts }); }
    catch (e) {
      document.dispatchEvent(new CustomEvent("os:offline"));
      throw new Error(OFFLINE);
    } finally { if (slow) { clearTimeout(slow); if (/^Still working/.test($("sbToast").textContent)) $("sbToast").hidden = true; } }
    let j = null;
    try { j = await r.json(); } catch (_) { /* empty */ }
    if (!r.ok) throw new Error((j && j.detail) || `Something went wrong (${r.status}).`);
    return j;
  }
  const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
  const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body || {}) });

  // ---------------------------------------------------------------- views: create | storyboard | export
  function setView(v) {
    if (sb.view !== v) { clearTimeout(toast._t); $("sbToast").hidden = true; }  // a note about the last view doesn't follow you
    sb.view = v;
    const on = v === "storyboard" || v === "export";
    document.body.classList.toggle("view-storyboard", on);
    $("storyboardView").hidden = !on;
    $("sbBoard").hidden = v !== "storyboard";
    $("sbExportPane").hidden = v !== "export";
    $("sbBoardActions").hidden = v !== "storyboard";
    $("sbExportActions").hidden = v !== "export";
    document.querySelectorAll(".vs-btn").forEach((b) => {
      const a = b.dataset.view === v;
      b.classList.toggle("active", a);
      b.setAttribute("aria-pressed", String(a));
      if (a) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    const url = new URL(location.href);
    if (on) url.searchParams.set("view", v); else url.searchParams.delete("view");
    history.replaceState(null, "", url);
    if (on) loadCast();
    if (on && !sb.project) loadProjects(); else if (on) render();
  }

  // ---------------------------------------------------------------- cast (the user's characters)
  // Re-read whenever the Storyboard opens: characters made in Create since the page loaded show up.
  async function loadCast() {
    try {
      const d = await (await fetch(API + "/cast")).json();
      sb.cast = d.cast || [];
      try {  // OS-054/055: which voices and voice engines the studio has (null = not known: all are offered)
        const v = await (await fetch("/api/voices")).json();
        sb.voiceOff = new Set((v.voices || []).filter((x) => x.available === false).map((x) => x.id));
        sb.engines = v.engines || null;
      } catch (_) { sb.voiceOff = new Set(); sb.engines = null; }
      document.dispatchEvent(new CustomEvent("os:cast", { detail: sb.cast }));
      if (sb.project) render();
      if (sb.mode === "shot") renderSheet();
    } catch (_) { /* keep the last list */ }
  }

  // ---------------------------------------------------------------- projects
  async function loadProjects(selectId) {
    let projects, broken, preview;
    try { ({ projects, broken, preview } = await api("/projects")); }
    catch (e) {
      sb.projects = [];
      renderPicker(null);
      $("sbExport").disabled = true;
      toast(`Couldn't load your stories: ${esc(e.message)} Is the app still running?`, true);
      return;
    }
    sb.projects = projects;
    if (broken && broken.length) toast(`Couldn't open ${plural(broken.length, "story")}: ${esc(broken.map((b) => b.id).join(", "))}. The file may be from a newer or older version of OpenSoul.`, true);
    // OS-001: Preview mode opens the story its sample takes come from (Juno – Spin Cycle), unless you picked one.
    const pv = preview && projects.find((x) => x.preview_demo);
    const want = selectId || new URLSearchParams(location.search).get("story") || (pv && pv.id) || (projects[0] && projects[0].id);
    renderPicker(want);
    if (want) await openProject(want);
  }

  function renderPicker(sel) {
    $("sbProject").innerHTML = sb.projects.map((p) => `<option value="${esc(p.id)}" ${p.id === sel ? "selected" : ""}>${esc(p.title)}${p.demo ? " (demo)" : ""}</option>`).join("")
      + `<option value="__new">New story…</option>`;
  }

  async function openProject(id) {
    try { sb.project = await api(`/projects/${encodeURIComponent(id)}`); }
    catch (e) {
      if (sb.projects[0] && sb.projects[0].id !== id) {  // P2-05: say so; an old bookmark must not look like lost work
        const r = await openProject(sb.projects[0].id);
        toast(`OpenSoul cannot find the story “${esc(id)}”. Pick one from the Story list.`);
        return r;
      }
      throw e;
    }
    const url = new URL(location.href);
    url.searchParams.set("story", sb.project.id);
    history.replaceState(null, "", url);
    // OS-074: the Story list always names the story that is open (Shorts opened "Shorts" but the list still said the demo).
    if ([...$("sbProject").options].some((o) => o.value === sb.project.id)) $("sbProject").value = sb.project.id;
    $("sbExportResult").hidden = true;
    render();
    document.dispatchEvent(new CustomEvent("os:project", { detail: sb.project }));
  }

  function setProject(p) {
    sb.project = p; render(); if (sb.openShot && sb.mode === "shot") renderSheet(); if (sb.mode === "stage") renderStageSheet();
    document.dispatchEvent(new CustomEvent("os:project", { detail: p }));  // the six-tab shell (unified.js) listens
  }

  // ---------------------------------------------------------------- helpers
  function keeperOf(s) { return s.versions.find((v) => v.id === s.keeper) || null; }
  // A Preview take made from a sample clip of a real render (presets/preview_samples.json): it has real pictures.
  const isSample = (v) => !!(v && v.settings && v.settings.sample);
  function kindLabel(v) {
    if (v.kind === "concept") return /^Start frame/.test(v.note || "") ? "Frame" : "Concept";
    if (v.kind === "frame") return "Frame";
    if (v.kind === "preview") return "Preview";
    if (v.kind === "upload") return "Uploaded";  // OS-064
    if (v.kind === "card") return "Card";  // OS-063
    if (v.status !== "ready") return v.status;
    const q = (v.settings || {}).quality;
    return q === "final" ? "Final" : q === "draft" ? "Draft" : "Render";
  }
  const castOf = (name) => sb.cast.find((c) => same(c.name, name));
  function pendingNote(s) {
    const who = sb.cast.filter((c) => c.look_pending && s.characters.some((n) => same(n, c.name))).map((c) => c.name);
    return who.length ? `<p class="sb-pending">${esc(who.join(" and "))}${who.length > 1 ? "'s looks aren't" : "'s look isn't"} final yet. Frames you make now are only for tests.</p>` : "";
  }
  // OS-041: render time on the studio. Time in the studio queue is shown apart (tooltip and the take details).
  const dur = (t) => `${t < 90 ? Math.round(t) + " s" : (t / 60).toFixed(1) + " min"}`;
  function secs(v) { const t = (v.settings || {}).render_seconds; return t ? dur(t) : ""; }
  function queueNote(v) { const q = (v.settings || {}).queue_seconds; return q >= 5 ? `Waited ${dur(q)} in the studio queue before it started.` : ""; }
  function typicalSecs(q) {  // median of finished takes on THIS machine, so the estimate is honest
    const t = (sb.project ? sb.project.shots : []).flatMap((s) => s.versions)
      .filter((v) => v.status === "ready" && (v.settings || {}).quality === q && (v.settings || {}).render_seconds)
      .map((v) => v.settings.render_seconds).sort((a, b) => a - b);
    return t.length ? t[Math.floor(t.length / 2)] : null;
  }
  function etaText(q) {
    const t = typicalSecs(q);
    const name = q === "final" ? "A Final take" : "A Draft take";
    if (!t) return q === "final" ? "Final renders full size and length." : "Draft is a quick, smaller preview.";
    return `${name} takes about ${t < 90 ? Math.max(1, Math.round(t / 60)) + " min" : (Math.round(t / 30) / 2) + " min"} here.`;
  }
  // The picture shown for a character (display only): its audited card picture if presets/demo_images.json lists one.
  const cardPic = (c) => (c && (c.card_url || c.picture_url)) || "";
  const initial = (n) => esc(String(n).trim().charAt(0).toUpperCase() || "?");
  // A cast placeholder picture (presets/demo_images.json, while a design is rebuilt) is a tall figure that crops to a
  // blank grey circle at avatar size: show the character's initial instead.
  const hasPic = (c) => !!(c && c.picture_url && !c.card_placeholder);
  function face(n, cls = "") {
    const c = castOf(n);
    if (c && c.card_placeholder) return `<span class="sb-initial ${cls}" title="${esc(c.name)} (placeholder while being rebuilt)">${initial(c.name)}</span>`;
    return hasPic(c) ? `<img class="${cls}" src="${esc(cardPic(c))}" alt="" title="${esc(c.name)}" />`
      : `<span class="sb-initial ${cls}${c ? "" : " missing"}" title="${esc(n)}${c ? "" : " (not in your characters yet)"}">${initial(n)}</span>`;
  }
  function castHTML(s) {
    if (!s.characters.length) return `<span class="sb-nocast">No cast</span>`;
    return `<div class="sb-cast" aria-label="Cast: ${esc(s.characters.join(", "))}">${s.characters.slice(0, 4).map((n) => face(n)).join("")}</div>`;
  }
  const camLabel = (id) => { const c = sb.cameras.find((x) => x.id === id); return id === "static" || !c ? "Static" : c.label; };
  const movesOf = (s) => (s.camera_moves && s.camera_moves.length ? s.camera_moves : [s.camera || "static"]);
  /** Shot sheet camera: the same tiles as Create (tiles.js), up to 3 moves in order; a plain list if tiles.js is missing. */
  function camTilesHTML(s) {
    const T = window.OpenSoulTiles;
    const cams = sb.cameras.length ? sb.cameras : [{ id: "static", label: "Static" }];
    const moves = movesOf(s);
    const picked = moves.map((m) => cams.find((c) => c.id === m)).filter(Boolean);
    const max = (sb.cameraRules && sb.cameraRules.max_moves) || 3;
    const exp = picked.filter((c) => c.experimental);
    const stack = moves.length > 1;
    const tagNote = exp.length || stack
      ? `<span class="sb-cam-note"><span class="os-exp inline">Experimental</span> ${exp.length ? `${esc(exp.map((c) => c.label).join(" and "))} ${exp.length > 1 ? "aren't" : "isn't"} reliable yet.` : ""}${stack ? `${exp.length ? " " : ""}Stacked moves are new, and we did not check them on the GPU yet. Look at the take before you keep it.` : ""}</span>` : "";
    const order = stack ? `<p class="sb-cam-order">${picked.map((c, i) => `<button type="button" class="sb-move-chip" data-move="${esc(c.id)}" title="Show ${esc(c.label)} in the strip">${i + 1}. ${esc(c.label)}</button>`).join(`<span class="sb-move-then">then</span>`)}</p>` : "";
    const draft = sb.quality !== "final";
    // Length rules (camera_plan §4 rule 7; enforced on the server too): Draft takes 2 moves at most, lengthened to 5 s.
    const rules = draft && sb.cameraRules ? { ...sb.cameraRules, max_moves: Math.min(sb.cameraRules.max_moves || 3, 2),
      max_why: "Drafts take up to 2 camera moves. Switch to Final for a third." } : sb.cameraRules;
    const len = stack && draft && moves.length > 2 ? `<p class="sb-cam-len warn" id="sbCamLen">Drafts take up to 2 camera moves. Switch to <strong>Final</strong> for all ${moves.length}, or remove one.</p>`
      : stack ? `<p class="sb-cam-len" id="sbCamLen">${draft ? "Draft lengthened to 5 s, so both moves have room." : moves.length > 2 ? `Final: at least 7 s, so all ${moves.length} moves have room.` : "Final: at least 5 s, so both moves have room."}</p>` : "";
    return `<div class="sb-section sb-cams"><p class="sb-label" id="sbCamH">Camera <span class="sb-cam-hint">Click up to ${max} moves in the order you want them.</span></p>${T && T.multiHTML ? T.multiHTML(cams, { selected: moves, rules, name: "Camera moves" })
      : `<select id="sbCam" aria-labelledby="sbCamH">${camOptions(s.camera)}</select>`}${order}${len}${tagNote}<p class="sb-cam-why" id="sbCamWhy" role="status" aria-live="polite"></p></div>`;
  }
  function wireCamTiles(root, s, save) {
    const T = window.OpenSoulTiles;
    const cams = sb.cameras;
    if (T && T.wireMulti && root.querySelector(".os-tiles.multi")) {
      T.wireMulti(root, movesOf(s), sb.cameraRules, {
        onChange: (moves) => save(moves.length > 1 ? { camera_moves: moves } : { camera: moves[0] },
          `Camera: ${esc(moves.map(camLabel).join(" → "))}.`),
        onHint: (why) => { const w = $("sbCamWhy"); if (w) w.textContent = why || ""; },  // the one place a clash reason shows (no tooltip)
        list: cams,
      });
      // A chip scrolls its tile into view (a third move can sit past the edge of the strip).
      root.querySelectorAll(".sb-cam-order [data-move]").forEach((c) => c.addEventListener("click", () => {
        const t = root.querySelector(`.sb-cams .os-tile[data-id="${CSS.escape(c.dataset.move)}"]`);
        if (!t) return;
        t.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
        t.classList.add("flash"); setTimeout(() => t.classList.remove("flash"), 900);
      }));
    } else if ($("sbCam")) $("sbCam").addEventListener("change", (e) => save({ camera: e.target.value }, `Camera: ${esc(camLabel(e.target.value))}.`));
  }
  function movesChipsHTML(s) {
    const m = movesOf(s);
    const exp = m.length > 1 || m.some((id) => (sb.cameras.find((c) => c.id === id) || {}).experimental);
    return `<div class="sb-moves" aria-label="Camera moves">${m.map((id, i) => `<span class="sb-move-chip">${m.length > 1 ? `${i + 1}. ` : ""}${esc(camLabel(id))}</span>`).join("")}${exp ? `<span class="os-exp inline">Experimental</span>` : ""}</div>`;
  }
  const camOptions = (sel) => (sb.cameras.length ? sb.cameras : [{ id: "static", label: "Static" }])
    .map((c) => `<option value="${esc(c.id)}" ${c.id === sel ? "selected" : ""}>${esc(c.id === "static" ? "Static (no move)" : c.label)}</option>`).join("");

  // ---------------------------------------------------------------- header + strip
  function render() {
    const p = sb.project;
    if (!p) return;
    // One keeper count everywhere (header, Review, Export): Preview takes count as keepers and are named as such.
    const all = p.shots.map(keeperOf).filter(Boolean), kept = all.filter((k) => !k.unapproved);  // demo takes not approved don't count
    const real = kept.filter((k) => !k.placeholder && !k.missing);
    const previews = kept.length - real.length;
    const hidden = !kept.length && all.length;
    if (document.activeElement !== $("sbTitle")) $("sbTitle").value = p.title;
    if ($("sbLook")) $("sbLook").value = p.look || "";
    if ($("sbFixCam")) $("sbFixCam").checked = !!p.fix_camera;
    if ($("sbAvoid") && document.activeElement !== $("sbAvoid")) $("sbAvoid").value = p.avoid || "";  // OS-068
    if ($("sbAvoidDefaults")) $("sbAvoidDefaults").checked = p.avoid_defaults !== false;
    if ($("sbAvoidList")) $("sbAvoidList").textContent = p.avoid_defaults !== false && (p.avoid_default_items || []).length ? `Famous design traits: ${p.avoid_default_items.join("; ")}.` : "";
    const names = [...new Set(p.shots.flatMap((s) => s.characters))];
    const finals = real.filter((k) => (k.settings || {}).quality === "final").length;
    const who = names.length ? `Cast: ${names.slice(0, 5).join(", ")}${names.length > 5 ? ` +${names.length - 5}` : ""}` : "No cast yet";
    $("sbSub").textContent = [who, plural(p.shots.length, "shot"), hidden ? "No approved takes yet" : plural(kept.length, "keeper") + (previews ? ` (${previews === kept.length ? "all" : previews} from Preview mode)` : ""), finals ? `${finals} final` : "", p.dry_run ? "Preview mode" : ""].filter(Boolean).join(" · ");
    const empty = p.shots.length === 0;
    $("sbEmpty").hidden = !empty;
    $("sbStrip").hidden = empty;
    $("sbHint").hidden = empty;
    $("sbToExport").disabled = empty;
    $("sbStrip").innerHTML = p.shots.map(cardHTML).join("") + `<li class="sb-add-li"><button class="sb-add" id="sbAdd" type="button"><div><span>+</span>Add shot</div></button></li>`;
    $("sbAdd").addEventListener("click", openNew);
    $("sbStrip").querySelectorAll(".sb-card").forEach(wireCard);
    stripArrows();
    renderStages();
    if (sb.view === "export") renderExport();
  }

  /** The shot row scrolls sideways: a soft fade at the edge plus an arrow while more cards are off-screen. */
  function stripArrows() {
    const st = $("sbStrip"), l = $("sbStripL"), r = $("sbStripR");
    if (!st || !l || !r) return;
    const sync = () => {
      const more = st.scrollWidth - st.clientWidth - st.scrollLeft > 4;
      r.hidden = st.hidden || !more; l.hidden = st.hidden || st.scrollLeft < 4;
      st.classList.toggle("more-right", more); st.classList.toggle("more-left", st.scrollLeft >= 4);
    };
    if (!st.dataset.arrows) {
      st.dataset.arrows = "1";
      st.addEventListener("scroll", sync, { passive: true });
      window.addEventListener("resize", sync);
      const step = (d) => st.scrollBy({ left: d * Math.max(260, st.clientWidth * 0.8), behavior: "smooth" });
      l.addEventListener("click", () => step(-1)); r.addEventListener("click", () => step(1));
    }
    requestAnimationFrame(sync);
  }

  function cardHTML(s, i) {
    const real = keeperOf(s);
    // Demo data: a keeper with no approved picture shows the plain "No take yet" card (no badges, no take count).
    const k = real && real.card_blank ? null : real;
    const img = k && (k.card_url || k.poster_url);
    const pills = k && !k.unapproved ? `<span class="sb-pill">${esc(kindLabel(k))}</span><span class="sb-pill right keeper">${esc(k.id)}</span>` : "";
    // Every shot with a take shows a real frame: its poster, else the clip's first frame; a lost file says so.
    const thumb = k && k.missing
      ? `<div class="sb-thumb none missing"><div><span class="sb-plus">!</span>Video missing<small>The file for ${esc(k.id)} isn't on this computer.</small></div><span class="sb-pill right keeper">${esc(k.id)}</span></div>`
      // A Preview placeholder (a name card with text) never shows as the card picture: a clean blank frame instead.
      : k && k.placeholder && !k.card_audited && !isSample(k) ? `<div class="sb-thumb blank" aria-label="Preview, no picture yet">${pills}</div>`
      : img ? `<div class="sb-thumb"><img src="${esc(img)}" alt="" draggable="false" />${pills}</div>`
      : k && k.video_url ? `<div class="sb-thumb"><video src="${esc(k.video_url)}#t=0.1" muted playsinline preload="metadata" aria-hidden="true"></video>${pills}</div>`
      : `<div class="sb-thumb none"><div><span class="sb-plus">+</span>No take yet</div></div>`;
    const n = real && real.unapproved ? 0 : s.versions.filter((v) => !v.unapproved).length;  // count approved takes only
    // Same words as the header and Review: a Preview take that is kept is a keeper; only a lost file says so.
    const kWord = k && k.missing ? "lost keeper" : "keeper";
    const takes = n ? `${plural(n, "take")}${k ? ` · ${kWord} ${esc(k.id)}` : ""}` : movesOf(s).length > 1 ? `${movesOf(s).length} camera moves` : "";
    const last = sb.project.shots.length - 1;
    return `<li class="sb-card" draggable="true" tabindex="0" data-id="${esc(s.id)}" aria-label="Shot ${i + 1}: ${esc(s.beat)}">
      ${thumb}
      <div class="sb-meta">
        <div class="sb-num-row"><span class="sb-num">Shot ${i + 1}</span>${castHTML(s)}</div>
        <input class="sb-beat" type="text" value="${esc(s.beat)}" title="${esc(s.beat)}" maxlength="120" aria-label="Name of shot ${i + 1}" spellcheck="false" />
        ${s.kind === "card" ? `<p class="sb-line">Title card: ${esc([s.card_title, s.card_sub].filter(Boolean).join(" · ")) || '<span class="sb-muted">no words yet</span>'}</p>`
          : `<p class="sb-line">${esc(s.prompt) || '<span class="sb-muted">Nothing described yet</span>'}</p>
        ${movesChipsHTML(s)}`}
        <div class="sb-card-foot"><p class="sb-takes">${takes}</p>
          <div class="sb-tools">
            <button type="button" data-act="left" aria-label="Move shot ${i + 1} earlier" title="Move earlier" ${i === 0 ? "disabled" : ""}><svg><use href="#i-left"/></svg></button>
            <button type="button" data-act="right" aria-label="Move shot ${i + 1} later" title="Move later" ${i === last ? "disabled" : ""}><svg><use href="#i-right"/></svg></button>
            <button type="button" data-act="del" aria-label="Delete shot ${i + 1}" title="Delete shot"><svg><use href="#i-trash"/></svg></button>
          </div></div>
      </div></li>`;
  }

  function wireName(input, s, after) {
    // Inline rename: Enter or leaving the field saves; Escape puts the old name back.
    const stop = (e) => e.stopPropagation();
    input.addEventListener("click", stop);
    input.addEventListener("mousedown", stop);
    input.addEventListener("focus", () => { const c = input.closest(".sb-card"); if (c) c.draggable = false; });
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") { e.preventDefault(); input.value = s.beat; input.blur(); }
    });
    input.addEventListener("blur", () => {
      if (input.hasAttribute("title")) input.title = input.value.trim() || s.beat;  // the tooltip keeps the full name
      const c = input.closest(".sb-card"); if (c) c.draggable = true;
      const v = input.value.replace(/\s+/g, " ").trim();
      if (!v) { input.value = s.beat; toast("A shot needs a name."); return; }
      if (v === s.beat) return;
      run(async () => { setProject(await patch(`/projects/${sb.project.id}/shots/${s.id}`, { beat: v })); if (after) after(); });
    });
  }

  function wireCard(el) {
    const id = el.dataset.id;
    const s = sb.project.shots.find((x) => x.id === id);
    wireName(el.querySelector(".sb-beat"), s);
    el.querySelectorAll(".sb-tools button").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const a = b.dataset.act;
      if (a === "del") deleteShot(id); else move(id, a === "left" ? -1 : 1);
    }));
    el.addEventListener("click", () => openShot(id));
    el.addEventListener("keydown", (e) => {
      if (e.target !== el) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openShot(id); }
      if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); move(id, e.key === "ArrowLeft" ? -1 : 1, true); }
      if (e.key === "Delete") { e.preventDefault(); deleteShot(id); }
    });
    el.addEventListener("dragstart", (e) => { sb.dragId = id; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", id); });
    el.addEventListener("dragend", () => { sb.dragId = null; clearDrop(); el.classList.remove("dragging"); });
    el.addEventListener("dragover", (e) => {
      if (!sb.dragId || sb.dragId === id) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      clearDrop();
      el.classList.add(e.clientX > r.left + r.width / 2 ? "drop-after" : "drop-before");
    });
    el.addEventListener("drop", async (e) => {
      e.preventDefault();
      const after = el.classList.contains("drop-after");
      clearDrop();
      const from = sb.dragId;
      if (!from || from === id) return;
      const order = sb.project.shots.map((x) => x.id).filter((x) => x !== from);
      order.splice(order.indexOf(id) + (after ? 1 : 0), 0, from);
      await run(async () => setProject(await post(`/projects/${sb.project.id}/reorder`, { order })));
    });
  }
  const clearDrop = () => document.querySelectorAll(".drop-before,.drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));

  async function move(id, delta, refocus) {
    await run(async () => setProject(await post(`/projects/${sb.project.id}/shots/${id}/move`, { delta })));
    if (refocus) { const el = document.querySelector(`.sb-card[data-id="${CSS.escape(id)}"]`); if (el) el.focus(); }
  }

  // Delete = gone from the story at once, with Undo. Its takes are kept, so Undo brings everything back.
  async function deleteShot(id) {
    const p = sb.project;
    const i = p.shots.findIndex((x) => x.id === id);
    const s = p.shots[i];
    if (!s) return;
    await run(async () => {
      setProject(await api(`/projects/${p.id}/shots/${id}?confirm=1`, { method: "DELETE" }));
      if (sb.mode === "shot" && sb.openShot === id) showSheet(false);
      toast(`Deleted “${esc(s.beat)}”${s.versions.length ? ` (${plural(s.versions.length, "take")} kept)` : ""}. <button class="sb-link" id="sbUndo" type="button">Undo</button>`, false, 9000);
      const u = $("sbUndo");
      if (u) u.addEventListener("click", () => run(async () => {
        setProject(await post(`/projects/${p.id}/shots/${id}/restore`, { index: i }));
        toast(`“${esc(s.beat)}” is back.`);
      }));
    });
  }

  async function run(fn) {
    try { await fn(); } catch (e) { toast(esc(e.message)); }
  }

  function toast(html, keep, ms) {
    const t = $("sbToast");
    t.innerHTML = html;
    t.hidden = false;
    clearTimeout(toast._t);
    if (!keep) toast._t = setTimeout(() => { t.hidden = true; }, ms || 6000);
  }

  // ---------------------------------------------------------------- story title (inline rename)
  // OS-006: the story's look. Stage plates, start frames and takes follow it.
  $("sbLook").addEventListener("change", (e) => {
    if (!sb.project) return;
    const look = e.target.value;
    run(async () => {
      setProject(await patch(`/projects/${sb.project.id}`, { look }));
      toast(`New pictures and takes in this story use the look: ${esc(e.target.options[e.target.selectedIndex].text)}.`);
    });
  });
  // OS-068: the story's Avoid list (original designs). It goes into every start frame and take of the story.
  $("sbAvoidBtn").addEventListener("click", (e) => {
    const open = e.currentTarget.getAttribute("aria-expanded") !== "true";
    e.currentTarget.setAttribute("aria-expanded", String(open));
    $("sbAvoidPop").hidden = !open;
    if (open) $("sbAvoid").focus();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sbAvoidPop").hidden) { $("sbAvoidPop").hidden = true; $("sbAvoidBtn").setAttribute("aria-expanded", "false"); } });
  document.addEventListener("click", (e) => { if (!$("sbAvoidPop").hidden && !$("sbAvoidBox").contains(e.target)) { $("sbAvoidPop").hidden = true; $("sbAvoidBtn").setAttribute("aria-expanded", "false"); } });
  $("sbAvoid").addEventListener("change", (e) => {
    if (!sb.project) return;
    run(async () => { setProject(await patch(`/projects/${sb.project.id}`, { avoid: e.target.value })); toast("Saved. New pictures and takes in this story avoid these things."); });
  });
  $("sbAvoidDefaults").addEventListener("change", (e) => {
    if (!sb.project) return;
    run(async () => { setProject(await patch(`/projects/${sb.project.id}`, { avoid_defaults: e.target.checked })); toast(e.target.checked ? "New pictures avoid famous design traits too." : "Only your own Avoid words are used now."); });
  });
  // OS-017: automatic camera re-renders cost GPU time and queue places, so they are off unless asked for.
  $("sbFixCam").addEventListener("change", (e) => {
    if (!sb.project) return;
    const fix_camera = e.target.checked;
    run(async () => {
      setProject(await patch(`/projects/${sb.project.id}`, { fix_camera }));
      toast(fix_camera ? "OpenSoul renders a take again when its camera move looks wrong (up to 2 more times)."
                       : "One render for each take. A note tells you when the camera move looks wrong.");
    });
  });
  $("sbTitle").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); e.target.blur(); }
    if (e.key === "Escape") { e.target.value = sb.project.title; e.target.blur(); }
  });
  $("sbTitle").addEventListener("blur", (e) => {
    const v = e.target.value.replace(/\s+/g, " ").trim();
    if (!sb.project || v === sb.project.title) return;
    if (!v) { e.target.value = sb.project.title; return; }
    run(async () => {
      setProject(await patch(`/projects/${sb.project.id}`, { title: v }));
      const it = sb.projects.find((x) => x.id === sb.project.id); if (it) it.title = v;
      renderPicker(sb.project.id);
    });
  });

  // ---------------------------------------------------------------- sheet
  // The sheet is a modal (P1-06): Tab and Shift+Tab stay inside it, and closing returns focus to what opened it.
  let sheetOpener = null;
  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';
  function showSheet(on) {
    const was = !$("sbSheet").hidden;
    if (on && !was) sheetOpener = document.activeElement;
    $("sbSheet").hidden = !on;
    $("sbScrim").hidden = !on;
    document.body.style.overflow = on ? "hidden" : "";
    document.body.classList.toggle("os-modal", !!on);
    if (!on) {
      sb.openShot = null; sb.mode = null; sb.returnTo = null; sb.openStage = null;
      if (was && sheetOpener && sheetOpener.isConnected && sheetOpener.focus) sheetOpener.focus();
      sheetOpener = null;
    }
  }
  $("sbSheet").addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const all = [...$("sbSheet").querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!all.length) return;
    const first = all[0], last = all[all.length - 1];
    if (e.shiftKey && (document.activeElement === first || !$("sbSheet").contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  document.addEventListener("focusin", (e) => {  // focus can't land behind the scrim (e.g. a click on the page edge)
    if (!$("sbSheet").hidden && !$("sbSheet").contains(e.target) && !e.target.closest("dialog, #sbToast")) {
      const f = $("sbSheet").querySelector(FOCUSABLE);
      if (f) f.focus();
    }
  });
  function sheetHead(eyebrow, title) {
    $("sbSheetEyebrow").textContent = eyebrow;
    $("sbSheetTitle").textContent = title;
  }

  function openShot(id) {
    sb.openShot = id;
    sb.mode = "shot";
    const s = sb.project.shots.find((x) => x.id === id);
    sb.viewing = (keeperOf(s) || s.versions[s.versions.length - 1] || {}).id || null;
    renderSheet();
    showSheet(true);
    $("sbClose").focus();
  }

  function stageHTML(v, s) {
    if (!v) {
      const who = s.characters.filter((n) => castOf(n) && castOf(n).picture_url);
      const hint = who.length
        ? `Click <strong>New start frame</strong> to put ${esc(listNames(who))} in this shot. Then click <strong>Animate this frame</strong>.`
        : s.characters.length ? "Add pictures for this cast below. Or describe the shot. Then click Generate." : "Pick who’s in it below. Or describe the shot. Then click Generate.";
      return `<div class="sb-stage none"><div><strong>No take yet</strong><br />${hint}</div></div>`;
    }
    if (v.status === "rendering") return `<div class="sb-stage none"><div><strong>Rendering ${esc(v.id)}…</strong><br />Your other takes are safe.</div></div>`;
    if (v.status === "failed") return `<div class="sb-stage none"><div><strong>${esc(v.id)} didn’t render</strong><br />${esc(v.note)}</div></div>`;
    if (v.unapproved) return `<div class="sb-stage none unapproved"><div><strong>No approved take yet</strong><br />OpenSoul keeps this demo take but hides it until it passes review. Make a new take to see one here.</div></div>`;
    const pill = v.placeholder ? `<span class="sb-pill">${esc(v.label || "Placeholder")}</span>` : "";
    const keep = v.id === s.keeper && !v.unapproved ? `<span class="sb-pill right keeper">Keeper</span>` : "";
    // Keep the previous take's still behind the new one until it has loaded (no blank flash when switching takes).
    const prev = sb.lastStill && sb.lastStill !== v.poster_url ? sb.lastStill : "";
    const hold = prev ? ` loading` : "";
    const media = v.video_url
      ? `<video class="sb-media${hold}" src="${esc(v.video_url)}" poster="${esc(v.poster_url || "")}" autoplay muted loop playsinline></video>`
      : `<img class="sb-media${hold}" src="${esc(v.poster_url)}" alt="${esc(s.beat)}, take ${esc(v.id)}" />`;
    return `<div class="sb-stage"${prev ? ` style="background-image:url(&quot;${esc(prev)}&quot;)"` : ""}>${media}${pill}${keep}</div>`;
  }

  function wireStageHold(root, v) {
    const m = root.querySelector(".sb-media");
    if (v && v.poster_url) sb.lastStill = v.poster_url;
    if (!m || !m.classList.contains("loading")) return;
    const show = () => { m.classList.remove("loading"); };
    if ((m.tagName === "IMG" && m.complete && m.naturalWidth) || (m.tagName === "VIDEO" && m.readyState >= 2)) { show(); return; }
    m.addEventListener(m.tagName === "IMG" ? "load" : "loadeddata", show, { once: true });
    m.addEventListener("error", show, { once: true });
    setTimeout(show, 4000);  // never hide a take for long, even if the load event is missed
  }

  function filmHTML(s) {
    if (!s.versions.length) return "";
    return `<ol class="sb-film" aria-label="Takes">${s.versions.map((v) => {
      const t = v.poster_url ? `<div class="ft"><img src="${esc(v.poster_url)}" alt="" /></div>` : `<div class="ft none">${v.unapproved ? "Not approved" : v.status === "rendering" ? "Rendering…" : esc(v.status)}</div>`;
      const kind = kindLabel(v) + (secs(v) ? ` · ${secs(v)}` : "");
      const qn = queueNote(v);
      return `<li><button type="button" data-v="${esc(v.id)}" aria-current="${v.id === sb.viewing}"${qn ? ` title="Render ${esc(secs(v))}. ${esc(qn)}"` : ""}>${t}
        <span class="fl">${esc(v.id)} ${v.id === s.keeper && !v.unapproved ? '<span class="sb-badge">Keeper</span>' : `<em>${esc(kind)}</em>`}</span></button></li>`;
    }).join("")}</ol>`;
  }

  // Cast chips: the user's own characters (on/off), names in the shot that aren't saved yet, and "New character".
  function castPickHTML(names) {
    // "More examples" characters (Pixel) only show here once they are in the shot.
    const lib = sb.cast.filter((c) => !c.more_example || names.some((n) => same(n, c.name))).map((c) => {
      const on = names.some((n) => same(n, c.name));
      const pic = hasPic(c) ? `<img src="${esc(cardPic(c))}" alt="" />` : `<span class="sb-initial">${initial(c.name)}</span>`;
      const vars = c.variants || [];
      const varTip = vars.length ? `${c.name} also has ${vars.length} other saved version${vars.length > 1 ? "s" : ""}. This shot uses the main one.` : "";
      const tip = [c.look_pending ? `${c.name}: ${c.look_pending}` : "", varTip].filter(Boolean).join(" ");
      const badge = vars.length ? `<span class="sb-vars" aria-label="${vars.length} other saved version${vars.length > 1 ? "s" : ""}">+${vars.length}</span>` : "";
      return `<button type="button" class="sb-chip ${on ? "on" : ""}" data-name="${esc(c.name)}" aria-pressed="${on}" ${tip ? `title="${esc(tip)}"` : ""}>${pic}${esc(c.name)}${badge}</button>`;
    }).join("");
    const missing = names.filter((n) => !castOf(n)).map((n) =>
      `<span class="sb-chip ghost" title="${esc(n)} isn't in your characters yet"><span class="sb-initial missing">${initial(n)}</span>${esc(n)}
        <button type="button" class="sb-link sb-chip-act" data-add="${esc(n)}">Add picture</button><button type="button" class="sb-chip-x" data-drop="${esc(n)}" aria-label="Remove ${esc(n)} from this shot">×</button></span>`).join("");
    const none = !sb.cast.length ? `<p class="sb-empty-line">You haven’t saved any characters yet. Add one from a picture or a character sheet.</p>` : "";
    return `${none}${lib}${missing}<button type="button" class="sb-chip add" data-new="1"><span class="sb-plus-sm">+</span>New character</button>`;
  }
  // Voice per character (built-in Orpheus voices): one pick per cast member, used for every line they speak.
  const VOICES = [["tara", "Tara · warm"], ["leah", "Leah · composed"], ["jess", "Jess · bright"], ["mia", "Mia · soft"],
    ["zoe", "Zoe · breezy"], ["zac", "Zac · boyish"], ["leo", "Leo · deep"], ["dan", "Dan · easygoing"]];
  // Stage picker: the shot's stage (a location's stage sheet) and which angle of it. Start frames are edited from that plate.
  function stagePickHTML(s) {
    const locs = sb.project.locations || [];
    const v = s.versions.find((x) => x.id === sb.viewing);
    const fromTake = v && v.status === "ready" && v.poster_url && !v.shipped ? `<button type="button" class="sb-link" id="sbStageFromTake" data-from="${esc(s.id)}/${esc(v.id)}">New stage from ${esc(v.id)}</button>` : "";
    if (!locs.length) return `<div class="sb-section"><p class="sb-label">Stage</p><p class="sb-empty-line">No stage sheets in this story yet. A stage sheet keeps a place looking the same in every shot.</p>
      <p class="sb-stage-acts"><button type="button" class="sb-link" id="sbStageNew">New stage</button>${fromTake ? ` · ${fromTake}` : ""}</p></div>`;
    const loc = locs.find((l) => same(l.name, s.location || ""));
    const angles = loc ? [{ name: "", label: "Master (wide)", image_url: loc.image_url }, ...loc.angles.filter((a) => a.image_url).map((a) => ({ ...a, label: a.name }))] : [];
    const thumbs = angles.map((a) => `<button type="button" class="sb-angle${same(a.name, s.stage_angle || "") ? " on" : ""}" data-angle="${esc(a.name)}" aria-pressed="${same(a.name, s.stage_angle || "")}" title="${esc(a.label)}">
        ${a.image_url ? `<img src="${esc(a.image_url)}" alt="" loading="lazy" />` : ""}<span>${esc(a.label)}</span></button>`).join("");
    return `<div class="sb-section"><label class="sb-label" for="sbStage">Stage</label>
      <select id="sbStage"><option value="">No stage</option>${locs.map((l) => `<option value="${esc(l.name)}" ${same(l.name, s.location || "") ? "selected" : ""}>${esc(l.name)}${l.angle_count ? ` · ${plural(l.angle_count, "angle")}` : ""}</option>`).join("")}</select>
      ${thumbs ? `<div class="sb-angles" role="group" aria-label="Stage angle">${thumbs}</div>` : ""}
      ${loc && !loc.ready ? `<p class="sb-hint">This stage isn’t finished yet: ${esc(loc.readiness.filter((r) => !r.optional && !r.done).map((r) => r.label.toLowerCase()).join(", "))}.</p>` : ""}
      <p class="sb-stage-acts">${loc ? `<button type="button" class="sb-link" id="sbStageEdit" data-stage="${esc(loc.name)}">Edit ${esc(loc.name)}</button>` : ""}${loc && loc.sheet_url ? ` · <button type="button" class="sb-link" data-lightbox="${esc(loc.sheet_url)}" data-lb-title="Stage sheet · ${esc(loc.name)}">Open the stage sheet</button>` : ""}
        ${loc ? " · " : ""}<button type="button" class="sb-link" id="sbStageNew">New stage</button>${fromTake ? ` · ${fromTake}` : ""}</p></div>`;
  }
  function voicePickHTML(names) {
    const who = names.map((n) => castOf(n)).filter(Boolean);
    if (!who.length) return "";
    const off = sb.voiceOff || new Set();
    return `<div class="sb-section sb-voices"><p class="sb-label">Voices (for every shot)</p>${who.map((c) =>
      `<label class="sb-voice">${esc(c.name)} <select data-voice-for="${esc(c.name)}" aria-label="Voice for ${esc(c.name)} in every shot">${VOICES.map(([id, label]) =>
        `<option value="${id}" ${id === (c.voice || "tara") ? "selected" : ""} ${off.has(id) ? "disabled" : ""}>${esc(label)}${off.has(id) ? " (not on your studio)" : ""}</option>`).join("")}</select>${c.voice_label ? ` <span class="sb-hint">lip-sync label: ${esc(c.voice_label)}</span>` : ""}</label>`).join("")}
      <details class="sb-adv"><summary>Advanced: voice engine and voice clips</summary>
      <p class="sb-hint">New stories speak with VoxCPM2 in each character’s own voice clip (save one below, consent required). A character without a clip speaks with the Orpheus voice that you pick here. Orpheus voices, made on this computer <span class="lic-badge restricted" title="Llama 3.2 Community License: commercial use allowed; some uses prohibited.">Open weights, use-restricted</span>. In a line, add <code>&lt;sigh&gt;</code>, <code>&lt;laugh&gt;</code> or <code>&lt;chuckle&gt;</code> where it happens.</p>
      <label class="sb-voice">Voice engine for this story <select id="sbEngine" aria-label="Voice engine for this story">${ENGINES.map(([id, label]) => {
        const gone = sb.engines && sb.engines[id] === false;  // OS-054: an engine the studio doesn't have
        return `<option value="${id}" ${id === (sb.project.voice_engine || "orpheus") ? "selected" : ""} ${gone ? "disabled" : ""}>${esc(label)}${gone ? " (not on your studio)" : ""}</option>`;
      }).join("")}</select></label>${engineWarn()}
      ${who.map((c) => `<details class="sb-clip"><summary>${esc(c.name)}’s voice clip (Chatterbox, VoxCPM2)</summary>
        <form data-clip-for="${esc(c.name)}"><input type="file" name="clip" accept=".wav,audio/wav" required aria-label="5-15 second WAV of ${esc(c.name)}’s voice" />
        <input type="text" name="made_with" placeholder="How you made it (e.g. my own recording)" required aria-label="How you made the clip" />
        <input type="text" name="ref_text" placeholder="What the clip says (optional)" aria-label="What the clip says" />
        <label><input type="checkbox" name="consent" value="true" required /> This clip is my own voice, a voice I made, or a voice I have written permission to use. It is not a real person I am imitating.</label>
        <button type="submit" class="sb-link">Save clip</button></form></details>`).join("")}</details></div>`;
  }
  // OS-054: say it before a Final when the story's engine is not on the studio (the take then uses another one).
  function engineWarn() {
    const e = (sb.project && sb.project.voice_engine) || "orpheus";
    if (!sb.engines || sb.engines[e] !== false) return "";
    const alt = ["kokoro", "orpheus"].find((x) => sb.engines[x]);
    const name = (ENGINES.find(([id]) => id === e) || [e, e])[1].split(" (")[0];
    return `<p class="sb-hint sb-warn" role="status">${esc(name)} isn’t on your studio. ${alt ? `Talking takes use ${alt === "kokoro" ? "Kokoro" : "Orpheus"} instead. Pick it here to make it the story’s engine.` : "Install a voice engine on the studio first."}</p>`;
  }
  const ENGINES = [["voxcpm2", "VoxCPM2 (Apache-2.0, voice clip; default for new stories)"], ["orpheus", "Orpheus (named voices, tags)"], ["chatterbox", "Chatterbox (MIT, voice clip)"], ["kokoro", "Kokoro (small, fast)"]];
  function wireVoicePick(root) {
    const eng = root.querySelector("#sbEngine");
    if (eng) eng.addEventListener("change", async () => {
      try {
        const p = await patch(`/projects/${encodeURIComponent(sb.project.id)}`, { tts_engine: eng.value });
        sb.project.voice_engine = p.voice_engine;
        toast(`This story now speaks with ${esc(eng.options[eng.selectedIndex].text)}.`);
      } catch (e) { toast(esc(e.message)); }
    });
    root.querySelectorAll("form[data-clip-for]").forEach((f) => f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const name = f.dataset.clipFor;
      try {
        const r = await api(`/cast/${encodeURIComponent(name)}/voice-clip`, { method: "PUT", body: new FormData(f) });
        toast(`${esc(name)}’s voice clip is saved (${r.seconds} s).`);
      } catch (e) { toast(esc(e.message)); }
    }));
    root.querySelectorAll("select[data-voice-for]").forEach((sel) => sel.addEventListener("change", async () => {
      const name = sel.dataset.voiceFor;
      try {
        const r = await api(`/cast/${encodeURIComponent(name)}/voice`, { method: "PUT", body: JSON.stringify({ voice: sel.value }) });
        const c = castOf(name); if (c) c.voice = r.voice;
        toast(`${esc(name)} now speaks with ${esc(sel.options[sel.selectedIndex].text)}.`);
      } catch (e) { toast(esc(e.message)); }
    }));
  }
  // Dialogue: one spoken line per shot. Draft = the voice only; Final = LTX renders picture + mouth to the voice
  // (joint audio+video), or LatentSync re-mouths it afterwards. All lip-sync logic is server-side (opensoul/lipsync.py).
  const TAGS = ["laugh", "chuckle", "sigh", "gasp", "cough", "sniffle", "groan", "yawn"];
  const LIPSYNC = [["ltx_av", "LTX audio+video (joint)"], ["latentsync", "LatentSync 1.6 (after the video)"]];
  // Where the voice comes from, in one line: the character's own voice is the default; a shot override is Advanced.
  function voiceFromText(s, who, ownLabel) {
    const lab = (id) => esc((VOICES.find(([v]) => v === id) || [id, id])[1]);
    if (s.voice) return `Voice: ${lab(s.voice)} · this shot${who ? ` (character default: ${esc(ownLabel)})` : ""}`;
    return who ? `Voice: ${esc(who)}’s voice (${esc(ownLabel)}) · from the character` : "Voice: default (Tara) · pick who speaks";
  }
  function dialogueHTML(s) {
    const cast = s.characters;
    const who = s.speaker || (cast.length === 1 ? cast[0] : "");
    const own = who ? ((castOf(who) || {}).voice || "tara") : "tara";
    const ownLabel = (VOICES.find(([id]) => id === own) || [own, own])[1];
    return `<div class="sb-section sb-dialogue"><label class="sb-label" for="sbLine">What they say</label>
      <textarea id="sbLine" rows="2" maxlength="500" aria-describedby="sbLineLen" placeholder="e.g. Whole milk. <chuckle> Obviously.">${esc(s.line || "")}</textarea>
      <p class="sb-hint" id="sbLineLen" aria-live="polite"></p>
      <div class="sb-dia-tools"><div class="sb-tags" role="group" aria-label="Insert a sound at the cursor">${TAGS.map((t) => `<button type="button" class="sb-chip sb-tag" data-tag="${t}" title="Insert &lt;${t}&gt; at the cursor">&lt;${t}&gt;</button>`).join("")}</div>
        <button type="button" class="btn btn-outline-sb btn-sm-sb" id="sbSpeak" ${s.line ? "" : "disabled"}>Speak</button></div>
      <audio id="sbSpeakAudio" controls hidden></audio>
      <div class="sb-dia-grid">
        <label for="sbSpeaker">Spoken by</label>
        <select id="sbSpeaker">${cast.length > 1 || !cast.length ? `<option value="">${cast.length ? "Pick who speaks" : "Nobody in this shot"}</option>` : ""}${cast.map((n) => `<option value="${esc(n)}" ${same(n, who) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        <label class="sb-check" for="sbLipsync"><input type="checkbox" id="sbLipsync" ${s.lipsync !== false ? "checked" : ""} /> Lip-sync</label><span></span>
        <label for="sbSeconds">Length (s)</label>
        <input type="number" id="sbSeconds" min="0" max="20" step="0.5" inputmode="decimal" placeholder="Auto" aria-describedby="sbSecondsHint" value="${s.seconds ? esc(String(s.seconds)) : ""}" />
      </div>
      <p class="sb-hint" id="sbSecondsHint">Length of this shot in the story. Auto: a talking shot uses the line and a short pause. With a longer length, the mouth stays closed after the line. The export cuts the shot to this length.</p>
      <p class="sb-voice-from" id="sbVoiceFrom">${voiceFromText(s, who, ownLabel)}</p>
      <details class="sb-adv" ${s.voice || s.lipsync_backend === "latentsync" ? "open" : ""}><summary>Advanced</summary>
        <label for="sbLipsyncBackend">Lip-sync with</label>
        <select id="sbLipsyncBackend" ${s.lipsync !== false ? "" : "disabled"}>${LIPSYNC.map(([id, label]) => `<option value="${id}" ${(s.lipsync_backend || "ltx_av") === id ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>
        <span class="sb-hint">LTX joint audio+video renders the mouth with the picture. LatentSync redraws the speaker’s mouth after the video.</span>
        <label for="sbLineVoice">Voice for this shot only</label>
        <select id="sbLineVoice"><option value="" ${s.voice ? "" : "selected"}>${who ? `${esc(who)}’s voice (${esc(ownLabel)})` : "Default voice (Tara)"}</option>${VOICES.map(([id, label]) => `<option value="${id}" ${s.voice === id ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>
        <span class="sb-hint">Change a character’s voice for every shot in Characters.</span>
        <label class="sb-check" for="sbMouthRefine"><input type="checkbox" id="sbMouthRefine" ${s.mouth_refine ? "checked" : ""} /> Mouth refine (LatentSync), can make lips paler</label>
        <span class="sb-hint">Off by default: camera-locked takes keep the LTX mouth. Select it for a second mouth pass.</span></details>
      <p class="sb-hint" id="sbLipHint">${esc(lipHint(s))}</p>${s.line ? engineWarn() : ""}</div>`;
  }
  // OS-043: say what the Final really does with the mouth. Engine: LTX audio+video (the voice or the song drives it).
  function lipHint(s) {
    const on = s.lipsync !== false;
    const m = s.music;
    if (!s.line && m && m.sings) return on
      ? `This shot sings: “${m.lyric || "a line of the song"}”. Final: LTX audio+video moves the mouth to the song. Draft: no song.`
      : "Lip-sync is off: the song plays over the picture. Write closed lips in What happens.";
    if (!s.line) return "No line: Final makes the picture only. Add a line to make the character talk.";
    if (!on) return "Lip-sync is off: Final puts the voice over the picture.";
    return s.lipsync_backend === "latentsync"
      ? "Draft: voice only. Final: LTX audio+video, then LatentSync redraws the mouth."
      : "Draft: voice only, no lip-sync. Final: LTX audio+video moves the mouth to the voice.";
  }
  function wireDialogue(root, s, save, base) {
    const ta = root.querySelector("#sbLine");
    if (!ta) return;
    root.querySelectorAll(".sb-tag").forEach((b) => b.addEventListener("mousedown", (e) => e.preventDefault()));
    root.querySelectorAll(".sb-tag").forEach((b) => b.addEventListener("click", () => {
      const tag = `<${b.dataset.tag}>`;
      const a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
      const pre = ta.value.slice(0, a), post = ta.value.slice(z);
      const ins = (pre && !/\s$/.test(pre) ? " " : "") + tag + (post && !/^\s/.test(post) ? " " : "");
      ta.focus(); ta.setSelectionRange(a, z);
      // insertText goes through the browser's edit history, so Ctrl+Z / Cmd+Z undoes the chip like typing would.
      let ok = false;
      try { ok = document.execCommand && document.execCommand("insertText", false, ins); } catch (e) { ok = false; }
      if (!ok) { ta.setRangeText(ins, a, z, "end"); ta.dispatchEvent(new Event("input", { bubbles: true })); }
      const at = a + ins.length;
      ta.setSelectionRange(at, at);
      root.querySelector("#sbSpeak").disabled = !ta.value.trim();
    }));
    // P2-08: a soft length check. About 2.5 spoken words a second; a shot is about 6 seconds.
    const lineLen = () => {
      const words = ta.value.replace(/<[a-z]+>/g, " ").split(/\s+/).filter(Boolean).length;
      const secs = Math.round(words / 2.5);
      $("sbLineLen").textContent = !words ? "" : secs > 6
        ? `About ${secs} s of speech. A shot is about 6 s. Use two shots for a longer line.`
        : `About ${Math.max(1, secs)} s of speech.`;
      $("sbLineLen").classList.toggle("sb-warn", secs > 6);
    };
    lineLen();
    ta.addEventListener("input", () => { root.querySelector("#sbSpeak").disabled = !ta.value.trim(); lineLen(); });
    ta.addEventListener("blur", (e) => {
      if (e.relatedTarget && e.relatedTarget.classList && e.relatedTarget.classList.contains("sb-tag")) return;
      if (ta.value.trim() !== (s.line || "")) save({ line: ta.value }, ta.value.trim() ? "Line saved." : "Line removed.");
    });
    root.querySelector("#sbSpeaker").addEventListener("change", (e) => save({ speaker: e.target.value }, e.target.value ? `${esc(e.target.value)} says the line.` : ""));
    root.querySelector("#sbLineVoice").addEventListener("change", (e) => save({ voice: e.target.value }, e.target.value ? "Voice changed for this shot." : "Back to the character’s own voice."));
    root.querySelector("#sbLipsync").addEventListener("change", (e) => save({ lipsync: e.target.checked }, e.target.checked ? "Final takes will lip-sync." : "Lip-sync off: Final keeps the voice over the picture."));
    root.querySelector("#sbSeconds").addEventListener("change", (e) => {
      const v = parseFloat(e.target.value) || 0;  // OS-059: planned length of the talking take, 0 = automatic
      save({ seconds: v }, v ? `Talking take: ${v} s. The mouth stays closed after the line.` : "Talking take length: automatic.");
    });
    root.querySelector("#sbMouthRefine").addEventListener("change", (e) => save({ mouth_refine: e.target.checked }, e.target.checked ? "Mouth refine on for this shot (can make lips paler)." : "Mouth refine off: the take keeps the LTX mouth."));
    root.querySelector("#sbLipsyncBackend").addEventListener("change", (e) => save({ lipsync_backend: e.target.value }, `Lip-sync: ${esc(e.target.options[e.target.selectedIndex].text)}.`));
    root.querySelector("#sbSpeak").addEventListener("click", () => run(async () => {
      const btn = root.querySelector("#sbSpeak");
      btn.disabled = true; btn.textContent = "Making the voice…";
      try {
        const r = await post(`${base}/speak`, { line: ta.value, voice: root.querySelector("#sbLineVoice").value || null });
        const au = root.querySelector("#sbSpeakAudio");
        au.src = r.audio_url; au.hidden = false;
        au.play().catch(() => {});
        if (r.placeholder) toast(`Preview tone (${r.seconds}s). In Studio mode, you hear the real ${esc(r.voice)} voice.`);
        if (r.voice_note) toast(esc(r.voice_note));
      } finally { if (btn.isConnected) { btn.disabled = false; btn.textContent = "Speak"; } }
    }));
  }
  function dialogueDetails(v) {
    const d = (v.settings || {}).dialogue;
    if (!d) return "";
    const ls = (v.settings || {}).lipsync_stats;
    const mode = { tts_only: "voice only", ltx_a2v: "LTX joint audio+video", "ltx_a2v+latentsync": "LTX audio+video, then LatentSync" }[d.mode] || d.mode;
    const out = [`Line: ${d.line}`, `Spoken by ${d.speaker || "nobody picked"} · voice ${d.voice}${d.voice_from === "shot" ? " (this shot)" : ""}`, `Lip-sync: ${mode}`];
    if (d.take_seconds_est) out.push(`Take length: about ${d.take_seconds_est} s` + (d.planned_seconds ? ` (planned ${d.planned_seconds} s)` : " (automatic)"));
    if (d.voice_note) out.push(d.voice_note);  // VoxCPM2 without a usable clip: spoken with Orpheus
    if (d.face_check && d.face_check.message) out.push(d.face_check.message);
    // L1c mouth pass cost hint: LatentSync runs in 16-frame chunks, about 35.3 s each (ceil(frames / 16) x 35.3 s)
    if (d.latentsync_est_s) out.push(`Mouth pass (LatentSync): about ${d.latentsync_est_s < 90 ? Math.round(d.latentsync_est_s) + " s" : (d.latentsync_est_s / 60).toFixed(1) + " min"} more` +
      `${d.stage2_default_on ? "" : ", only if the take fails a check"}`);
    if (ls) out.push(`Lip-sync stats: face found ${Math.round((ls.face_found_ratio || 0) * 100)}% of ${ls.frames} frames, held ${ls.held_frames}` +
      `${ls.face_px_median ? `, face ${ls.face_px_median}px (min ${ls.face_px_min})` : ""}${ls.multi_face_frames ? `, ${ls.multi_face_frames} frames with several faces` : ""}`);
    else if (d.mode !== "tts_only") out.push("Lip-sync stats: none yet (Preview mode, or the lip-sync step wrote no stats).");
    return out.join("\n");
  }
  function toggleName(names, n) { return names.some((x) => same(x, n)) ? names.filter((x) => !same(x, n)) : [...names, n]; }

  function renderSheet() {
    if (sb.mode !== "shot") return;
    const p = sb.project;
    const i = p.shots.findIndex((x) => x.id === sb.openShot);
    if (i < 0) { showSheet(false); return; }
    const s = p.shots[i];
    const v = s.versions.find((x) => x.id === sb.viewing) || null;
    const nextN = Math.max(0, ...s.versions.map((x) => x.take), s.next_take - 1) + 1;
    $("sbSheetEyebrow").textContent = `Shot ${i + 1} of ${p.shots.length}`;
    $("sbSheetTitle").innerHTML = `<input id="sbSheetName" class="sb-sheet-name" type="text" maxlength="120" value="${esc(s.beat)}" aria-label="Shot name" spellcheck="false" />`;
    wireName($("sbSheetName"), s);
    // A demo take that isn't on the approved list never gets a Keeper mark, only a muted "pending review".
    const keepBtn = !v || v.status !== "ready" ? "" : v.id === s.keeper && v.unapproved
      ? `<span class="sb-is-keeper pending">Keeper (pending review)</span>`
      : v.id === s.keeper ? `<span class="sb-is-keeper">✓ Keeper</span>`
      : v.unapproved || v.shipped ? ""  // an unapproved take can't be kept; a shipped take isn't stored on the server
      : `<button class="btn btn-outline-sb" id="sbKeep" type="button">Use this take</button>`;
    const fb = v && ((v.settings || {}).dialogue || {}).fallback;
    const line = v ? `<p><strong>${esc(v.id)}</strong> · ${esc(v.label || (v.kind === "render" ? "Render" : ""))}${v.edit ? ` · “${esc(v.edit)}”` : ""}${fb ? `<span class="sb-fallback" role="note">LatentSync not used: ${esc(fb)}</span>` : ""}</p>` : `<p></p>`;
    const details = v ? [`Take ${v.take_id}`, `Created ${new Date(v.created).toLocaleString()}`, v.seed != null ? `Seed ${v.seed}` : "",
      v.based_on ? `Made from ${v.based_on}` : "", secs(v) ? `Render time on the studio: ${secs(v)}` : "", queueNote(v), v.note, dialogueDetails(v), v.prompt ? `Prompt used: ${v.prompt}` : "",
      Object.keys(v.scores || {}).length ? `Scores: ${JSON.stringify(v.scores)}` : ""].filter(Boolean).join("\n") : "";
    if (s.kind === "card") { renderCardSheet(p, s, i, v, keepBtn, line, details); return; }  // OS-063
    const hasCast = s.characters.some((n) => castOf(n) && castOf(n).picture_url);
    const finalOf = v && (v.settings || {}).quality === "draft" ? s.versions.find((x) => x.based_on === v.id && (x.settings || {}).quality === "final" && x.status !== "failed") : null;
    // OS-019 / OS-066: a shot with no cast (an establishing or action shot) gets its start frame from the stage plate,
    // or from the words of What happens alone.
    const stageLoc = (p.locations || []).find((l) => same(l.name, s.location || "") && l.image_url);
    const unpictured = s.characters.length && !hasCast;  // cast named, but nobody has a picture yet
    const canFrame = hasCast || !!stageLoc || !s.characters.length;
    const frameFirst = !s.versions.length && canFrame;
    const needFrame = !s.versions.length && !hasCast && !unpictured;  // Generate would animate the wrong picture
    const draftTooMany = sb.quality !== "final" && movesOf(s).length > 2;  // server says the same (camera_moves.DRAFT_WHY)
    const regenText = v && kindLabel(v) === "Frame" ? "Animate this frame" : s.versions.length ? "Regenerate" : "Generate";
    $("sbSheetBody").innerHTML = `
      ${stageHTML(v, s)}
      <div class="sb-take-line">${line}${keepBtn}</div>
      ${filmHTML(s)}
      ${uploadRowHTML()}
      ${kindPickHTML(s)}
      <div class="sb-section">
        <p class="sb-label">Who’s in this shot</p>
        <div class="sb-castpick" role="group" aria-label="Who’s in this shot">${castPickHTML(s.characters)}${pendingNote(s)}</div>
      </div>
      ${dialogueHTML(s)}
      ${voicePickHTML(s.characters)}
      ${stagePickHTML(s)}
      <div class="sb-section sb-two">
        <div class="full"><label class="sb-label" for="sbPrompt">What happens</label><textarea id="sbPrompt" rows="2" maxlength="2000" placeholder="e.g. 3 AM, rain on the window. She reads at the register.">${esc(s.prompt)}</textarea></div>
      </div>
      ${camTilesHTML(s)}
      <div class="sb-section sb-change">
        <label class="sb-label" for="sbEdit">${s.versions.length ? "What should change in the next take?" : "Anything to add for the first take?"}</label>
        <textarea id="sbEdit" rows="2" maxlength="500" placeholder="${v ? "e.g. warmer light, slower push-in, the cat looks up" : "e.g. wide shot, rain on the window"}"></textarea>
        <div class="sb-change-row"><p>${s.versions.length ? `Makes v${nextN}; earlier takes stay.` : "Makes v1 from the shot description."} ${esc(etaText(sb.quality === "final" ? "final" : "draft"))}</p>
          <div class="sb-actions"><div class="sb-quality" role="group" aria-label="Quality">
            <button type="button" class="sb-q ${sb.quality !== "final" ? "on" : ""}" data-q="draft" title="Fast preview: smaller, shorter, no lip-sync">Draft</button>
            <button type="button" class="sb-q ${sb.quality === "final" ? "on" : ""}" data-q="final" title="Full quality render">Final</button>
          </div>
          <button class="btn btn-md ${frameFirst ? "btn-primary" : "btn-outline-sb"}" id="sbFrame" type="button" ${canFrame ? "" : "disabled"} title="${hasCast ? "Put the cast into this shot as a still (Qwen-Image-Edit, local)" : stageLoc ? "Make a still of the stage for this shot (Qwen-Image-Edit, local)" : canFrame ? "Make a still from the words in What happens (Z-Image-Turbo, local)" : "Make a character sheet for the cast first"}">New start frame</button>
          <button class="btn btn-md ${frameFirst ? "btn-outline-sb" : "btn-primary"}" id="sbRegen" type="button" ${draftTooMany ? 'disabled title="Drafts take up to 2 camera moves. Switch to Final."' : needFrame ? 'disabled title="This shot has no cast. Make a start frame first."' : ""}>${regenText}</button></div></div>
        ${finalOf ? `<p class="sb-finalrow">${esc(finalOf.id)} is the Final of ${esc(v.id)}. <button class="sb-link" id="sbSeeFinal" type="button" data-v="${esc(finalOf.id)}">Show ${esc(finalOf.id)}</button></p>`
          : v && v.status === "ready" && !v.unapproved && v.kind !== "concept" && (v.settings || {}).quality === "draft" ? `<p class="sb-finalrow">Happy with ${esc(v.id)}? <button class="sb-link" id="sbFinal" type="button">Render ${esc(v.id)} in Final quality</button> <span>Same seed and start frame${typicalSecs("final") ? ", " + esc(etaText("final").replace("A Final take takes ", "").replace(" here.", "")) : ""}.</span></p>`
          : v && v.based_on && (v.settings || {}).quality === "final" ? `<p class="sb-finalrow">Final of ${esc(v.based_on)}. <button class="sb-link" id="sbSeeFinal" type="button" data-v="${esc(v.based_on)}">Show the Draft</button></p>` : ""}
      </div>
      <details class="sb-adv"><summary>More options</summary>
        <div class="sb-adv-grid">
          <div><label for="sbSeed">Seed (blank = new)</label><input id="sbSeed" type="number" min="1" /></div>
        </div>
        <div class="sb-adv-actions">
          ${v ? `<button class="btn btn-ghost btn-sm-sb" id="sbRecipe" type="button" title="Copy what you need to make this take again on another computer">Copy recipe</button>` : ""}
          <button class="btn btn-ghost btn-sm-sb" id="sbEarlier" type="button" ${i === 0 ? "disabled" : ""}>Move earlier</button>
          <button class="btn btn-ghost btn-sm-sb" id="sbLater" type="button" ${i === p.shots.length - 1 ? "disabled" : ""}>Move later</button>
          ${v && !v.shipped ? `<button class="btn btn-sm-sb btn-danger-sb" id="sbDelTake" type="button">Delete ${esc(v.id)}…</button>` : ""}
          <button class="btn btn-sm-sb btn-danger-sb" id="sbDelShot" type="button">Delete shot</button>
        </div>
        ${details ? `<div class="sb-details">${esc(details)}</div>` : ""}
      </details>`;
    wireStageHold($("sbSheetBody"), v);
    const film = $("sbSheetBody").querySelector(".sb-film");
    const cur = film && film.querySelector('button[aria-current="true"]');
    if (cur) film.scrollLeft = Math.max(0, cur.parentElement.offsetLeft - film.offsetLeft - (film.clientWidth - cur.clientWidth) / 2);
    const base = `/projects/${p.id}/shots/${s.id}`;
    const save = (body, msg) => run(async () => { setProject(await patch(base, body)); if (msg) toast(msg); });
    $("sbSheetBody").querySelectorAll(".sb-film button").forEach((b) => b.addEventListener("click", () => { sb.viewing = b.dataset.v; renderSheet(); }));
    $("sbPrompt").addEventListener("blur", (e) => { if (e.target.value !== s.prompt) save({ prompt: e.target.value }); });
    wireCamTiles($("sbSheetBody"), s, save);
    if ($("sbStage")) $("sbStage").addEventListener("change", (e) => save({ location: e.target.value, stage_angle: "" }, e.target.value ? `Stage: ${esc(e.target.value)}.` : "No stage."));
    $("sbSheetBody").querySelectorAll(".sb-angle").forEach((b) => b.addEventListener("click", () => save({ stage_angle: b.dataset.angle }, `Angle: ${esc(b.dataset.angle || "master")}.`)));
    if ($("sbStageNew")) $("sbStageNew").addEventListener("click", () => openStage(null, { shot: s.id }));
    if ($("sbStageEdit")) $("sbStageEdit").addEventListener("click", (e) => openStage(e.currentTarget.dataset.stage, { shot: s.id }));
    if ($("sbStageFromTake")) $("sbStageFromTake").addEventListener("click", (e) => openStage(null, { shot: s.id, from: e.currentTarget.dataset.from }));
    wireCastPick($("sbSheetBody"), () => s.characters, (chars) => save({ characters: chars }), (name) => openCharacter(name, s.id));
    wireVoicePick($("sbSheetBody"));
    wireDialogue($("sbSheetBody"), s, save, base);
    if ($("sbRecipe")) $("sbRecipe").addEventListener("click", () => {
      const st = v.settings || {};
      const recipe = [`Shot: ${s.beat} (${p.title})`, `Take: ${v.id} · ${kindLabel(v)}`, `Cast: ${s.characters.join(", ") || "none"}`,
        `Camera: ${s.camera}`, s.line ? `Line: ${s.speaker ? s.speaker + ": " : ""}${s.line}` : "", v.seed != null ? `Seed: ${v.seed}` : "", st.quality ? `Quality: ${st.quality}` : "",
        st.base_image ? `Start frame: ${st.base_image}` : v.file && kindLabel(v) === "Frame" ? `Start frame: ${v.file}` : "",
        `Prompt: ${v.prompt || s.prompt}`].filter(Boolean).join("\n");
      (navigator.clipboard ? navigator.clipboard.writeText(recipe) : Promise.reject()).then(
        () => toast("Recipe copied. Paste it into a shot on any OpenSoul install to make this take again."),
        () => toast(`<pre style="white-space:pre-wrap;margin:0">${esc(recipe)}</pre>`, true));
    });
    if ($("sbSeeFinal")) $("sbSeeFinal").addEventListener("click", (e) => { sb.viewing = e.currentTarget.dataset.v; renderSheet(); });
    if ($("sbKeep")) $("sbKeep").addEventListener("click", () => run(async () => { setProject(await post(`${base}/keeper`, { version_id: v.id })); toast(`${esc(v.id)} is now the keeper for “${esc(s.beat)}”.`); }));
    $("sbRegen").addEventListener("click", () => run(async () => {
      const btn = $("sbRegen");
      btn.disabled = true; btn.textContent = "Making a new take…";
      const seed = $("sbSeed").value ? Number($("sbSeed").value) : null;
      const before = new Set(s.versions.map((x) => x.id));
      try {
        const np = await post(`${base}/regenerate`, { edit: $("sbEdit").value, seed, from_version: v && !v.shipped ? v.id : null, quality: sb.quality === "final" ? "final" : "draft" });
        sb.editDraft = null;
        const made = np.shots.find((x) => x.id === s.id).versions.find((x) => !before.has(x.id));
        sb.viewing = made ? made.id : sb.viewing;
        setProject(np);
        $("sbSheet").scrollTo({ top: 0, behavior: "smooth" });
        if (made) toast(`Made ${esc(made.id)}. Your earlier takes are still here. Click <strong>Use this take</strong> to make it the keeper.`);
        if (made && made.status === "rendering") poll();
      } finally { if (btn.isConnected) { btn.disabled = false; btn.textContent = regenText; } }
    }));
    $("sbFrame").addEventListener("click", () => run(async () => {
      const btn = $("sbFrame");
      btn.disabled = true; btn.textContent = "Composing…";
      const before = new Set(s.versions.map((x) => x.id));
      try {
        const np = await post(`${base}/frame`, { edit: $("sbEdit").value, seed: $("sbSeed").value ? Number($("sbSeed").value) : null });
        sb.editDraft = null;
        const made = np.shots.find((x) => x.id === s.id).versions.find((x) => !before.has(x.id));
        sb.viewing = made ? made.id : sb.viewing;
        setProject(np);
        if (made) toast(`Made start frame ${esc(made.id)}. Click <strong>Animate this frame</strong> to make a video take from it.`);
        if (made && made.status === "rendering") poll();
      } finally { if (btn.isConnected) { btn.disabled = false; btn.textContent = "New start frame"; } }
    }));
    $("sbSheetBody").querySelectorAll(".sb-q").forEach((b) => b.addEventListener("click", () => { sb.quality = b.dataset.q; renderSheet(); }));
    // OS-035: the typed change survives a re-render (Draft/Final toggle, a poll, a save). It goes with the next take.
    const ed = $("sbEdit");
    if (ed) {
      if (sb.editDraft && sb.editDraft.shot === s.id && !ed.value) ed.value = sb.editDraft.text;
      ed.addEventListener("input", () => { sb.editDraft = { shot: s.id, text: ed.value }; });
    }
    if ($("sbFinal")) $("sbFinal").addEventListener("click", () => run(async () => {
      const before = new Set(s.versions.map((x) => x.id));
      const np = await post(`${base}/final`, { version_id: v.id });
      const made = np.shots.find((x) => x.id === s.id).versions.find((x) => !before.has(x.id));
      sb.viewing = made ? made.id : sb.viewing;
      setProject(np);
      if (made) toast(`Rendering ${esc(made.id)} in Final quality from ${esc(v.id)} (same seed and picture). ${esc(v.id)} stays.`);
      if (made && made.status === "rendering") poll();
    }));
    wireKindPick(s, save);
    wireUpload(s, base);
    $("sbEarlier").addEventListener("click", () => move(s.id, -1));
    $("sbLater").addEventListener("click", () => move(s.id, 1));
    if ($("sbDelTake")) $("sbDelTake").addEventListener("click", () => {
      if (!confirm(`Delete take ${v.id} of “${s.beat}”? You cannot undo this. Your other takes stay.`)) return;
      run(async () => { const np = await api(`${base}/versions/${v.id}?confirm=1`, { method: "DELETE" }); const ns = np.shots.find((x) => x.id === s.id); sb.viewing = ns && (ns.keeper || (ns.versions.at(-1) || {}).id); setProject(np); });
    });
    $("sbDelShot").addEventListener("click", () => deleteShot(s.id));
  }

  // OS-063: Scene or Title card. A card is text on a color, drawn on this computer (no model, no GPU).
  function kindPickHTML(s) {
    return `<div class="sb-section sb-kind"><p class="sb-label" id="sbKindL">Type of shot</p>
      <div class="sb-quality" role="group" aria-labelledby="sbKindL">
        <button type="button" class="sb-q ${s.kind !== "card" ? "on" : ""}" data-kind="scene" aria-pressed="${s.kind !== "card"}">Scene</button>
        <button type="button" class="sb-q ${s.kind === "card" ? "on" : ""}" data-kind="card" aria-pressed="${s.kind === "card"}">Title card</button></div></div>`;
  }
  function wireKindPick(s, save) {
    $("sbSheetBody").querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
      if ((s.kind || "scene") === b.dataset.kind) return;
      save(b.dataset.kind === "card" ? { kind: "card", card_title: s.card_title || s.beat } : { kind: "scene" },
        b.dataset.kind === "card" ? "This shot is a title card now. Type the words, then click <strong>Make the card</strong>." : "This shot is a scene now.");
    }));
  }
  const CARD_BG = [["black", "Black"], ["white", "White"], ["night", "Night blue"], ["red", "Dark red"]];
  function renderCardSheet(p, s, i, v, keepBtn, line, details) {
    const base = `/projects/${p.id}/shots/${s.id}`;
    const save = (body, msg) => run(async () => { setProject(await patch(base, body)); if (msg) toast(msg); });
    $("sbSheetBody").innerHTML = `
      ${stageHTML(v, s)}
      <div class="sb-take-line">${line}${keepBtn}</div>
      ${filmHTML(s)}
      ${uploadRowHTML()}
      ${kindPickHTML(s)}
      <div class="sb-section sb-card-form">
        <label class="sb-label" for="sbCardTitle">Big text</label>
        <input id="sbCardTitle" type="text" maxlength="80" value="${esc(s.card_title || "")}" placeholder="e.g. THE LAST LIGHTHOUSE" />
        <label class="sb-label" for="sbCardSub">Small text (optional)</label>
        <input id="sbCardSub" type="text" maxlength="160" value="${esc(s.card_sub || "")}" placeholder="e.g. Coming soon" />
        <label class="sb-label" for="sbCardBg">Background</label>
        <select id="sbCardBg">${CARD_BG.map(([id, label]) => `<option value="${id}" ${(s.card_bg || "black") === id ? "selected" : ""}>${label}</option>`).join("")}</select>
        <label class="sb-label" for="sbCardLen">Length (s)</label>
        <input id="sbCardLen" type="number" min="1" max="20" step="0.5" inputmode="decimal" placeholder="3" value="${s.seconds ? esc(String(s.seconds)) : ""}" />
        <p class="sb-hint">OpenSoul draws the card on this computer. It uses no model and no GPU, so the words are exactly what you type.</p>
        <div class="sb-actions"><button class="btn btn-primary btn-md" id="sbMakeCard" type="button">${s.versions.some((x) => x.kind === "card") ? "Make the card again" : "Make the card"}</button></div>
      </div>
      <details class="sb-adv"><summary>More options</summary>
        <div class="sb-adv-actions">
          <button class="btn btn-ghost btn-sm-sb" id="sbEarlier" type="button" ${i === 0 ? "disabled" : ""}>Move earlier</button>
          <button class="btn btn-ghost btn-sm-sb" id="sbLater" type="button" ${i === p.shots.length - 1 ? "disabled" : ""}>Move later</button>
          ${v && !v.shipped ? `<button class="btn btn-sm-sb btn-danger-sb" id="sbDelTake" type="button">Delete ${esc(v.id)}…</button>` : ""}
          <button class="btn btn-sm-sb btn-danger-sb" id="sbDelShot" type="button">Delete shot</button>
        </div>
        ${details ? `<div class="sb-details">${esc(details)}</div>` : ""}
      </details>`;
    wireStageHold($("sbSheetBody"), v);
    $("sbSheetBody").querySelectorAll(".sb-film button").forEach((b) => b.addEventListener("click", () => { sb.viewing = b.dataset.v; renderSheet(); }));
    if ($("sbKeep")) $("sbKeep").addEventListener("click", () => run(async () => { setProject(await post(`${base}/keeper`, { version_id: v.id })); toast(`${esc(v.id)} is now the keeper for “${esc(s.beat)}”.`); }));
    const fields = () => ({ card_title: $("sbCardTitle").value, card_sub: $("sbCardSub").value, card_bg: $("sbCardBg").value });
    ["sbCardTitle", "sbCardSub"].forEach((id) => $(id).addEventListener("blur", () => { const f = fields(); if (f.card_title !== (s.card_title || "") || f.card_sub !== (s.card_sub || "")) save(f); }));
    $("sbCardBg").addEventListener("change", () => save(fields()));
    $("sbCardLen").addEventListener("change", (e) => save({ seconds: e.target.value === "" ? 0 : Number(e.target.value) }));
    $("sbMakeCard").addEventListener("click", () => run(async () => {
      const before = new Set(s.versions.map((x) => x.id));
      await patch(base, { ...fields(), seconds: $("sbCardLen").value === "" ? 0 : Number($("sbCardLen").value) });
      const np = await post(`${base}/card`, {});
      const made = np.shots.find((x) => x.id === s.id).versions.find((x) => !before.has(x.id));
      sb.viewing = made ? made.id : sb.viewing;
      setProject(np);
      if (made) toast(`Made card ${esc(made.id)}.`);
    }));
    wireKindPick(s, save);
    wireUpload(s, base);
    $("sbEarlier").addEventListener("click", () => move(s.id, -1));
    $("sbLater").addEventListener("click", () => move(s.id, 1));
    if ($("sbDelTake")) $("sbDelTake").addEventListener("click", () => {
      if (!confirm(`Delete take ${v.id} of “${s.beat}”? You cannot undo this. Your other takes stay.`)) return;
      run(async () => { const np = await api(`${base}/versions/${v.id}?confirm=1`, { method: "DELETE" }); const ns = np.shots.find((x) => x.id === s.id); sb.viewing = ns && (ns.keeper || (ns.versions.at(-1) || {}).id); setProject(np); });
    });
    $("sbDelShot").addEventListener("click", () => deleteShot(s.id));
  }
  function uploadRowHTML() {
    return `<p class="sb-upload-row"><button class="sb-link" id="sbUpload" type="button">Add your own picture or clip as a take</button>
        <input type="file" id="sbUploadFile" accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm" hidden /></p>`;
  }
  // OS-064: your own still or clip becomes a new take (it can be the keeper and goes into the export).
  function wireUpload(s, base) {
    $("sbUpload").addEventListener("click", () => $("sbUploadFile").click());
    $("sbUploadFile").addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      if (!confirm(`Add “${f.name}” as a new take? Use only a file that you made or have permission to use.`)) { e.target.value = ""; return; }
      run(async () => {
        const fd = new FormData();
        fd.append("file", f); fd.append("consent", "true");
        const before = new Set(s.versions.map((x) => x.id));
        const np = await api(`${base}/upload`, { method: "POST", body: fd });
        const made = np.shots.find((x) => x.id === s.id).versions.find((x) => !before.has(x.id));
        sb.viewing = made ? made.id : sb.viewing;
        setProject(np);
        if (made) toast(`Added ${esc(made.id)} from your file.${made.id === np.shots.find((x) => x.id === s.id).keeper ? " It is the keeper now." : " Click <strong>Use this take</strong> to make it the keeper."}`);
      });
    });
  }

  function wireCastPick(root, get, set, onNew) {
    root.querySelectorAll(".sb-chip[data-name]").forEach((b) => b.addEventListener("click", () => set(toggleName(get(), b.dataset.name))));
    root.querySelectorAll("[data-drop]").forEach((b) => b.addEventListener("click", () => set(get().filter((x) => !same(x, b.dataset.drop)))));
    root.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => onNew(b.dataset.add)));
    root.querySelectorAll("[data-new]").forEach((b) => b.addEventListener("click", () => onNew("")));
  }

  let polling = null;
  function poll() {
    clearTimeout(polling);
    polling = setTimeout(async () => {
      const p = await api(`/projects/${sb.project.id}`);
      setProject(p);
      if (p.shots.some((s) => s.versions.some((v) => v.status === "rendering")) || (p.locations || []).some((l) => l.rendering)) poll();
    }, 4000);
  }

  // ---------------------------------------------------------------- new character (from a picture or a sheet)
  function openCharacter(name, shotId) {
    sb.returnTo = shotId ? { mode: "shot", id: shotId } : sb.mode === "new" ? { mode: "new" } : null;
    sb.mode = "character";
    sheetHead("Your characters", "New character");
    $("sbSheetBody").innerHTML = `<div class="sb-form">
      <div class="field"><label for="sbCName">Name</label><input id="sbCName" type="text" maxlength="60" value="${esc(name || "")}" placeholder="e.g. Kai" autocomplete="off" /></div>
      <div class="field"><span class="label">Picture</span>
        <div class="sb-seg" role="radiogroup" aria-label="Picture type">
          <button type="button" class="sb-seg-b on" data-kind="reference" role="radio" aria-checked="true">Reference picture</button>
          <button type="button" class="sb-seg-b" data-kind="sheet" role="radio" aria-checked="false">Character sheet</button>
        </div>
        <input id="sbCFile" type="file" accept="image/*" />
        <label class="file-btn" for="sbCFile">Choose a picture</label> <span class="file-name" id="sbCFileName">No picture yet</span>
        <img class="sb-file-thumb" id="sbCFileThumb" alt="The picture you chose" hidden />
        <span class="hint" id="sbCKindHint">One clear picture of them. It becomes their face in start frames.</span></div>
      <label class="consent" id="sbCConsentRow" hidden><input id="sbCConsent" type="checkbox" /><span>I own this picture or have permission. Original characters or your own photos only.</span></label>
      <div class="field"><label for="sbCDesc">Look &amp; wardrobe <span class="optional">(optional with a picture)</span></label>
        <textarea id="sbCDesc" rows="3" maxlength="1000" placeholder="e.g. a tall courier in his thirties, short black hair, yellow rain jacket"></textarea>
        <span class="hint">Locks their look in every prompt. Want six matching angles? <button type="button" class="sb-link" id="sbCToCreate">Make a full character sheet in Create</button>.</span></div>
      ${sb.returnTo ? `<label class="consent" id="sbCAddRow"><input id="sbCAdd" type="checkbox" checked /><span>Also put them in ${sb.returnTo.mode === "shot" ? "this shot" : "the new shot"}</span></label>` : ""}
      <div class="sb-form-actions"><button class="btn btn-ghost btn-md" id="sbCCancel" type="button">Cancel</button><button class="btn btn-primary btn-md" id="sbCSave" type="button">Save character</button></div>
    </div>`;
    showSheet(true);
    let kind = "reference";
    $("sbSheetBody").querySelectorAll(".sb-seg-b").forEach((b) => b.addEventListener("click", () => {
      kind = b.dataset.kind;
      $("sbSheetBody").querySelectorAll(".sb-seg-b").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
      $("sbCKindHint").textContent = kind === "sheet" ? "A sheet with several views of them (like the six-view sheet from Create)." : "One clear picture of them. It becomes their face in start frames.";
    }));
    $("sbCFile").addEventListener("change", (e) => {
      const f = e.target.files[0];
      $("sbCFileName").textContent = f ? f.name : "No picture yet";
      $("sbCConsentRow").hidden = !f;
    });
    wireFileThumb($("sbCFile"), "sbCFileThumb");
    $("sbCToCreate").addEventListener("click", () => { showSheet(false); setView("create"); const n = $("name"); if (n) { n.value = $("sbCName") ? $("sbCName").value : ""; n.focus(); } });
    $("sbCCancel").addEventListener("click", back);
    $("sbCSave").addEventListener("click", () => run(async () => {
      const fd = new FormData();
      fd.append("name", $("sbCName").value);
      fd.append("description", $("sbCDesc").value);
      fd.append("kind", kind);
      fd.append("consent", $("sbCConsent").checked ? "true" : "false");
      if ($("sbCFile").files[0]) fd.append("image", $("sbCFile").files[0]);
      let nm;
      try {
        const r = await api("/cast", { method: "POST", body: fd });
        sb.cast = r.cast;
        nm = r.character.name;
        toast(`${esc(nm)} is in your characters.`);
      } catch (e) {
        // Made in Create (or another tab) after this page loaded: refresh, then just use them.
        await loadCast();
        const have = castOf($("sbCName").value.split(/\s+/).join(" ").trim());
        if (!have) throw e;
        nm = have.name;
        toast(`${esc(nm)} is already in your characters. Using them.`);
      }
      const ret = sb.returnTo;
      const addToShot = !!($("sbCAdd") && $("sbCAdd").checked);  // explicit: never added to a shot silently
      if (addToShot && ret && ret.mode === "shot") {
        const s = sb.project.shots.find((x) => x.id === ret.id);
        if (s && !s.characters.some((x) => same(x, nm))) {
          setProject(await patch(`/projects/${sb.project.id}/shots/${s.id}`, { characters: [...s.characters, nm] }));
          toast(`${esc(nm)} is in your characters and in this shot.`);
        }
      } else if (addToShot && ret && ret.mode === "new" && sb.draft) {
        if (!sb.draft.characters.some((x) => same(x, nm))) sb.draft.characters.push(nm);
      }
      back();
    }));
    $("sbCName").focus();
    function back() {
      const ret = sb.returnTo;
      sb.returnTo = null;
      if (ret && ret.mode === "shot") openShot(ret.id);
      else if (ret && ret.mode === "new") openNew(true);
      else showSheet(false);
      if (sb.project) render();
    }
  }

  // ---------------------------------------------------------------- stages (stage sheets: one place, the same in every shot)
  // Mirrors the character sheet: start from a picture (or a take), the master plate is the "face" of the place,
  // Make angles adds views (add / regenerate / rename), Build stage sheet makes the one picture to check by eye,
  // and a checklist says what's still missing. Shots pick a stage + angle in their sheet.
  const locOf = (name) => (sb.project.locations || []).find((l) => same(l.name, name));
  const locBase = (name) => `/projects/${sb.project.id}/locations/${encodeURIComponent(name)}`;
  // Take picker: the takes as small pictures (the select stays as the keyboard / screen-reader way to pick).
  function takeStripHTML(takes, selected) {
    return `<div class="sb-take-strip" role="group" aria-label="Your takes">${takes.map((t) => `<button type="button" class="sb-take-pick${t.value === selected ? " on" : ""}" data-take-pick="${esc(t.value)}" aria-pressed="${t.value === selected}" title="${esc(t.label)}">
      <img src="${esc(t.url)}" alt="" loading="lazy" /><span>${esc(t.label.replace(/ · [^·]+ · /, " · "))}</span></button>`).join("")}</div>`;
  }
  function wireTakeStrip(root) {
    root.querySelectorAll("[data-take-pick]").forEach((b) => b.addEventListener("click", () => {
      const sel = $("sbStTakeSel");
      if (!sel) return;
      sel.value = b.dataset.takePick;
      root.querySelectorAll("[data-take-pick]").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
      sel.dispatchEvent(new Event("change"));
    }));
  }
  // A chosen file shows as a small picture right away (was only its file name).
  function wireFileThumb(input, thumbId) {
    const img = $(thumbId);
    if (!input || !img) return;
    input.addEventListener("change", () => {
      const f = input.files && input.files[0];
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      if (f) { img.dataset.url = URL.createObjectURL(f); img.src = img.dataset.url; img.hidden = false; }
      else { img.hidden = true; img.removeAttribute("src"); delete img.dataset.url; }
    });
  }
  function takeStills() {  // every take with a still: "Shot 2 · v3"
    return sb.project.shots.flatMap((s, i) => s.versions.filter((v) => v.status === "ready" && v.poster_url && !v.shipped)
      .map((v) => ({ value: `${s.id}/${v.id}`, label: `Shot ${i + 1} · ${s.beat} · ${v.id}`, url: v.poster_url })));
  }
  function renderStages() {
    const box = $("sbStageList");
    if (!box) return;
    const locs = sb.project.locations || [];
    box.innerHTML = locs.map((l) => {
      const req = l.readiness.filter((x) => !x.optional);
      const done = req.filter((x) => x.done).length;
      // A stand-in plate (demo story during the rebuild) says so instead of "Ready".
      const state = l.rendering ? `Making ${plural(l.rendering, "angle")}…` : l.placeholder ? (l.status || "Rebuilding the plate")
        : l.ready ? "Ready" : `${done} of ${req.length} done`;
      return `<li><button type="button" class="sb-stage-card${l.ready && !l.placeholder ? " ready" : ""}" data-stage="${esc(l.name)}">
        ${l.image_url ? `<img src="${esc(l.image_url)}" alt="" loading="lazy" />` : `<span class="sb-stage-noimg">No master plate</span>`}
        <span class="sb-stage-n">${esc(l.name)}</span>
        <span class="sb-stage-s">${esc(state)}</span>
        <span class="sb-stage-s sb-stage-c">${esc(plural(l.angle_count || 0, "angle"))}${l.shots_using ? ` · ${plural(l.shots_using, "shot")}` : ""}</span></button></li>`;
    }).join("") + `<li><button type="button" class="sb-stage-card add" id="sbNewStage"><span class="sb-plus-sm">+</span>New stage</button></li>`;
    box.querySelectorAll("[data-stage]").forEach((b) => b.addEventListener("click", () => openStage(b.dataset.stage)));
    $("sbNewStage").addEventListener("click", () => openStage(null));
  }

  async function stageSuggestions() {
    if (!sb.angleHints) { try { sb.angleHints = await api("/stage/angle-suggestions"); } catch (_) { sb.angleHints = { angles: [], max: 6, min: 2 }; } }
    return sb.angleHints;
  }

  function openStage(name, opts = {}) {
    sb.returnTo = opts.shot ? { mode: "shot", id: opts.shot } : sb.mode === "shot" && sb.openShot ? { mode: "shot", id: sb.openShot } : null;
    sb.mode = "stage";
    sb.openStage = name;
    sb.stageFrom = opts.from || null;
    $("sbSheetBody").innerHTML = "";  // a fresh form every time the sheet opens
    stageSuggestions().then(() => { if (sb.mode === "stage") renderStageSheet(); });
    renderStageSheet();
    showSheet(true);
  }
  function stageBack() {
    const ret = sb.returnTo;
    sb.returnTo = null;
    if (ret && ret.mode === "shot" && sb.project.shots.some((s) => s.id === ret.id)) openShot(ret.id); else showSheet(false);
  }

  function newStageHTML() {
    const takes = takeStills();
    const from = sb.stageFrom && takes.some((t) => t.value === sb.stageFrom) ? sb.stageFrom : "";
    const src = from ? "take" : "upload";
    return `<div class="sb-form">
      <div class="field"><label for="sbStName">Name</label><input id="sbStName" data-new-stage type="text" maxlength="60" placeholder="e.g. Night Diner" autocomplete="off" /></div>
      <div class="field"><span class="label">Master plate</span>
        <div class="sb-seg" role="radiogroup" aria-label="Start the stage from">
          <button type="button" class="sb-seg-b ${src === "upload" ? "on" : ""}" data-src="upload" role="radio" aria-checked="${src === "upload"}">A picture</button>
          <button type="button" class="sb-seg-b ${src === "take" ? "on" : ""}" data-src="take" role="radio" aria-checked="${src === "take"}" ${takes.length ? "" : "disabled title=\"No takes with a still yet\""}>One of your takes</button>
        </div>
        <div id="sbStUpload" ${src === "upload" ? "" : "hidden"}>
          <input id="sbStFile" type="file" accept="image/*" />
          <label class="file-btn" for="sbStFile">Choose a picture</label> <span class="file-name" id="sbStFileName">No picture yet</span>
          <img class="sb-file-thumb" id="sbStFileThumb" alt="The picture you chose" hidden />
          <label class="consent" id="sbStConsentRow" hidden><input id="sbStConsent" type="checkbox" /><span>I own this picture or have permission to use it.</span></label>
        </div>
        <div id="sbStTake" ${src === "take" ? "" : "hidden"}>
          ${takeStripHTML(takes, from || (takes[0] || {}).value)}
          <select id="sbStTakeSel" aria-label="Take to use as the master plate">${takes.map((t) => `<option value="${esc(t.value)}" ${t.value === from ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select>
        </div>
        <span class="hint">The wide shot of the stage. OpenSoul makes the angles from it and edits the start frames from it.</span></div>
      <div class="field"><label for="sbStDesc">What’s there <span class="optional">(optional)</span></label>
        <textarea id="sbStDesc" rows="2" maxlength="1500" placeholder="e.g. chrome counter, red vinyl stools, neon OPEN sign, rain on the window"></textarea>
        <span class="hint">Goes into every angle and start frame, so the stage stays the same.</span></div>
      <div class="sb-form-actions"><button class="btn btn-ghost btn-md" id="sbStCancel" type="button">Cancel</button><button class="btn btn-primary btn-md" id="sbStMake" type="button">Create stage</button></div></div>`;
  }
  function wireNewStage() {
    let src = $("sbStTake").hidden ? "upload" : "take";
    $("sbSheetBody").querySelectorAll("[data-src]").forEach((b) => b.addEventListener("click", () => {
      src = b.dataset.src;
      $("sbSheetBody").querySelectorAll("[data-src]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
      $("sbStUpload").hidden = src !== "upload"; $("sbStTake").hidden = src !== "take";
    }));
    $("sbStFile").addEventListener("change", (e) => { const f = e.target.files[0]; $("sbStFileName").textContent = f ? f.name : "No picture yet"; $("sbStConsentRow").hidden = !f; });
    wireFileThumb($("sbStFile"), "sbStFileThumb");
    wireTakeStrip($("sbStTake"));
    $("sbStCancel").addEventListener("click", stageBack);
    $("sbStMake").addEventListener("click", () => run(async () => {
      const name = $("sbStName").value.trim().replace(/\s+/g, " ");
      if (!name) { $("sbStName").focus(); throw new Error("Give the stage a name."); }
      if (locOf(name)) throw new Error(`There’s already a stage called “${name}”. Open it from the Stages row, or pick another name.`);
      const desc = $("sbStDesc").value;
      let np;
      if (src === "take") {
        np = await api(locBase(name), { method: "PUT", body: JSON.stringify({ from_version: $("sbStTakeSel").value, description: desc }) });
      } else {
        const f = $("sbStFile").files[0];
        if (!f) throw new Error("Choose a picture of the place, or use one of your takes.");
        const fd = new FormData();
        fd.append("role", "master"); fd.append("consent", $("sbStConsent").checked ? "true" : "false"); fd.append("description", desc); fd.append("image", f);
        np = await api(`${locBase(name)}/upload`, { method: "POST", body: fd });
      }
      sb.openStage = (np.locations.find((l) => same(l.name, name)) || {}).name || name;
      $("sbSheetBody").innerHTML = "";  // the New stage form is done: draw the stage editor
      setProject(np);
      toast(`Made the stage “${esc(sb.openStage)}”. Next: make at least ${(sb.angleHints || {}).min || 2} angles.`);
    }));
    $("sbStName").focus();
  }

  function angleTileHTML(a) {
    const body = a.status === "rendering" ? `<span class="sb-at-msg">Making this angle…</span>`
      : a.status === "failed" ? `<span class="sb-at-msg bad" role="note">${esc(a.error || "Couldn’t make this angle.")}</span>`
      : a.image_url ? `<img src="${esc(a.image_url)}" alt="${esc(a.name)}" loading="lazy" />` : `<span class="sb-at-msg">No picture yet</span>`;
    return `<li class="sb-at${a.status ? " " + esc(a.status) : ""}" data-a="${esc(a.name)}">
      <div class="sb-at-pic">${body}</div>
      <input class="sb-at-name" type="text" maxlength="60" value="${esc(a.name)}" aria-label="Name of the angle ${esc(a.name)}" spellcheck="false" />
      ${a.note ? `<p class="sb-at-note">${esc(a.note)}</p>` : ""}
      <div class="sb-at-acts"><button type="button" class="sb-link" data-regen="${esc(a.name)}" ${a.status === "rendering" ? "disabled" : ""}>${a.image_url || a.status === "failed" ? "Regenerate" : "Make"}</button>
        <button type="button" class="sb-link danger" data-del-angle="${esc(a.name)}" aria-label="Remove the angle ${esc(a.name)}">Remove</button></div></li>`;
  }

  function stageHTMLFor(l) {
    const hints = sb.angleHints || { angles: [], max: 6, min: 2 };
    const full = l.angles.length >= hints.max;
    const sugg = hints.angles.filter((g) => !l.angles.some((a) => same(a.name, g.name)));
    const check = l.readiness.map((r) => `<li class="${r.done ? "done" : ""}${r.optional ? " opt" : ""}"><span aria-hidden="true">${r.done ? "✓" : "○"}</span>
      ${esc(r.label)}${r.optional ? ` <em>(optional)</em>` : ""}${r.detail ? ` <span class="sb-ck-d">· ${esc(r.detail)}</span>` : ""}</li>`).join("");
    const takes = takeStills();
    return `<div class="sb-stage-ed">
      <div class="sb-st-top">
        <figure class="sb-st-master">${l.image_url ? `<img src="${esc(l.image_url)}" alt="Master plate of ${esc(l.name)}" />` : `<span class="sb-at-msg">No master plate yet</span>`}
          <figcaption>Master plate (wide)</figcaption></figure>
        <div class="sb-st-ready"><p class="sb-label">${l.ready ? "Stage sheet ready" : "To finish this stage"}</p><ul class="sb-check-list">${check}</ul>
          <p class="sb-hint">${l.shots_using ? `Used by ${plural(l.shots_using, "shot")}.` : "No shot uses this stage yet. Pick it in a shot’s Stage section."}</p></div>
      </div>
      <div class="sb-section"><p class="sb-label">Replace the master plate</p>
        <div class="sb-st-row"><input id="sbStFile" type="file" accept="image/*" /><label class="file-btn" for="sbStFile">Upload a picture</label>
          ${takes.length ? `<span>or</span><select id="sbStTakeSel" aria-label="Use a take as the master plate"><option value="">Use one of your takes…</option>${takes.map((t) => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join("")}</select>` : ""}</div>
        ${takes.length ? takeStripHTML(takes, "") : ""}
        <img class="sb-file-thumb" id="sbStFileThumb" alt="The picture you chose" hidden />
        <label class="consent" id="sbStConsentRow" hidden><input id="sbStConsent" type="checkbox" /><span>I own this picture or have permission to use it.</span></label>
        <p class="sb-hint">Angles you already made stay; build the sheet again afterwards.</p></div>
      <div class="sb-section"><label class="sb-label" for="sbStDesc">What’s there</label>
        <textarea id="sbStDesc" rows="2" maxlength="1500" placeholder="e.g. chrome counter, red vinyl stools, neon OPEN sign">${esc(l.description || "")}</textarea></div>
      <div class="sb-section"><p class="sb-label">Angles <span class="sb-count">${Math.min(l.angle_count || 0, hints.max)} of ${hints.max}</span></p>
        ${l.angles.length ? `<ul class="sb-at-grid">${l.angles.map(angleTileHTML).join("")}</ul>` : `<p class="sb-empty-line">No angles yet. OpenSoul makes each angle from the master plate, so the stage stays the same.</p>`}
        ${full ? `<p class="sb-hint">A stage sheet holds up to ${hints.max} angles. Remove one to add another.</p>` : `
        <div class="sb-st-add"><p class="sb-hint">Make angles:</p>
          ${sugg.map((g) => `<button type="button" class="sb-chip" data-make="${esc(g.name)}" title="${esc(g.note)}" ${l.image_url ? "" : "disabled"}>+ ${esc(g.name)}</button>`).join("")}
          <span class="sb-st-custom"><input id="sbStAngle" type="text" maxlength="60" placeholder="your own, e.g. behind the counter" aria-label="Name of a new angle" />
          <button type="button" class="btn btn-outline-sb btn-sm-sb" id="sbStAngleMake" ${l.image_url ? "" : "disabled"}>Make angle</button>
          <input id="sbStAngleFile" type="file" accept="image/*" /><label class="file-btn sb-sm" for="sbStAngleFile" title="Use your own picture for this angle">Upload instead</label></span>
          ${l.image_url ? "" : `<p class="sb-hint">Give the stage a master plate first. OpenSoul makes its angles from it.</p>`}</div>`}</div>
      <div class="sb-section"><p class="sb-label">Empty plate <span class="optional">(optional)</span></p>
        <div class="sb-st-row">${l.empty_url ? `<img class="sb-st-empty" src="${esc(l.empty_url)}" alt="Empty plate" />` : ""}
          <input id="sbStEmpty" type="file" accept="image/*" /><label class="file-btn" for="sbStEmpty">${l.empty_url ? "Replace" : "Upload"} the empty plate</label></div>
        <p class="sb-hint">The same view with nobody in it. If it exists, OpenSoul makes the angles from it.</p></div>
      <div class="sb-section"><label class="sb-label" for="sbStCheck">Continuity checklist <span class="optional">(optional, one per line)</span></label>
        <textarea id="sbStCheck" rows="3" maxlength="2000" placeholder="e.g. neon sign says OPEN&#10;three stools at the counter">${esc((l.checklist || []).join("\n"))}</textarea></div>
      <div class="sb-section sb-st-build">
        <button class="btn btn-primary btn-md" id="sbStBuild" type="button" ${l.image_url && !l.rendering ? "" : "disabled"}>${l.sheet_url ? "Build stage sheet again" : "Build stage sheet"}</button>
        ${l.sheet_url ? `<button type="button" class="sb-link" data-lightbox="${esc(l.sheet_url)}" data-lb-title="Stage sheet · ${esc(l.name)}">Open the stage sheet</button>${l.sheet_stale ? ` <span class="sb-fallback" role="note">Out of date: pictures changed after you built it.</span>` : ""}` : ""}
        ${l.rendering ? `<p class="sb-hint">Waiting for ${plural(l.rendering, "angle")} to finish.</p>` : ""}
      </div>
      <details class="sb-adv"><summary>More options</summary><div class="sb-adv-actions">
        <button class="btn btn-sm-sb btn-danger-sb" id="sbStDel" type="button">Delete stage</button></div></details>
      <div class="sb-form-actions"><button class="btn btn-ghost btn-md" id="sbStDone" type="button">${sb.returnTo ? "Back to the shot" : "Done"}</button></div></div>`;
  }

  function renderStageSheet() {
    if (sb.mode !== "stage") return;
    const l = sb.openStage ? locOf(sb.openStage) : null;
    if (sb.openStage && !l) { stageBack(); return; }
    if (!l) {
      // The New stage form is drawn once: a background refresh (another take or angle still rendering) must never wipe
      // what the user typed, the picture they chose or the rights box they ticked.
      if ($("sbSheetBody").querySelector("#sbStName[data-new-stage]")) return;
      sheetHead("Stages", "New stage"); $("sbSheetBody").innerHTML = newStageHTML(); wireNewStage(); return;
    }
    const keep = document.activeElement && document.activeElement.id;  // don't lose typing when a render finishes
    const pending = $("sbStBuild") && $("sbStFile") && $("sbStFile").files && $("sbStFile").files.length;  // a new master plate waiting for the rights box
    if (pending || keep === "sbStDesc" || keep === "sbStCheck" || keep === "sbStAngle" || (document.activeElement || {}).classList?.contains("sb-at-name")) { poll(); return; }
    sheetHead("Stage sheet", l.name);
    $("sbSheetBody").innerHTML = stageHTMLFor(l);
    const base = locBase(l.name);
    const put = (body, msg) => run(async () => { setProject(await api(base, { method: "PUT", body: JSON.stringify(body) })); if (msg) toast(msg); });
    const upload = (role, file, extra = {}) => run(async () => {
      const fd = new FormData();
      fd.append("role", role); fd.append("consent", ($("sbStConsent") && $("sbStConsent").checked) || extra.consent ? "true" : "false");
      Object.entries(extra).forEach(([k, v]) => { if (k !== "consent") fd.append(k, v); });
      fd.append("image", file);
      const np = await api(`${base}/upload`, { method: "POST", body: fd });
      if ($("sbStFile")) $("sbStFile").value = "";  // nothing pending any more: let the editor redraw with the new plate
      setProject(np);
      toast(role === "master" ? "New master plate. Build the stage sheet again when you’re done." : role === "empty" ? "Empty plate saved." : `Angle “${esc(extra.angle)}” saved from your picture.`);
    });
    const ownIt = () => confirm("Do you own these pictures or have permission to use them?");
    const make = (angle, seed) => run(async () => {
      setProject(await api(`${base}/angles/${encodeURIComponent(angle)}`, { method: "PUT", body: JSON.stringify({ generate: true, ...(seed ? { seed } : {}) }) }));
      const a = (locOf(l.name).angles || []).find((x) => same(x.name, angle));
      toast(a && a.status === "rendering" ? `Making “${esc(angle)}” from the master plate. You can keep working.` : `Made “${esc(angle)}”.`);
      if (a && a.status === "rendering") poll();
    });
    wireFileThumb($("sbStFile"), "sbStFileThumb");
    wireTakeStrip($("sbSheetBody").querySelector(".sb-stage-ed") || $("sbSheetBody"));
    $("sbStFile").addEventListener("change", (e) => { $("sbStConsentRow").hidden = !e.target.files[0]; if (e.target.files[0]) $("sbStConsent").focus(); });
    $("sbStConsent").addEventListener("change", (e) => { const f = $("sbStFile").files[0]; if (e.target.checked && f) upload("master", f); });
    if ($("sbStTakeSel")) $("sbStTakeSel").addEventListener("change", (e) => { if (e.target.value) put({ from_version: e.target.value }, "Master plate replaced with that take. Build the stage sheet again when you’re done."); });
    $("sbStDesc").addEventListener("blur", (e) => { if (e.target.value !== (l.description || "")) put({ description: e.target.value }, "Set description saved."); });
    $("sbStCheck").addEventListener("blur", (e) => { const v = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean); if (v.join("\n") !== (l.checklist || []).join("\n")) put({ checklist: v }, "Checklist saved."); });
    $("sbStEmpty").addEventListener("change", (e) => { const f = e.target.files[0]; if (f && ownIt()) upload("empty", f, { consent: true }); });
    $("sbSheetBody").querySelectorAll("[data-make]").forEach((b) => b.addEventListener("click", () => make(b.dataset.make)));
    if ($("sbStAngleMake")) {
      $("sbStAngleMake").addEventListener("click", () => { const n = $("sbStAngle").value.trim(); if (!n) { $("sbStAngle").focus(); toast("Name the angle first, e.g. “behind the counter”."); return; } make(n); });
      $("sbStAngle").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("sbStAngleMake").click(); } });
      $("sbStAngleFile").addEventListener("change", (e) => {
        const f = e.target.files[0], n = $("sbStAngle").value.trim();
        if (!f) return;
        if (!n) { e.target.value = ""; $("sbStAngle").focus(); toast("Name the angle first. Then upload its picture."); return; }
        if (ownIt()) upload("angle", f, { angle: n, consent: true });
      });
    }
    $("sbSheetBody").querySelectorAll("[data-regen]").forEach((b) => b.addEventListener("click", () => make(b.dataset.regen)));
    $("sbSheetBody").querySelectorAll("[data-del-angle]").forEach((b) => b.addEventListener("click", () => {
      const n = b.dataset.delAngle;
      if (!confirm(`Remove the angle “${n}”? Shots that use it will use the master plate.`)) return;
      run(async () => { setProject(await api(`${base}/angles/${encodeURIComponent(n)}`, { method: "DELETE" })); toast(`Removed “${esc(n)}”.`); });
    }));
    $("sbSheetBody").querySelectorAll(".sb-at-name").forEach((inp) => {
      const old = inp.closest(".sb-at").dataset.a;
      const commit = () => {
        const nv = inp.value.trim().replace(/\s+/g, " ");
        if (!nv || nv === old) { inp.value = old; return; }
        run(async () => {
          try { setProject(await api(`${base}/angles/${encodeURIComponent(old)}`, { method: "PUT", body: JSON.stringify({ rename: nv }) })); toast(`Renamed to “${esc(nv)}”. Shots that use it also change.`); }
          catch (e) { inp.value = old; throw e; }
        });
      };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); inp.blur(); } if (e.key === "Escape") { inp.value = old; inp.blur(); } });
      inp.addEventListener("blur", commit);
    });
    $("sbStBuild").addEventListener("click", () => run(async () => {
      const b = $("sbStBuild"); b.disabled = true; b.textContent = "Building…";
      try {
        setProject(await post(`${base}/sheet`));
        const nl = locOf(l.name);
        const miss = nl.readiness.filter((r) => !r.optional && !r.done && r.id !== "sheet").map((r) => r.label.toLowerCase());
        toast(nl.ready ? `Stage sheet for “${esc(nl.name)}” is ready. Open it and look at the stage to check it.` : `Built. Still missing: ${esc(miss.join(", "))}.`);
      } finally { if (b.isConnected) { b.disabled = false; } }
    }));
    $("sbStDel").addEventListener("click", () => {
      if (!confirm(`Delete the stage “${l.name}”? ${l.shots_using ? `${plural(l.shots_using, "shot")} will have no stage. ` : ""}Takes you made stay.`)) return;
      run(async () => { const np = await api(base, { method: "DELETE" }); sb.openStage = null; setProject(np); stageBack(); toast(`Deleted the stage “${esc(l.name)}”.`); });
    });
    $("sbStDone").addEventListener("click", stageBack);
    if (l.rendering) poll();
  }

  // ---------------------------------------------------------------- new shot
  function openNew(keepDraft) {
    sb.mode = "new";
    sb.openShot = null;
    const p = sb.project;
    if (!keepDraft || !sb.draft) sb.draft = { beat: "", prompt: "", camera: "static", characters: p.character && castOf(p.character) ? [castOf(p.character).name] : [] };
    const d = sb.draft;
    sheetHead(`Shot ${p.shots.length + 1}`, "New shot");
    $("sbSheetBody").innerHTML = `<div class="sb-form">
      <div class="field"><label for="sbNewBeat">Name</label><input id="sbNewBeat" type="text" maxlength="120" value="${esc(d.beat)}" placeholder="e.g. Cold open" autocomplete="off" /></div>
      <div class="field"><label for="sbNewPrompt">What happens?</label><textarea id="sbNewPrompt" rows="3" placeholder="e.g. 3 AM, rain on the window. She reads at the register.">${esc(d.prompt)}</textarea></div>
      <div class="field"><span class="label">Who’s in it</span><div class="sb-castpick" id="sbNewCast" role="group" aria-label="Who’s in it">${castPickHTML(d.characters)}</div></div>
      <div class="field"><label for="sbNewCam">Camera</label><select id="sbNewCam">${camOptions(d.camera)}</select></div>
      <div class="sb-form-actions"><button class="btn btn-ghost btn-md" id="sbNewCancel" type="button">Cancel</button><button class="btn btn-primary btn-md" id="sbNewAdd" type="button">Add shot</button></div></div>`;
    showSheet(true);
    const sync = () => { d.beat = $("sbNewBeat").value; d.prompt = $("sbNewPrompt").value; d.camera = $("sbNewCam").value; };
    const recast = () => { $("sbNewCast").innerHTML = castPickHTML(d.characters); wireCastPick($("sbNewCast"), () => d.characters, (c) => { d.characters = c; recast(); }, (n) => { sync(); openCharacter(n); }); };
    recast();
    $("sbNewBeat").focus();
    $("sbNewCancel").addEventListener("click", () => { sb.draft = null; showSheet(false); });
    $("sbNewAdd").addEventListener("click", () => run(async () => {
      sync();
      if (!d.beat.trim()) { $("sbNewBeat").focus(); throw new Error("Give the shot a name."); }
      const np = await post(`/projects/${p.id}/shots`, { beat: d.beat, prompt: d.prompt, camera: d.camera, characters: d.characters });
      sb.draft = null;
      setProject(np);
      openShot(np.shots[np.shots.length - 1].id);
    }));
  }

  // ---------------------------------------------------------------- new story: blank, template or script
  async function newStory(opts) {
    const want = (opts && opts.template) || "blank";
    renderPicker(sb.project && sb.project.id);
    if (!sb.templates.length) { try { sb.templates = (await api("/templates")).templates; } catch (_) { sb.templates = []; } }
    await loadCast();  // the lead picker lists characters made in Create since the page loaded
    sb.mode = "story";
    sheetHead("New story", "What are you making?");
    let pick = want;
    let lead = "";
    let typed = "";
    const tcard = (t) => `<button type="button" class="sb-tpl ${t.id === pick ? "on" : ""}" data-t="${esc(t.id)}" role="radio" aria-checked="${t.id === pick}" tabindex="${t.id === pick ? 0 : -1}">
        <span class="sb-tpl-t">${esc(t.title)}</span><span class="sb-tpl-b">${esc(t.blurb)}</span>
        <span class="sb-tpl-n">${t.id === "script" ? "You paste it, we split it" : t.shots ? plural(t.shots, "shot") + " · " + esc(t.beats.slice(0, 4).join(", ")) + (t.beats.length > 4 ? "…" : "") : "Empty"}</span></button>`;
    const options = [...sb.templates, { id: "script", title: "From a script", blurb: "Paste a short script. Each scene or line becomes a named shot with a suggested cast and camera.", shots: 0, beats: [] }];
    const draw = () => {
      $("sbSheetBody").innerHTML = `<div class="sb-form">
        <div class="field"><label for="sbStoryName">Story name</label><input id="sbStoryName" type="text" maxlength="80" placeholder="e.g. The Last Bus" autocomplete="off" /></div>
        <div class="field"><span class="label">Start from</span><div class="sb-tpls" role="radiogroup" aria-label="Start from">${options.map(tcard).join("")}</div></div>
        <div class="field" id="sbLeadField"><span class="label">Lead character <span class="optional">(optional)</span></span>
          <div class="sb-castpick" role="radiogroup" aria-label="Lead character">
            <button type="button" class="sb-chip ${lead ? "" : "on"}" data-lead="" aria-pressed="${!lead}">Nobody yet</button>
            ${sb.cast.map((c) => `<button type="button" class="sb-chip ${same(lead, c.name) ? "on" : ""}" data-lead="${esc(c.name)}" aria-pressed="${same(lead, c.name)}">${hasPic(c) ? `<img src="${esc(cardPic(c))}" alt="" />` : `<span class="sb-initial">${initial(c.name)}</span>`}${esc(c.name)}</button>`).join("")}
          </div><span class="hint">New shots include the lead character. You can change the cast of each shot later.</span></div>
        <div id="sbScriptBox"></div>
        <div class="sb-form-actions" id="sbStoryActions"><button class="btn btn-ghost btn-md" id="sbStoryCancel" type="button">Cancel</button><button class="btn btn-primary btn-md" id="sbStoryMake" type="button">Create story</button></div>
      </div>`;
      const name = $("sbStoryName");
      name.value = typed;
      name.addEventListener("input", () => { typed = name.value; });
      $("sbSheetBody").querySelectorAll(".sb-tpl").forEach((b) => b.addEventListener("click", () => { pick = b.dataset.t; draw(); }));
      $("sbSheetBody").querySelector(".sb-tpls").addEventListener("keydown", (e) => {  // radio group: arrow keys move the choice
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!step) return;
        e.preventDefault();
        const ids = options.map((t) => t.id);
        pick = ids[(ids.indexOf(pick) + step + ids.length) % ids.length];
        draw();
        const on = $("sbSheetBody").querySelector(`.sb-tpl[data-t="${CSS.escape(pick)}"]`);
        if (on) on.focus();
      });
      $("sbSheetBody").querySelectorAll("[data-lead]").forEach((b) => b.addEventListener("click", () => { lead = b.dataset.lead; draw(); }));
      $("sbStoryCancel").addEventListener("click", () => showSheet(false));
      if (pick === "script") {
        $("sbLeadField").hidden = true;
        $("sbStoryActions").hidden = true;
        scriptEditor($("sbScriptBox"), { onDone: async (shots, title) => {
          const p = await post("/projects", { title: name.value.trim() || title || "Untitled story", shots });
          showSheet(false); await loadProjects(p.id); toast(`Made “${esc(p.title)}” with ${plural(p.shots.length, "shot")}. Every shot stays editable.`);
        }, doneLabel: (n) => `Create story with ${plural(n, "shot")}`, onTitle: (t) => { if (t && !name.value.trim()) { name.value = t; typed = t; } } });
      }
      $("sbStoryMake").addEventListener("click", () => run(async () => {
        const p = await post("/projects", { title: name.value, template: pick, character: lead });
        showSheet(false);
        await loadProjects(p.id);
        toast(p.shots.length ? `Made “${esc(p.title)}” from a template: ${plural(p.shots.length, "shot")}, all editable.` : `Made “${esc(p.title)}”. Add your first shot.`);
      }));
      const ta = pick === "script" && $("sbScriptBox").querySelector("textarea");
      (ta || name).focus();
    };
    draw();
    showSheet(true);
  }

  // ---------------------------------------------------------------- script → shots (editable before anything is saved)
  function scriptEditor(box, { onDone, doneLabel, onTitle }) {
    let rows = null;
    let notes = [];
    const rowHTML = (r, i) => `<li class="sb-srow" data-i="${i}">
        <span class="sb-srow-n">${i + 1}</span>
        <div class="sb-srow-main">
          <input class="sb-srow-beat" type="text" maxlength="120" value="${esc(r.beat)}" aria-label="Name of shot ${i + 1}" />
          <textarea class="sb-srow-prompt" rows="2" maxlength="2000" aria-label="What happens in shot ${i + 1}">${esc(r.prompt)}</textarea>
          <div class="sb-srow-meta">
            <label>Cast <input class="sb-srow-cast" type="text" value="${esc(r.characters.join(", "))}" placeholder="nobody" aria-label="Cast of shot ${i + 1}, separated by commas" list="sbCastNames" /></label>
            <label>Camera <select class="sb-srow-cam" aria-label="Camera for shot ${i + 1}">${camOptions(r.camera)}</select></label>
            <label class="sb-srow-says">${r.speaker ? `${esc(r.speaker)} says` : "Says"} <input class="sb-srow-line" type="text" maxlength="500" value="${esc(r.line || "")}" placeholder="no line" aria-label="Spoken line of shot ${i + 1}" /></label>
            ${r.why && r.why.camera ? `<span class="sb-why">camera from ${esc(r.why.camera)}</span>` : ""}
          </div>
        </div>
        <button type="button" class="sb-srow-x" data-x="${i}" aria-label="Remove shot ${i + 1}" title="Remove"><svg><use href="#i-trash"/></svg></button>
      </li>`;
    const read = () => box.querySelectorAll(".sb-srow").forEach((li) => {
      const r = rows[Number(li.dataset.i)];
      r.beat = li.querySelector(".sb-srow-beat").value;
      r.prompt = li.querySelector(".sb-srow-prompt").value;
      r.characters = li.querySelector(".sb-srow-cast").value.split(",").map((x) => x.trim()).filter(Boolean);
      r.camera = li.querySelector(".sb-srow-cam").value;
      r.line = li.querySelector(".sb-srow-line").value;
      if (r.speaker && !r.characters.some((n) => same(n, r.speaker))) r.speaker = "";
    });
    const draw = () => {
      const text = box.querySelector("#sbScript") ? box.querySelector("#sbScript").value : (draw.text || "");
      draw.text = text;
      box.innerHTML = `<div class="field"><label for="sbScript">Your script</label>
          <textarea id="sbScript" rows="${rows ? 4 : 9}" maxlength="20000" placeholder="${esc("INT. BUS STOP - NIGHT\nRain. Kai waits alone under a flickering light. Close on his face.\nKAI\nCome on, come on.\n\nEXT. ROAD\nThe bus appears. The camera pulls back to reveal the empty city.")}">${esc(text)}</textarea>
          <span class="hint">Scenes (INT./EXT., ## headings, “Scene 2:”), numbered lines or paragraphs each become a shot. A line like <em>KAI: Hi</em> adds the speaker to the cast. Words like “close on”, “pulls back” or <em>[camera: orbit]</em> pick a camera. Runs on this computer, no model needed.</span></div>
        <div class="sb-form-actions left"><button class="btn ${rows ? "btn-ghost" : "btn-primary"} btn-md" id="sbSplit" type="button">${rows ? "Split again" : "Split into shots"}</button></div>
        ${rows ? `<p class="sb-label">${plural(rows.length, "shot")} · edit anything, then ${esc(doneLabel(rows.length).toLowerCase())}</p>
          ${notes.map((n) => `<p class="sb-note">${esc(n)}</p>`).join("")}
          <ol class="sb-srows">${rows.map(rowHTML).join("")}</ol>
          <datalist id="sbCastNames">${sb.cast.map((c) => `<option value="${esc(c.name)}"></option>`).join("")}</datalist>
          <div class="sb-form-actions"><button class="btn btn-ghost btn-md" id="sbAddRow" type="button">Add a shot</button><button class="btn btn-primary btn-md" id="sbScriptDone" type="button" ${rows.length ? "" : "disabled"}>${esc(doneLabel(rows.length))}</button></div>` : ""}`;
      box.querySelector("#sbSplit").addEventListener("click", () => run(async () => {
        const r = await post("/script/split", { text: box.querySelector("#sbScript").value });
        rows = r.shots; notes = r.notes || [];
        if (onTitle) onTitle(r.title);
        draw();
      }));
      if (!rows) { box.querySelector("#sbScript").focus(); return; }
      box.querySelectorAll("[data-x]").forEach((b) => b.addEventListener("click", () => { read(); rows.splice(Number(b.dataset.x), 1); draw(); }));
      box.querySelector("#sbAddRow").addEventListener("click", () => { read(); rows.push({ beat: `Shot ${rows.length + 1}`, prompt: "", characters: [], camera: "static", line: "", speaker: "" }); draw(); });
      box.querySelector("#sbScriptDone").addEventListener("click", () => run(async () => {
        read();
        const bad = rows.findIndex((r) => !r.beat.trim());
        if (bad >= 0) throw new Error(`Shot ${bad + 1} needs a name.`);
        await onDone(rows.map(({ beat, prompt, characters, camera, line, speaker, kind, card_title, card_sub }) => ({ beat, prompt, characters, camera, line: line || "", speaker: speaker || "",
          ...(kind === "card" ? { kind, card_title: card_title || "", card_sub: card_sub || "" } : {}) })));  // OS-063: a card line stays a card
      }));
    };
    draw();
  }

  function openScript() {
    sb.mode = "script";
    sheetHead(sb.project.title, "Add shots from a script");
    $("sbSheetBody").innerHTML = `<div class="sb-form" id="sbScriptWrap"></div>`;
    showSheet(true);
    scriptEditor($("sbScriptWrap"), { doneLabel: (n) => `Add ${plural(n, "shot")}`, onDone: async (shots) => {
      const np = await post(`/projects/${sb.project.id}/shots/batch`, { shots });
      showSheet(false); setProject(np); toast(`Added ${plural(shots.length, "shot")} at the end. Drag them anywhere.`);
    } });
  }

  // ---------------------------------------------------------------- export view
  function renderExport() {
    const p = sb.project;
    const keepers = p.shots.filter((s) => keeperOf(s) && !keeperOf(s).unapproved && !keeperOf(s).preview_only);  // the server skips these too
    const unapproved = p.shots.some((s) => keeperOf(s) && keeperOf(s).unapproved);
    const preview = p.shots.some((s) => keeperOf(s) && keeperOf(s).preview_only);
    const skipped = p.shots.length - keepers.length;
    const allowListed = !!p.demo || unapproved || preview;  // OS-065: black fill is for shots with no keeper only
    const fillBox = $("sbFillGaps");
    if (fillBox) { fillBox.closest(".sb-fill").hidden = !skipped || allowListed || !keepers.length; fillBox.onchange = () => renderExport(); }
    const placeholders = keepers.filter((s) => keeperOf(s).placeholder).length;
    const stills = keepers.filter((s) => ["frame", "concept"].includes(keeperOf(s).kind)).length;  // OS-026
    sb.exportStills = stills;
    $("sbExportLead").innerHTML = !p.shots.length ? "This story has no shots yet. Return to the storyboard to add shots."
      : !keepers.length && preview ? "The demo’s Shot 1 take is a preview. It plays in the app, but the export skips it. Make your own takes to export the story."
      : !keepers.length && unapproved ? "No approved take yet. OpenSoul keeps the demo story's earlier takes but does not export them. Make new takes to export the story."
      : !keepers.length ? "No shot has a keeper yet. Open a shot. Make a take. Then click <strong>Use this take</strong>."
      : `Exports ${plural(keepers.length, "keeper")} in this order as one ${p.aspect === "9:16" ? "vertical" : "16:9"} MP4.${skipped ? ` ${plural(skipped, "shot")} without ${unapproved ? "an approved" : "a"} keeper ${skipped === 1 ? "is" : "are"} ${!allowListed && fillOn() ? `black for ${skipped === 1 ? "its" : "their"} length` : "skipped"}.` : ""}${placeholders ? ` ${placeholders} ${placeholders === 1 ? "is a Preview take" : "are Preview takes"}, so this is a Preview export.` : ""}`
        + (stills ? ` <strong>${stills === 1 ? "1 keeper is a still frame" : `${stills} keepers are still frames`}.</strong> A still frame shows as a still picture. To animate it, open the shot. Then click <strong>Animate this frame</strong>.` : "");
    $("sbExport").disabled = !keepers.length;
    loadSongs(p.id);
    const allowList = !!p.demo || unapproved || preview || p.shots.some((s) => s.versions.some((v) => v.unapproved));
    const CLAPPER = `<svg class="sb-reel-ph" aria-hidden="true" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="9" width="18" height="11" rx="1.5"/><path d="M3 9h18M4 9l1-4h15l1 4M8 5l2 4M13 5l2 4M18 5l1.5 3"/></svg>`;
    $("sbReel").innerHTML = p.shots.map((s, i) => {
      const k = keeperOf(s);
      // One blank tile, one status and one action for every skipped shot: the demo story (an approved-take allow-list) says
      // "no approved take", other stories "no keeper"; every card has Open shot.
      const kept = k && !k.unapproved && !k.preview_only;
      const why = allowList ? "no approved take" : "no keeper";
      const thumb = kept && (k.card_url || k.poster_url) ? `<img src="${esc(k.card_url || k.poster_url)}" alt="" />`
        : kept ? `<span>${esc(k.id)}</span>` : CLAPPER;  // a faint clapper, no text: the status line says why
      const state = kept ? `${esc(k.id)} · ${esc(kindLabel(k))}${isSample(k) ? " · sample" : k.placeholder ? " · placeholder" : ""}` : `Skipped · ${why}`;
      // OS-061: each shot is cut to its Length, from its Start in the keeper. Empty Length = the whole take (a still: 3 s).
      const isVid = kept && !!k.video_url;
      const cut = cutOf(s);
      const trim = kept ? `<div class="sb-reel-cut" role="group" aria-label="Cut for shot ${i + 1}">
          ${isVid ? `<label>Start <input type="number" min="0" max="60" step="0.1" inputmode="decimal" data-trim="${esc(s.id)}" value="${s.trim_start ? esc(String(s.trim_start)) : ""}" placeholder="0" aria-label="Start of shot ${i + 1} in seconds" /> s</label>` : ""}
          <label>Length <input type="number" min="1" max="20" step="0.5" inputmode="decimal" data-len="${esc(s.id)}" value="${s.seconds ? esc(String(s.seconds)) : ""}" placeholder="${isVid && k.take_seconds ? esc(String(k.take_seconds)) : "3"}" aria-label="Length of shot ${i + 1} in seconds" /> s</label></div>
        <p class="sb-reel-s">In the cut: ${cut ? `${cut.toFixed(1)} s` : "the whole take"}${isVid && k.take_seconds ? ` of ${Number(k.take_seconds).toFixed(1)} s` : ""}</p>` : "";
      return `<li class="${kept ? "" : "skip"}"><div class="sb-reel-t">${thumb}</div><div class="sb-reel-m"><span class="sb-num">Shot ${i + 1}</span>
        <p class="sb-reel-b" title="${esc(s.beat)}">${esc(s.beat)}</p><p class="sb-reel-s">${state}</p>${trim}
        <button class="sb-link" type="button" data-open="${esc(s.id)}">Open shot</button></div></li>`;
    }).join("");
    $("sbReel").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { setView("storyboard"); openShot(b.dataset.open); }));
    const saveCut = (sid, body) => run(async () => { setProject(await patch(`/projects/${p.id}/shots/${sid}`, body)); renderExport(); });
    $("sbReel").querySelectorAll("[data-trim]").forEach((x) => x.addEventListener("change", () => saveCut(x.dataset.trim, { trim_start: x.value === "" ? 0 : Number(x.value) })));
    $("sbReel").querySelectorAll("[data-len]").forEach((x) => x.addEventListener("change", () => saveCut(x.dataset.len, { seconds: x.value === "" ? 0 : Number(x.value) })));
    const total = p.shots.reduce((t, s) => t + (cutOf(s) || 0), 0);
    const tl = $("sbExportTotal");
    if (tl) tl.textContent = keepers.length ? `Length of the cut: about ${total.toFixed(1)} s (${plural(p.shots.length, "shot")}). Set a Length on a shot to cut it to that length.` : "";
  }
  function fillOn() { const x = $("sbFillGaps"); return !x || x.checked; }
  // OS-061: seconds a shot runs in the export (null = the whole take, length not known yet).
  function cutOf(s) {
    const k = keeperOf(s);
    const kept = k && !k.unapproved && !k.preview_only;
    if (Number(s.seconds) > 0) return Number(s.seconds);
    if (!kept) return fillOn() && !sb.project.demo ? 3 : null;  // OS-065: black of 3 s when it has no Length
    if (!k.video_url) return 3;
    return k.take_seconds ? Math.max(0, Number(k.take_seconds) - Number(s.trim_start || 0)) : null;
  }

  // OS-024 / OS-029: "Add the song" — a finished Music song under the whole story, ducked under spoken lines.
  async function loadSongs(pid) {
    const sel = $("sbSong");
    if (!sel) return;
    const keep = sel.value;
    try {
      const r = await api(`/projects/${pid}/songs`);
      sel.innerHTML = `<option value="">No song</option>` + r.songs.map((x) => `<option value="${esc(x.song_id)}">${esc(x.title)}${x.for_this_story ? " · made for this story" : ""}</option>`).join("");
      if (r.songs.some((x) => x.song_id === keep)) sel.value = keep;
      $("sbSongHint").textContent = r.songs.length ? "The song plays under the shots. It goes quieter when someone talks."
        : "No song yet. Make a song in Music videos (top bar). Then add it here.";
      sel.disabled = !r.songs.length;
    } catch (e) { sel.disabled = true; }
    $("sbSongLevel").disabled = !sel.value;
  }

  async function exportStory() {
    const b = $("sbExport");
    if (sb.exportStills && !confirm(`${sb.exportStills === 1 ? "1 keeper is a still frame" : `${sb.exportStills} keepers are still frames`}. Export anyway?`)) return;
    b.disabled = true; b.textContent = "Stitching…";
    try {
      const song = $("sbSong") ? $("sbSong").value : "";
      const r = await post(`/projects/${sb.project.id}/export`, { ...(song ? { song, song_level: Number($("sbSongLevel").value) / 100 } : {}), fill_gaps: fillOn() });
      const n = r.plan.items.filter((it) => it.source_kind !== "black").length;
      const box = $("sbExportResult");
      box.hidden = false;
      box.innerHTML = `${r.output_url ? `<video src="${esc(r.output_url)}" controls playsinline></video>` : ""}
        <div><p class="sb-reel-b">Stitched ${plural(n, "keeper")} in order.</p>${r.note ? `<p class="sb-reel-s">${esc(r.note)}</p>` : ""}
        ${r.download_url ? `<a class="btn btn-primary btn-md" href="${esc(r.download_url)}">Download MP4</a>` : ""}</div>`;
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { toast(esc(e.message)); }
    finally { b.disabled = false; b.textContent = "Export story"; }
  }

  // ---------------------------------------------------------------- lightbox (pictures open in the app, never a raw file URL)
  function openLightbox(url, title) {
    closeLightbox();
    const box = document.createElement("div");
    box.id = "sbLightbox"; box.className = "sb-lightbox"; box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", title || "Picture");
    box.innerHTML = `<figure class="sb-lb-fig"><img src="${esc(url)}" alt="${esc(title || "")}" />${title ? `<figcaption>${esc(title)}</figcaption>` : ""}</figure>
      <button type="button" class="sb-lb-close" aria-label="Close">×</button>`;
    box.addEventListener("click", (e) => { if (e.target === box || e.target.closest(".sb-lb-close")) closeLightbox(); });
    document.body.appendChild(box);
    box.querySelector(".sb-lb-close").focus();
  }
  function closeLightbox() { const b = $("sbLightbox"); if (b) b.remove(); }
  document.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest("[data-lightbox]");
    if (t) { e.preventDefault(); openLightbox(t.dataset.lightbox, t.dataset.lbTitle); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("sbLightbox")) { e.stopImmediatePropagation(); closeLightbox(); } }, true);

  // ---------------------------------------------------------------- wire up
  document.querySelectorAll(".vs-btn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  document.querySelectorAll(".sb-goto").forEach((b) => b.addEventListener("click", () => setView("storyboard")));
  $("sbProject").addEventListener("change", (e) => (e.target.value === "__new" ? newStory() : run(() => openProject(e.target.value))));
  $("sbNewStory").addEventListener("click", newStory);
  $("sbFromSong").addEventListener("click", () => {
    if (window.OpenSoulMusic) window.OpenSoulMusic.open({ story: sb.project && !sb.project.demo ? sb.project.id : "" });
    else toast("To make music videos, open the full studio.");
  });
  $("sbSong").addEventListener("change", (e) => { $("sbSongLevel").disabled = !e.target.value; });
  $("sbAddFirst").addEventListener("click", () => openNew());
  $("sbScriptFirst").addEventListener("click", openScript);
  $("sbFromScript").addEventListener("click", openScript);
  $("sbToExport").addEventListener("click", () => setView("export"));
  $("sbBackToBoard").addEventListener("click", () => setView("storyboard"));
  $("sbExport").addEventListener("click", exportStory);
  $("sbClose").addEventListener("click", () => showSheet(false));
  $("sbScrim").addEventListener("click", () => showSheet(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sbSheet").hidden && !(e.target && e.target.matches && e.target.matches("input.sb-sheet-name"))) showSheet(false); });
  fetch("/api/presets").then((r) => r.json()).then((d) => { sb.cameras = d.camera || []; sb.cameraRules = d.camera_rules || null; if (sb.project) render(); }).catch(() => {});
  loadCast();
  // Shorts (was Quick shot, P1-07): one shot in the "Shorts" story (id quick-shots), made if it isn't there yet; opens the new-shot sheet.
  async function quickShot() {
    await loadProjects();
    let q = (sb.projects || []).find((x) => x.id === "quick-shots" || x.title === "Quick shots" || x.title === "Shorts");
    if (!q) { q = await post("/projects", { title: "Shorts" }); await loadProjects(q.id); }
    await openProject(q.id);
    openNew();
  }
  window.OpenSoulStoryboard = { setView, quickShot: () => run(quickShot), openShot: (id) => openShot(id), openStage: (n) => openStage(n), newStory, openScript, state: sb,
    openCharacter: (name) => openCharacter(name || ""), openNew: () => openNew(), loadCast, loadProjects,
    openProject: (id) => run(() => openProject(id)), render: () => sb.project && render(),
    api, post, setProject, poll, toast, keeperOf, kindLabel };
  const v0 = new URLSearchParams(location.search).get("view");
  if (v0 === "storyboard" || v0 === "export") setView(v0);
})();
