/* Six-tab shell: Characters → Stages → Shots → Render → Review → Export, all on the current project.
   The default since unify step 9; the old Create / Storyboard pages stay at ?ui=classic (D2; a later release removes them).
   It reuses the existing pieces: Create's character editor (window.OpenSoulCreate) and the Storyboard
   (window.OpenSoulStoryboard: stages, shots, export). No server paths are shown anywhere. */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const params = new URLSearchParams(location.search);
  const mode = params.get("ui");
  if (mode === "classic") return;  // D2: the old Create / Storyboard pages stay reachable at ?ui=classic for now

  const TABS = ["characters", "stages", "shots", "render", "review", "export"];
  const LEAD = {
    stages: "Places that look the same in every shot: a master plate plus a few angles.",
    shots: "One moment per shot: who is in it, where, the camera and a line to say.",
    render: "First, make a quick Draft of every shot. Then render the best ones in Final quality.",
    review: "Compare the takes side by side. Keep one take per shot. The other takes stay until you remove them.",
    export: "Your keepers, in order, joined into one video of the story.",
  };
  const NEXT = { stages: "shots", shots: "render", render: "review", review: "export" };
  const LABEL = { characters: "Characters", stages: "Stages", shots: "Shots", render: "Render", review: "Review", export: "Export" };
  const st = { tab: null, boot: null, editing: false };
  const SB = () => window.OpenSoulStoryboard;
  const CR = () => window.OpenSoulCreate;

  document.body.classList.add("ui-unified");
  $("ufTabs").hidden = false;

  // A lead line + one "Next" button under the story header, for the tabs that live in the storyboard view.
  const bar = document.createElement("div");
  bar.className = "uf-bar";
  bar.id = "ufBar";
  bar.innerHTML = `<p class="uf-lead" id="ufLead"></p><button class="btn btn-primary btn-md uf-next" id="ufNext" type="button"></button>`;
  const head = document.querySelector("#storyboardView .sb-head");
  if (head) head.after(bar);
  const queue = document.createElement("div");
  queue.className = "uf-queue";
  queue.id = "ufQueue";
  bar.after(queue);

  function setTab(t, { push = true } = {}) {
    if (!TABS.includes(t)) t = "characters";
    st.tab = t;
    document.body.dataset.tab = t;
    document.querySelectorAll("#ufTabs [data-tab]").forEach((b) => {
      const on = b.dataset.tab === t;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    const chars = t === "characters";
    $("ufCharacters").hidden = !chars;
    if (chars) {
      if (SB()) SB().setView("create");
      CR() && CR().setStep(1);
      renderCast();
    } else if (SB()) {
      SB().setView(t === "export" ? "export" : "storyboard");
    }
    $("ufLead").textContent = LEAD[t] || "";
    renderQueue();
    renderExportCards();
    const cur = SB() && SB().state.project;  // fresh takes when you arrive (renders may have finished meanwhile)
    if (cur && (t === "render" || t === "review")) SB().api(`/projects/${encodeURIComponent(cur.id)}`).then((np) => SB().setProject(np)).catch(() => {});
    const n = NEXT[t];
    $("ufNext").hidden = !n;
    if (n) { $("ufNext").textContent = `Next: ${LABEL[n]}`; $("ufNext").dataset.next = n; }
    const url = new URL(location.href);
    url.searchParams.delete("ui");
    url.searchParams.set("tab", t);
    url.searchParams.delete("view");
    if (push) history.replaceState(null, "", url);
    window.scrollTo({ top: 0 });
  }

  // ---------------------------------------------------------------- Characters: the cast grid (+ demo cards)
  async function renderCast() {
    let cast = [];
    try { cast = (await (await fetch("/api/cast")).json()).cast || []; } catch (_) { cast = []; }
    const demos = (st.boot && st.boot.demos) || [];
    const mine = cast.filter((c) => !demos.some((d) => d.name.toLowerCase() === c.name.toLowerCase() && !c.folder));
    const pic = (url, name) => url ? `<img src="${esc(url)}" alt="" loading="lazy" />` : `<span class="uf-ini">${esc((name || "?").slice(0, 1).toUpperCase())}</span>`;
    const card = (c) => {
      const n = (c.variants || []).length;
      const voice = c.voice ? `Voice: ${esc(c.voice[0].toUpperCase() + c.voice.slice(1))}` : "";
      const extra = n ? ` · ${n} other version${n > 1 ? "s" : ""}` : "";
      return `<li><button type="button" class="uf-card${c.card_placeholder ? " uf-ph" : ""}" data-pick="${esc(c.name)}">${pic(c.card_url || c.picture_url, c.name)}
        ${c.card_placeholder ? `<span class="uf-ph-tag">Placeholder</span>` : ""}<span class="uf-name">${esc(c.name)}${c.made_from_text ? ` <span class="uf-badge uf-text">Made from text</span>` : ""}</span><span class="uf-meta">${voice}${extra}</span>${c.card_note ? `<span class="uf-meta">${esc(c.card_note)}</span>` : ""}</button></li>`;
    };
    const demoCard = (d) => `<li><button type="button" class="uf-card demo" data-demo="${esc(d.name)}">${pic(d.card_url || d.sheet_url, d.name)}
        <span class="uf-name">${esc(d.name)} <span class="uf-badge">Demo</span></span><span class="uf-meta">Ready to use</span></button></li>`;
    const demoNames = new Set(demos.map((d) => d.name.toLowerCase()));
    // Example characters that aren't part of the demo film (Pixel) sit under "More examples", still one tap away.
    const cards = mine.filter((c) => !demoNames.has(c.name.toLowerCase()) || c.folder).map((c) => ({ x: c, more: c.more_example, html: card(c) }))
      .concat(demos.filter((d) => !mine.some((c) => c.name.toLowerCase() === d.name.toLowerCase())).map((d) => ({ x: d, more: d.more_example, html: demoCard(d) })));
    const more = cards.filter((c) => c.more);
    $("ufCast").innerHTML = cards.filter((c) => !c.more).map((c) => c.html).join("")
      + `<li><button type="button" class="uf-card add" id="ufNewChar"><span class="uf-plus">+</span><span class="uf-name">New character</span><span class="uf-meta">From a description or a photo</span></button></li>`;
    const mx = $("ufMoreEx");
    if (mx) {
      mx.hidden = !more.length;
      $("ufMoreList").innerHTML = more.map((c) => c.html).join("");
      const b = $("ufMoreBtn");
      b.textContent = `More examples (${more.length})`;
      if (!b.dataset.wired) {
        b.dataset.wired = "1";
        b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", String(open)); $("ufMoreList").hidden = !open; });
      }
    }
    const root = $("ufCast").parentElement;
    root.querySelectorAll("#ufCast [data-pick], #ufMoreEx [data-pick]").forEach((b) => b.addEventListener("click", () => edit(() => CR().pickCharacter(b.dataset.pick))));
    root.querySelectorAll("#ufCast [data-demo], #ufMoreEx [data-demo]").forEach((b) => b.addEventListener("click", () => edit(() => CR().loadDemo(b.dataset.demo))));
    $("ufNewChar").addEventListener("click", () => edit(() => CR().newCharacter()));
  }
  function edit(fn) {
    st.editing = true;
    document.body.classList.add("uf-editing");
    fn();
    const card = document.querySelector(".create-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------------------------------------------------------------- Render + Review: a queue over regenerate / final / keeper
  const isVideo = (v) => v && v.video_url && v.kind !== "concept" && v.kind !== "frame";
  const q = (v) => ((v && v.settings) || {}).quality || "draft";
  function shotState(s) {
    const k = SB().keeperOf(s);
    if (s.kind === "card") return k ? { key: "final", text: `Title card ${k.id}` } : { key: "none", text: "No card yet", act: "Make the card" };  // OS-063
    if (s.versions.some((v) => v.status === "rendering")) return { key: "rendering", text: "Rendering…" };
    if (k && k.missing) return { key: "none", text: `Video missing for ${k.id}: make a new take`, act: "Make a draft" };
    const many = (s.camera_moves || []).length > 2;  // Drafts take 2 camera moves at most: go straight to Final
    if (!s.versions.some(isVideo)) return { key: "none", text: many ? "No take yet · 3 camera moves need Final" : "No take yet", act: many ? "Make a final" : "Make a draft" };
    if (!k) return { key: "pick", text: `${s.versions.length} take${s.versions.length > 1 ? "s" : ""}, no keeper`, act: "Choose in Review" };
    if (q(k) === "final") return { key: "final", text: `Final ${k.id}` };
    const fin = s.versions.find((v) => v.based_on === k.id && q(v) === "final" && v.status === "ready");
    if (fin) return { key: "final-ready", text: `Final ${fin.id} is ready`, act: "Choose in Review" };
    return { key: "draft", text: `Draft ${k.id}`, act: "Render final" };
  }
  function thumb(s) {
    const k = SB().keeperOf(s) || s.versions.filter((v) => v.poster_url).at(-1);
    if (k && k.missing) return `<span class="uf-q-none">Video missing</span>`;
    return k && (k.card_url || k.poster_url) ? `<img src="${esc(k.card_url || k.poster_url)}" alt="" loading="lazy" />`
      : k && k.video_url ? `<video src="${esc(k.video_url)}#t=0.1" muted playsinline preload="metadata" aria-hidden="true"></video>` : `<span class="uf-q-none">No take</span>`;
  }
  // P2-09: the accessible name starts with the words the thumbnail shows ("No take", "Video missing").
  function thumbLabel(s, i) {
    const vis = (thumb(s).match(/uf-q-none">([^<]+)</) || [])[1];
    return vis ? `${esc(vis)}: open shot ${i + 1}` : `Open shot ${i + 1}`;
  }
  async function act(s, a) {
    const sb = SB(), p = sb.state.project, base = `/projects/${p.id}/shots/${s.id}`;
    if (a === "Choose in Review") return setTab("review");
    if (a === "Make the card") { sb.setProject(await sb.post(`${base}/card`, {})); return; }  // OS-063: drawn here, no GPU
    const np = a === "Render final" ? await sb.post(`${base}/final`, { version_id: s.keeper })
      : await sb.post(`${base}/regenerate`, { edit: "", seed: null, from_version: null, quality: a === "Make a final" ? "final" : "draft" });
    sb.setProject(np);
    if (np.shots.some((x) => x.versions.some((v) => v.status === "rendering"))) sb.poll();
  }
  function renderQueue() {
    const sb = SB(), p = sb && sb.state.project, box = $("ufQueue");
    if (!box) return;
    const on = st.tab === "render" || st.tab === "review";
    box.hidden = !on || !p;
    if (!on || !p) return;
    if (!p.shots.length) { box.innerHTML = `<p class="uf-q-empty">This story has no shots yet. <button class="sb-link" type="button" data-next="shots">Add shots first</button></p>`; return; }
    if (st.tab === "render") renderRender(p, box); else renderReview(p, box);
  }
  function renderRender(p, box) {
    const states = p.shots.map(shotState);
    const finals = states.filter((x) => x.key === "final").length;
    const todo = p.shots.filter((s, i) => states[i].key === "none" && states[i].act === "Make a draft");
    const mode = p.dry_run ? " Preview mode: takes are samples from a real render. OpenSoul sends nothing to the GPU." : "";
    box.innerHTML = `<div class="uf-q-top"><p>${finals} of ${p.shots.length} shot${p.shots.length > 1 ? "s" : ""} in Final quality.${mode}</p>
      ${todo.length ? `<button class="btn btn-outline-sb btn-md" id="ufDraftAll" type="button">Draft the ${todo.length} shot${todo.length > 1 ? "s" : ""} with no take</button>` : ""}</div>
      <ol class="uf-q-list" aria-label="Render queue">${p.shots.map((s, i) => {
        const x = states[i];
        return `<li class="uf-q-row ${esc(x.key)}" data-sid="${esc(s.id)}"><button type="button" class="uf-q-thumb" data-open="${esc(s.id)}" aria-label="${thumbLabel(s, i)}">${thumb(s)}</button>
          <div class="uf-q-txt"><span class="uf-q-n">Shot ${i + 1}</span><strong title="${esc(s.beat)}">${esc(s.beat)}</strong><span class="uf-q-st">${esc(x.text)}</span></div>
          ${x.act ? `<button class="btn ${x.key === "draft" ? "btn-primary" : "btn-outline-sb"} btn-md uf-q-act" type="button" data-act="${esc(x.act)}">${esc(x.act)}</button>`
            : x.key === "final" ? `<span class="uf-q-done">✓ Final</span>` : `<span class="uf-q-wait">Working…</span>`}</li>`;
      }).join("")}</ol>`;
    wireRows(p, box);
    const all = $("ufDraftAll");
    if (all) all.addEventListener("click", async () => {
      all.disabled = true;
      try { for (const s of todo) { all.textContent = `Drafting ${s.beat}…`; await act(s, "Make a draft"); } }
      catch (e) { SB().toast(esc(e.message)); } finally { renderQueue(); }
    });
  }
  function renderReview(p, box) {
    const rows = p.shots.map((s, i) => ({ s, i, takes: s.versions.filter((v) => v.status === "ready" && (isVideo(v) || v.poster_url)) })).filter((r) => r.takes.length);
    const hidden = p.shots.some((s) => s.versions.some((v) => v.unapproved));
    if (!rows.length) {
      box.innerHTML = hidden
        ? `<div class="uf-q-empty uf-rv-none"><strong>No approved take yet</strong><p>OpenSoul keeps the demo story's earlier takes but hides them until they pass review. Your new takes appear here so you can compare them.</p><button class="sb-link" type="button" data-next="render">Make drafts in Render</button></div>`
        : `<p class="uf-q-empty">No takes to compare yet. <button class="sb-link" type="button" data-next="render">Make drafts in Render</button></p>`;
      return;
    }
    box.innerHTML = `<ol class="uf-rv-list" aria-label="Takes to compare">${rows.map(({ s, i, takes }) => `<li class="uf-rv-row" data-sid="${esc(s.id)}">
      <div class="uf-rv-head"><span class="uf-q-n">Shot ${i + 1}</span><strong title="${esc(s.beat)}">${esc(s.beat)}</strong><button class="sb-link" type="button" data-open="${esc(s.id)}">Open shot</button></div>
      <ul class="uf-rv-takes${p.aspect === "9:16" ? "" : " wide"}">${takes.slice(-4).map((v) => {
        const keep = v.id === s.keeper;
        const media = isVideo(v) ? `<video src="${esc(v.video_url)}" ${v.poster_url ? `poster="${esc(v.poster_url)}"` : ""} muted loop playsinline preload="metadata" controls></video>`
          : `<img src="${esc(v.poster_url)}" alt="" loading="lazy" />`;
        return `<li class="uf-rv-take ${keep ? "keeper" : ""}">${media}<div class="uf-rv-foot"><span>${esc(v.id)} · ${esc(SB().kindLabel(v))}${q(v) === "final" && SB().kindLabel(v) !== "Final" ? " · Final" : ""}</span>
          ${keep ? `<span class="uf-q-done">✓ Keeper</span>` : `<button class="btn btn-outline-sb btn-sm-sb" type="button" data-keep="${esc(v.id)}">Keep this</button>`}</div></li>`;
      }).join("")}</ul>${takes.length > 4 ? `<p class="uf-rv-more">Showing the latest 4 of ${takes.length} takes. Open the shot for all of them.</p>` : ""}</li>`).join("")}</ol>`;
    wireRows(p, box);
    box.querySelectorAll("[data-keep]").forEach((b) => b.addEventListener("click", async () => {
      const sid = b.closest("[data-sid]").dataset.sid;
      try { SB().setProject(await SB().post(`/projects/${p.id}/shots/${sid}/keeper`, { version_id: b.dataset.keep })); SB().toast(`${esc(b.dataset.keep)} is the keeper now.`); }
      catch (e) { SB().toast(esc(e.message)); }
    }));
  }
  function wireRows(p, box) {
    box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => SB().openShot(b.dataset.open)));
    box.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
      const s = p.shots.find((x) => x.id === b.closest("[data-sid]").dataset.sid);
      b.disabled = true;
      try { await act(s, b.dataset.act); } catch (e) { SB().toast(esc(e.message)); b.disabled = false; }
    }));
  }
  document.addEventListener("os:project", () => renderQueue());

  // ---------------------------------------------------------------- Export: the reel (storyboard) + a vertical clip + credits
  const exp = document.createElement("div");
  exp.className = "uf-exp";
  exp.id = "ufExport";
  const reel = $("sbExportPane");
  if (reel) reel.append(exp);
  function renderExportCards() {
    const sb = SB(), p = sb && sb.state.project;
    if (!p || st.tab !== "export") return;
    const shots = p.shots.map((s, i) => ({ s, i, k: sb.keeperOf(s) })).filter((x) => isVideo(x.k));
    const pick = $("ufClipShot") ? $("ufClipShot").value : "";
    exp.innerHTML = `<section class="uf-exp-card"><h2>Vertical clip</h2>
        <p>One shot as a 9:16 MP4 for a post, with a caption to paste.</p>
        ${shots.length ? `<label class="uf-exp-row"><span>Shot</span><select id="ufClipShot">${shots.map(({ s, i, k }) =>
          `<option value="${esc(s.id)}" ${s.id === pick ? "selected" : ""}>Shot ${i + 1}: ${esc(s.beat)} (${esc(k.id)})</option>`).join("")}</select></label>
        <div class="uf-exp-acts"><button class="btn btn-primary btn-md" id="ufClipGo" type="button">Export vertical MP4</button>
          <button class="btn btn-ghost btn-md" id="ufClipCopy" type="button" hidden>Copy caption</button></div>
        <textarea id="ufClipCaption" rows="2" readonly hidden aria-label="Caption"></textarea><p class="uf-exp-st" id="ufClipSt" role="status"></p>
        <div class="uf-clip-out" id="ufClipOut" hidden></div>`
        : `<p class="uf-exp-st">No shot has a video keeper yet. <button class="sb-link" type="button" data-next="render">Make drafts in Render</button></p>`}</section>`;  // Credits: the one footer link (opens the same dialog), not a second card here
    if ($("ufClipCopy")) $("ufClipCopy").addEventListener("click", async () => {
      const t = $("ufClipCaption");
      try { await navigator.clipboard.writeText(t.value); } catch (_) { t.select(); document.execCommand("copy"); }
      $("ufClipSt").textContent = "Caption copied.";
    });
    if ($("ufClipGo")) $("ufClipGo").addEventListener("click", async () => {
      const x = shots.find((y) => y.s.id === $("ufClipShot").value) || shots[0];
      const b = $("ufClipGo");
      b.disabled = true; $("ufClipSt").textContent = "Preparing your vertical video…";
      try {
        const r = await fetch("/api/share", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_url: x.k.video_url, title: x.s.beat, name: sampleCast(x.k) || x.s.characters[0] || p.title, camera: x.s.camera || null }) });
        const d = await r.json();
        if (!r.ok || !d.mp4_url) throw new Error(d.note || d.detail || "Export failed. Try again.");
        // P1-02: show the clip and a real Download button (a scripted click can't save a file in the app window)
        const prev = x.k.placeholder || p.dry_run;
        const dl = d.mp4_url + (d.mp4_url.includes("?") ? "&" : "?") + "download=1";
        $("ufClipOut").innerHTML = `<video src="${esc(d.mp4_url)}" controls playsinline preload="metadata" aria-label="Vertical clip: ${esc(x.s.beat)}"></video>
          <div class="uf-exp-acts"><a class="btn btn-primary btn-md" href="${esc(dl)}" download="${esc(d.filename)}">Download MP4</a></div>`;
        $("ufClipOut").hidden = false;
        $("ufClipSt").textContent = `Made ${d.filename} (9:16${prev ? ", Preview mode sample" : ""}). Play it below or download it.`;
        $("ufClipCaption").value = d.caption; $("ufClipCaption").hidden = false; $("ufClipCopy").hidden = false;
      } catch (e) { $("ufClipSt").textContent = e.message; } finally { b.disabled = false; }
    });
  }
  document.addEventListener("os:project", () => renderExportCards());

  // ---------------------------------------------------------------- first run: three ways in + the examples slot
  function renderFirst() {
    const fr = (st.boot && st.boot.first_run) || { items: [] };
    const seen = localStorage.getItem("os_first_seen") === "1";
    $("ufFirst").hidden = seen && params.get("first") !== "1";
    // Only review-passed clips reach this list (presets/demo_images.json); with none, the examples block hides.
    // With no passed clip, the right half shows one passed still from the demo story (never labelled as a move).
    const ex = document.querySelector(".uf-examples");
    const items = fr.items || [], still = !items.length && fr.still;
    if (ex) { ex.hidden = !items.length && !still; ex.classList.toggle("still", !!still); }
    $("ufExTitle").textContent = still ? still.title : (fr.title || "Examples");
    if (still) { $("ufExRow").innerHTML = `<figure class="uf-ex-still"><img src="${esc(still.image_url)}" alt="${esc(still.alt || "")}" /><figcaption>${esc(still.caption || "")}</figcaption></figure>`; return; }
    $("ufExRow").innerHTML = items.slice(0, 3).map((it) =>
      `<figure class="uf-ex"><video src="${esc(it.video_url)}" ${it.poster_url ? `poster="${esc(it.poster_url)}"` : ""} muted loop playsinline autoplay preload="metadata"></video>
        <figcaption>${esc(it.title)}</figcaption></figure>`).join("");
  }
  // OS-002: a Preview sample shows its own cast (Juno Pell), whatever the story says. Caption and file name follow the picture.
  const sampleCast = (k) => (k && k.settings && k.settings.sample && k.settings.sample.cast) || "";
  async function goStory(pick) {
    const sb = SB();
    if (!sb) return;
    setTab("shots");
    await sb.loadProjects();
    const ps = sb.state.projects || [];
    const want = pick(ps);
    if (want) await sb.openProject(want.id);
    return want;
  }
  // OS-001: in Preview mode the demo is Juno's 'Spin Cycle', the story the Preview sample clips come from.
  $("ufTryDemo").addEventListener("click", () => goStory((ps) => ps.find((p) => p.preview_demo) || ps.find((p) => /lumi/i.test(p.id)) || ps.find((p) => p.id !== "quick-shots")));
  $("ufQuick").addEventListener("click", () => { setTab("shots"); SB() && SB().quickShot(); });
  // Top-bar Shorts (was Quick shot, P1-08): the new single-shot flow, not the old ?ui=classic page.
  const quickNow = () => { setTab("shots"); if (SB()) SB().quickShot(); };
  if ($("toQuickShot")) $("toQuickShot").addEventListener("click", (e) => { e.preventDefault(); quickNow(); });
  if (params.get("quick") === "1") window.addEventListener("load", () => setTimeout(quickNow, 0));
  $("ufScript").addEventListener("click", () => { setTab("shots"); SB() && SB().newStory({ template: "script" }); });
  const describeFirst = () => {
    setTab("characters"); edit(() => CR().newCharacter());
    const n = $("name"); if (n) n.focus({ preventScroll: true });  // P2-03: focus moves to the form, not just the scroll
  };
  $("ufDescribe").addEventListener("click", describeFirst);
  $("ufFirstClose").addEventListener("click", () => { localStorage.setItem("os_first_seen", "1"); $("ufFirst").hidden = true; });

  // ---------------------------------------------------------------- wiring
  document.querySelectorAll("#ufTabs [data-tab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  document.addEventListener("click", (e) => {
    const n = e.target.closest && e.target.closest(".uf-next[data-next], #ufQueue [data-next]");
    if (n) setTab(n.dataset.next);
  });
  document.addEventListener("os:cast", () => { if (st.tab === "characters") renderCast(); });
  // The old "Choose a shot" / "Open the Storyboard" links lead into the tabs instead.
  if ($("toStep2")) $("toStep2").addEventListener("click", (e) => { e.stopImmediatePropagation(); setTab("shots"); }, true);

  // A fresh profile (first visit, no tab asked for) lands on New character, Describe: words first, no photo needed.
  const freshLanding = !localStorage.getItem("os_landed") && !params.get("tab") && !params.get("view") && !params.get("demo");
  fetch("/api/bootstrap").then((r) => r.json()).then((d) => {
    st.boot = d; renderFirst(); if (st.tab === "characters") renderCast();
    if (freshLanding && CR()) {
      localStorage.setItem("os_landed", "1");
      st.editing = true; document.body.classList.add("uf-editing"); CR().newCharacter();  // no scroll: the hero stays in view
    }
  }).catch(() => {});
  const fromView = { storyboard: "shots", export: "export" }[params.get("view")];  // old links keep working
  const toModels = params.get("tab") === "models";  // Models is its own tab (models.js), shown over the steps: ?tab=models -> ?models=1
  setTab((!toModels && params.get("tab")) || fromView || "characters", { push: true });
  if (toModels) { const u = new URL(location.href); u.searchParams.set("models", "1"); history.replaceState(null, "", u); }
  window.OpenSoulUnified = { setTab, state: st };
})();
