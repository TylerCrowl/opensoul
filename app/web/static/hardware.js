/* Settings view + hardware picker. Asks /api/hardware/recommend which models fit this computer and shows one card per
   stage (model, precision, memory measured or estimated, tested/untested, licence, why). Detection happens on the
   server, locally (nvidia-smi, /proc/meminfo); nothing here talks to another machine. Preview mode can show any
   simulated computer (?simulate=spark|spark_x2|rtx5090|rtx24|cpu, plus the advisory ones in presets/model_manifest.yaml
   such as rtx4060 or mac32). When the picker has no stack for a computer (8-16 GB cards, Macs, CPU only) it shows a
   recommendation-only tier from the model manifest instead of a bare "no recommendation". The licence filter
   (?commercial=allowed|open_only) marks cards whose licence it hides. Open with the Settings button or ?settings=1. */
(() => {
  const $ = (id) => document.getElementById(id);
  const view = $("settingsView");
  const btn = $("settingsLink");
  const intro = $("hwIntro");
  if (!view || !btn) return;
  const qs = new URLSearchParams(location.search);
  const st = { sim: qs.get("simulate") || "", tier: qs.get("tier") || "", commercial: qs.get("commercial") || "any", data: null, busy: false };
  const INTRO_KEY = "opensoul.hwIntroSeen";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const gb = (n) => (n == null ? "" : `${Number(n) % 1 ? Number(n).toFixed(1) : n} GB`);

  view.innerHTML = `
    <header class="hw-head">
      <h1 id="hwH">Settings</h1>
      <p>Choose how OpenSoul looks and which open models suit this computer.</p>
    </header>
    <div id="settingsExtra"></div>
    <section class="hw-card" aria-labelledby="hwPickH">
      <h2 id="hwPickH">Models for this computer</h2>
      <p class="hw-found" id="hwFound" role="status">Checking this computer…</p>
      <div class="hw-controls">
        <label for="hwTier">Recommend models for
          <select id="hwTier"></select>
        </label>
        <label for="hwMachines">Computers in your studio
          <select id="hwMachines"></select>
          <small id="hwMachinesNote"></small>
        </label>
        <label for="hwLic">Licenses to show
          <select id="hwLic">
            <option value="any">Every allowed license</option>
            <option value="allowed">Commercial use allowed (incl. conditions)</option>
            <option value="open_only">Open licenses only</option>
          </select>
          <small>LTX, LatentSync and Orpheus allow commercial use with conditions</small>
        </label>
        <label for="hwSim" id="hwSimWrap" hidden>Preview as
          <select id="hwSim"></select>
          <small>Preview mode only: no real detection</small>
        </label>
      </div>
      <div id="hwBody" aria-live="polite"></div>
      <section class="hw-voices" id="hwVoices" aria-labelledby="hwVoH" hidden>
        <h3 id="hwVoH">Voice options</h3>
        <ul id="hwVoList"></ul>
      </section>
      <details class="hw-more" id="hwMore">
        <summary>Models we don’t offer, and why</summary>
        <ul id="hwNot"></ul>
      </details>
      <p class="hw-foot">“Tested (measured on Spark)” numbers come from real runs on one DGX Spark (docs/HARDWARE_MEMORY.md). We calculate “Untested (estimate)” numbers from file sizes; we did not run them on that hardware. Every model listed allows commercial use. “Open weights, use-restricted” means the license allows commercial use but prohibits some uses. Videos made with LTX carry the AI-generated label.</p>
    </section>`;

  function badge(c) {
    if (c.tested && c.memory_kind === "measured") return `<span class="hw-badge tested">Tested · measured on Spark</span>`;
    if (c.badge === "planned (estimate)") return `<span class="hw-badge planned">Planned · estimate</span>`;
    return `<span class="hw-badge untested">Untested · estimate</span>`;
  }
  // The licence class badge: only the use-restricted class gets one (amber), with its one-line explanation.
  function licBadge(c) {
    return c.license_class === "use_restricted"
      ? `<span class="hw-badge restricted" title="${esc(c.license_class_explain)}">${esc(c.license_class_label)}</span>` : "";
  }
  function licExplain(c) {
    return c.license_class === "use_restricted" ? `<p class="hw-lic-explain">${esc(c.license_class_explain)}</p>` : "";
  }
  function memory(c) {
    if (c.memory_kind === "measured") {
      const range = c.measured_low_gb != null ? `${Math.round(c.measured_low_gb)}–${Math.round(c.measured_gb)} GB` : gb(c.measured_gb);
      return `${range} <span class="hw-mem-k">measured</span>`;
    }
    return `about ${gb(c.est_gb)} <span class="hw-mem-k">estimate</span>`;
  }
  function licNote(c) {
    return [c.license_note || (c.ai_label ? "Every video carries the AI-generated label." : ""),
      c.license_verified ? "" : "License not verified."].filter(Boolean).join(" ");
  }
  function stage2(s) {
    if (!s) return "";
    const lic = licNote(s);
    return `<div class="hw-stage2">
      <p class="hw-stage2-h">Optional Stage 2 · ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.model)}</a>` : esc(s.model)}</p>
      <p class="hw-badges">${badge(s)}${licBadge(s)}</p>
      <dl class="hw-facts">
        <dt>Memory</dt><dd title="${esc(s.memory_detail)}">${memory(s)}</dd>
        <dt>License</dt><dd>${esc(s.license)}</dd>
      </dl>
      ${licExplain(s)}
      <p class="hw-why">${esc(s.why)}</p>
      ${lic ? `<p class="hw-lic">${esc(lic)}</p>` : ""}
    </div>`;
  }
  function hiddenCard(label, c) {
    return `<li class="hw-stage hw-hidden"><p class="hw-stage-name"><span>${esc(label)}</span></p>
      <p class="hw-why">Hidden by the license filter${c && c.license ? ` (${esc(c.license)})` : ""}.</p></li>`;
  }
  // Recommendation-only card (presets/model_manifest.yaml advisory tiers): never a tested or app-run claim.
  function advCard(c) {
    if (c.hidden_by_license_filter) return hiddenCard(c.slot_label);
    const m = c.model;
    if (!m) return `<li class="hw-stage" data-slot="${esc(c.slot)}"><p class="hw-stage-name"><span>${esc(c.slot_label)}</span></p>
      <h4>No local pick</h4><p class="hw-why">${esc(c.note)}</p></li>`;
    const mem = m.memory && m.memory.est_gb != null ? `about ${gb(m.memory.est_gb)} <span class="hw-mem-k">${esc(m.memory.source)}</span>` : "not known";
    return `<li class="hw-stage" data-slot="${esc(c.slot)}">
      <p class="hw-stage-name"><span>${esc(c.slot_label)}</span><span>${m.in_app ? "In the app" : "Not in the app yet"}</span></p>
      <h4>${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.label)}</a>` : esc(m.label)}</h4>
      <p class="hw-badges"><span class="hw-badge untested">Recommendation only</span>${licBadge(m)}</p>
      <dl class="hw-facts">
        <dt>Memory</dt><dd title="${esc(m.memory && m.memory.basis)}">${mem}</dd>
        <dt>Download</dt><dd>${m.weights_gb != null ? gb(m.weights_gb) : "not checked"}</dd>
        <dt>License</dt><dd>${esc(m.license)}</dd>
      </dl>
      ${c.note ? `<p class="hw-why">${esc(c.note)}</p>` : ""}
      ${!m.in_app && m.in_app_note ? `<p class="hw-lic">${esc(m.in_app_note)}</p>` : ""}
    </li>`;
  }
  function advisoryBody(a) {
    const mac = (a.mac_caveats || []).length
      ? `<div class="hw-note hw-mac"><h4>Mac notes</h4><ul>${a.mac_caveats.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
    return `<div class="hw-tier hw-advisory"><div class="hw-tier-title"><h3>${esc(a.label)}</h3>
        <span class="hw-badge untested">${esc(a.status_label)}</span></div>
        <p>${esc(a.verdict)}</p>
        <p class="hw-note">Recommendation only: these are estimates or figures from the tools' authors. We did not test them, and they don't change what the app runs.</p>
      </div>
      <ol class="hw-grid">${a.cards.map(advCard).join("")}</ol>${mac}`;
  }
  function card(c, multi) {
    if (c.hidden_by_license_filter) return hiddenCard(c.stage_label, c);
    const lic = licNote(c);
    return `<li class="hw-stage" data-stage="${esc(c.stage)}">
      <p class="hw-stage-name"><span>${esc(c.stage_label)}</span>${multi && c.machine_label ? `<span>${esc(c.machine_label)}</span>` : ""}</p>
      <h4>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.model)}</a>` : esc(c.model)}</h4>
      <p class="hw-badges">${badge(c)}${c.recommended ? `<span class="hw-badge rec">Recommended</span>` : ""}${licBadge(c)}</p>
      <dl class="hw-facts">
        <dt>Precision</dt><dd>${esc(c.precision)}</dd>
        <dt>Memory</dt><dd title="${esc(c.memory_detail)}">${memory(c)}</dd>
        <dt>License</dt><dd>${esc(c.license)}</dd>
      </dl>
      ${licExplain(c)}
      <p class="hw-why">${esc(c.why)}</p>
      ${c.app_default_note ? `<p class="hw-lic">${esc(c.app_default_note)}</p>` : ""}
      ${lic ? `<p class="hw-lic">${esc(lic)}</p>` : ""}
      ${stage2(c.stage2)}
    </li>`;
  }
  function voiceItem(v) {
    const lic = licNote(v);
    return `<li class="hw-voice" data-voice="${esc(v.model_id)}">
      <div class="hw-voice-h"><strong>${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.model)}</a>` : esc(v.model)}</strong>
        <span class="hw-badge ${v.status === "recommended" ? "rec" : v.status === "not_in_app" ? "none" : "app"}">${esc(v.status_label)}</span>${licBadge(v)}</div>
      <p class="hw-voice-lic">License: ${esc(v.license)}${v.weights_gb ? ` · ${gb(v.weights_gb)} download` : ""}${v.license_verified ? "" : " · not verified"}</p>
      ${licExplain(v)}
      <p class="hw-why">${esc(v.note)}</p>
      ${lic ? `<p class="hw-lic">${esc(lic)}</p>` : ""}
    </li>`;
  }
  function tierBadge(r) {
    if (r.fallback) return `<span class="hw-badge none">No recommendation</span>`;
    if (r.status === "planned") return `<span class="hw-badge planned">Planned</span>`;
    return r.tested ? `<span class="hw-badge tested">Tested · measured on Spark</span>` : `<span class="hw-badge untested">Untested · estimate</span>`;
  }

  function render(d) {
    st.data = d;
    const r = d.recommendation;
    const hw = d.hardware;
    const autoShort = (d.tiers.find((t) => t.id === d.auto_tier) || {}).short || d.auto_tier;
    $("hwFound").innerHTML = `<strong>${hw.simulated ? "Simulated" : hw.studio ? "Studio" : "Found"}:</strong> ${esc(d.summary)}` +
      (hw.simulated ? `<span class="hw-sim">Preview: ${esc(hw.simulation_label)}</span>` : "");
    const sel = st.tier || (d.tier_source === "setting" ? r.tier : "auto");
    $("hwTier").innerHTML = `<option value="auto">Best match: ${esc(autoShort)}</option>` +
      d.tiers.map((t) => `<option value="${esc(t.id)}">${esc(t.label)}${t.fallback ? "" : t.tested ? " · tested" : t.status === "planned" ? " · planned" : " · untested"}</option>`).join("");
    $("hwTier").value = sel;
    const n = hw.machines || 1;
    $("hwMachines").innerHTML = [1, 2, 3, 4].map((k) => `<option value="${k}">${k === 1 ? "1 computer" : `${k} computers`}</option>`).join("");
    $("hwMachines").value = String(Math.min(n, 4));
    const locked = hw.machines_source === "OPENSOUL_MACHINES" || hw.simulated;
    $("hwMachines").disabled = locked;
    $("hwMachinesNote").textContent = hw.machines_source === "OPENSOUL_MACHINES" ? "Set by OPENSOUL_MACHINES"
      : hw.simulated ? "Set by the preview" : "You set this; OpenSoul never searches the network";
    $("hwSimWrap").hidden = !d.dry_run || !d.simulations.length;
    $("hwSim").innerHTML = `<option value="">This computer (detected)</option>` +
      d.simulations.concat(d.advisory_simulations || []).map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");
    $("hwLic").value = st.commercial;
    $("hwSim").value = st.sim;

    const multi = (r.machines || []).length > 1;
    const head = r.fallback && d.advisory ? "" // the advisory tier carries its own title and badge
      : r.fallback
      ? `<div class="hw-tier"><div class="hw-tier-title"><h3>${esc(r.label)}</h3>${tierBadge(r)}</div></div>`
      : `<div class="hw-tier">
        <div class="hw-tier-title"><h3>${esc(r.label)}</h3>${tierBadge(r)}</div>
        ${r.planned_reason ? `<p class="hw-planned">${esc(r.planned_reason)}</p>` : ""}
        <p>${esc(r.summary)}</p>
        ${r.note ? `<p class="hw-note">${esc(r.note)}</p>` : ""}
        ${r.launch_flags ? `<p class="hw-note">${esc(r.launch_flags)}</p>` : ""}
      </div>`;
    const body = r.fallback && d.advisory
      ? advisoryBody(d.advisory)
      : r.fallback
      ? `<div class="hw-empty"><h4>No models recommended for this computer</h4>
          <p>${esc(r.summary)}</p>${r.note ? `<p>${esc(r.note)}</p>` : ""}</div>`
      : `<ol class="hw-grid">${r.cards.map((c) => card(c, multi)).join("")}</ol>`;
    $("hwBody").innerHTML = head + body;
    const vo = r.voice_options || [];
    $("hwVoices").hidden = !vo.length;
    $("hwVoList").innerHTML = vo.map(voiceItem).join("");
    $("hwNot").innerHTML = r.not_recommended.map((m) =>
      `<li><strong>${esc(m.label)}</strong> · ${esc(m.license)}<br><span>${esc(m.reason)}</span></li>`).join("");
  }

  async function load() {
    const u = new URL("/api/hardware/recommend", location.origin);
    if (st.sim) u.searchParams.set("simulate", st.sim);
    if (st.tier && st.tier !== "auto") u.searchParams.set("tier", st.tier);
    if (st.commercial && st.commercial !== "any") u.searchParams.set("commercial", st.commercial);
    try {
      const r = await fetch(u, { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      render(d);
    } catch (e) {
      $("hwFound").innerHTML = `<span class="hw-error">Couldn’t check this computer: ${esc(e.message)}</span>`;
    }
  }
  async function save(body) {
    try {
      const r = await fetch("/api/hardware/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    } catch (e) {
      $("hwFound").innerHTML = `<span class="hw-error">Couldn’t save: ${esc(e.message)}</span>`;
    }
  }
  $("hwTier").addEventListener("change", async (e) => {
    st.tier = e.target.value === "auto" ? "" : e.target.value;
    if (!st.sim) await save({ tier_override: st.tier || null });
    setUrl(); load();
  });
  $("hwMachines").addEventListener("change", async (e) => { await save({ machines: Number(e.target.value) }); load(); });
  $("hwSim").addEventListener("change", (e) => { st.sim = e.target.value; st.tier = ""; setUrl(); load(); });
  $("hwLic").addEventListener("change", (e) => { st.commercial = e.target.value; setUrl(); load(); });

  function setUrl() {
    const url = new URL(location.href);
    if (!view.hidden) url.searchParams.set("settings", "1"); else url.searchParams.delete("settings");
    st.sim ? url.searchParams.set("simulate", st.sim) : url.searchParams.delete("simulate");
    st.tier ? url.searchParams.set("tier", st.tier) : url.searchParams.delete("tier");
    st.commercial && st.commercial !== "any" ? url.searchParams.set("commercial", st.commercial) : url.searchParams.delete("commercial");
    history.replaceState(null, "", url);
  }
  function open() {
    if (document.body.classList.contains("music-on")) { const mb = $("ufMusicBtn"); document.body.classList.remove("music-on"); const mv = $("musicView"); if (mv) mv.hidden = true; if (mb) { mb.classList.remove("active"); mb.removeAttribute("aria-current"); } }
    if (window.OpenSoulModels) window.OpenSoulModels.close();  // the Models tab gives way to Settings
    document.body.classList.add("settings-on");
    view.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    btn.setAttribute("aria-current", "page");
    seenIntro();
    setUrl();
    window.scrollTo({ top: 0 });
    load();
  }
  function close() {
    if (view.hidden) return;
    document.body.classList.remove("settings-on");
    view.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    btn.removeAttribute("aria-current");
    setUrl();
  }
  btn.addEventListener("click", () => (view.hidden ? open() : close()));
  document.querySelectorAll("#ufTabs button, .view-switch .vs-btn, .step-chip").forEach((b) => b.addEventListener("click", close));
  window.OpenSoulSettings = { open, close, reload: load, setSim: (id) => { st.sim = id || ""; st.tier = ""; } }; // setSim: the Models screen's Preview as

  // First run: one quiet line under the top bar with what was found, until it is opened or dismissed.
  function seenIntro() { try { localStorage.setItem(INTRO_KEY, "1"); } catch { /* private mode */ } if (intro) intro.hidden = true; }
  async function firstRun() {
    let seen = false;
    try { seen = localStorage.getItem(INTRO_KEY) === "1"; } catch { /* private mode */ }
    if (!intro || seen || qs.get("settings")) return;
    try {
      const u = new URL("/api/hardware/detect", location.origin);
      if (st.sim) u.searchParams.set("simulate", st.sim);
      const d = await (await fetch(u, { cache: "no-store" })).json();
      intro.innerHTML = `<p><strong>${d.hardware && d.hardware.studio ? "Configured for your studio." : "Configured for this computer."}</strong> ${esc(d.summary)}.</p>
        <button class="btn btn-outline btn-sm" type="button" id="hwIntroOpen">See recommended models</button>
        <button class="sb-close" type="button" id="hwIntroX" aria-label="Dismiss">&times;</button>`;
      intro.hidden = false;
      $("hwIntroOpen").addEventListener("click", open);
      $("hwIntroX").addEventListener("click", seenIntro);
    } catch { /* the note is optional */ }
  }
  if (qs.get("settings")) open(); else firstRun();
})();
