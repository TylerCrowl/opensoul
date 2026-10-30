/* Models screen: one card per model slot (image, edit, video, lipsync, music, voice, upscale) with the active model and
   the alternatives: licence and commercial-use badge, memory need and whether it fits this computer (or, in preview
   mode, the computer chosen in "Preview as", shared with the picker through ?simulate=), download size, installed or
   in-app, platforms. Data: GET /api/hardware/models. "Plan install / swap" asks POST /api/setup/plan for a dry-run plan
   and shows it. This page never approves anything: it shows the exact command the user runs in a terminal
   (python -m opensoul.setup_engine approve <plan_id>), and agents can't run that step.
   It lives in Settings (Settings -> Models), so the top bar keeps a clean six-step timeline. ?models=1 or ?tab=models
   open it; while it is open the Settings button shows as current, and "Settings" at the top goes back. */
(() => {
  const $ = (id) => document.getElementById(id);
  const view = $("modelsView");
  const settings = $("settingsView");
  const btn = $("settingsLink");

  if (!view || !settings || !btn) return;
  const qs = new URLSearchParams(location.search);
  const st = { sim: qs.get("simulate") || "", commercial: qs.get("commercial") || "any", data: null, plan: null };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const gb = (n) => (n == null ? "" : `${Number(n) % 1 ? Number(n).toFixed(1) : n} GB`);
  const PLAT = { nvidia: "NVIDIA", apple: "Apple Silicon", cpu: "CPU" };

  // Settings -> Models: one row above the picker (the picker itself is unchanged).
  const pick = settings.querySelector('[aria-labelledby="hwPickH"]');
  const entry = document.createElement("p");
  entry.className = "md-entry";
  entry.innerHTML = `<strong>Models</strong> The model for each step, its license and an install plan to read before you install.
    <button class="btn btn-outline btn-sm" type="button" id="hwModelsOpen">Open Models</button>`;
  if (pick) pick.before(entry); else settings.append(entry);

  view.innerHTML = `
    <header class="hw-head md-head">
      <p class="md-crumb"><button class="btn-link" type="button" id="mdToSettings">Settings</button> <span aria-hidden="true">›</span> Models</p>
      <h1 id="mdH">Models</h1>
      <p>One model per step. The active model comes first, then the alternatives. A plan is a dry run: it does not download or change anything here.</p>
      <p class="md-preview-note" id="mdPreviewNote" hidden>Preview mode needs no models. You need them only for a studio.</p>
    </header>
    <section class="hw-card md-bar">
      <p class="hw-found" id="mdFound" role="status">Checking this computer…</p>
      <div class="hw-controls">
        <label for="mdCommercial">Commercial use only
          <select id="mdCommercial">
            <option value="any">Off: every allowed license</option>
            <option value="allowed">On: commercial use allowed, conditions OK</option>
            <option value="open_only">On: commercial use with no conditions</option>
          </select>
          <small>LTX, LatentSync and Orpheus allow commercial use with conditions</small>
        </label>
        <label for="mdSim" id="mdSimWrap" hidden>Preview as
          <select id="mdSim"></select>
          <small>Fit badges for this computer · preview mode only</small>
        </label>
      </div>
      <p class="md-filtered" id="mdFiltered" role="status" hidden></p>
    </section>
    <div id="mdSlots" aria-live="polite"></div>
    <dialog class="md-plan" id="mdPlan" aria-labelledby="mdPlanH">
      <form method="dialog" class="credits-x"><button class="sb-close" type="submit" aria-label="Close">&times;</button></form>
      <div id="mdPlanBody"></div>
    </dialog>`;

  function commercialBadge(o) {
    if (o.commercial_use === "yes") return `<span class="hw-badge tested">Commercial use</span>`;
    if (o.commercial_use === "conditional") return `<span class="hw-badge restricted" title="${esc(o.license_note || o.license_class_label)}">Commercial use · conditions</span>`;
    return `<span class="hw-badge none">No commercial use</span>`;
  }
  function fitBadge(f) {
    const cls = { fits: "tested", tight: "untested", too_big: "md-bad", wrong_platform: "none", unknown: "none" }[f.status] || "none";
    const t = f.need_gb != null && f.budget_gb != null ? `needs ${gb(f.need_gb)} (${f.need_kind}); ${gb(f.budget_gb)} ${f.budget_kind}` : "";
    return `<span class="hw-badge ${cls}" title="${esc(t)}">${esc(f.label)}</span>`;
  }
  function installState(o) {
    if (!o.in_app) return `<span class="hw-badge none">Not in the app yet</span>`;
    const studio = o.installed_where === "studio";
    if (o.installed === true) return `<span class="hw-badge tested">${studio ? "On your studio" : "Installed"}</span>`;
    if (o.installed === false) return `<span class="hw-badge app">${studio ? "In the app · not on your studio" : "In the app · not downloaded"}</span>`;
    return `<span class="hw-badge app">In the app</span>`;
  }
  function memory(o) {
    const f = o.fit || {};
    if (f.need_gb == null) return "not known";
    return `${f.need_kind === "measured" ? "" : "about "}${gb(f.need_gb)} <span class="hw-mem-k">${esc(f.need_kind)}</span>`;
  }
  function option(s, o) {
    const plat = (o.platforms || []).map((p) => PLAT[p] || p).join(", ") || "not stated";
    const swap = !o.is_active;
    const action = o.in_app
      ? `<button class="btn btn-outline btn-sm md-planbtn" type="button" data-slot="${esc(s.id)}" data-model="${esc(o.id)}" data-swap="${swap ? 1 : ""}">Plan install / swap</button>`
      : `<button class="btn btn-outline btn-sm" type="button" disabled title="${esc(o.in_app_note)}">Plan install / swap</button>
         <small class="md-why">OpenSoul can’t install it yet</small>`;
    return `<li class="hw-stage md-opt${o.is_active ? " md-active" : ""}" data-model="${esc(o.id)}">
      <p class="hw-stage-name"><span>${o.is_active ? "Active" : "Alternative"}${o.is_default ? " · app default" : ""}</span><span>${esc(o.runtime === "comfyui" ? "" : o.runtime)}</span></p>
      <h3>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.label)}</a>` : esc(o.label)}</h3>
      <p class="hw-badges">${commercialBadge(o)}${fitBadge(o.fit)}${installState(o)}</p>
      <dl class="hw-facts">
        <dt>License</dt><dd>${esc(o.license)}${o.license_verified ? "" : " <span class=\"hw-mem-k\">not verified</span>"}</dd>
        <dt>Memory</dt><dd title="${esc((o.memory && o.memory.basis) || "")}">${memory(o)}</dd>
        <dt>Download</dt><dd>${o.weights_gb ? gb(o.weights_gb) : o.bundled_with && o.bundled_with.length ? `with ${esc(o.bundled_with.join(", "))}` : o.weights_gb === 0 ? "none" : "not checked"}</dd>
        <dt>Platforms</dt><dd>${esc(plat)}</dd>
      </dl>
      ${!o.in_app && o.in_app_note ? `<p class="hw-lic">${esc(o.in_app_note)}</p>` : ""}
      <div class="md-act">${action}</div>
    </li>`;
  }
  function slotCard(s) {
    const hidden = s.hidden_count ? `<p class="hw-lic">${s.hidden_count} hidden by the commercial-use filter.</p>` : "";
    return `<section class="hw-card md-slot" data-slot="${esc(s.id)}" aria-labelledby="mdS_${esc(s.id)}">
      <div class="md-slot-h"><h2 id="mdS_${esc(s.id)}">${esc(s.label)}</h2>
        <span class="hw-badge ${s.active_source === "saved" ? "rec" : "app"}">${s.active_source === "saved" ? "Swapped by you" : "App default"}</span></div>
      ${s.plain ? `<p class="md-plain">${esc(s.plain)}</p>` : ""}${hidden}
      ${s.options.length ? `<ol class="hw-grid">${s.options.map((o) => option(s, o)).join("")}</ol>`
        : `<p class="hw-empty">No model for this step matches the filter.</p>`}
    </section>`;
  }
  function render(d) {
    st.data = d;
    const hw = d.hardware;
    $("mdFound").innerHTML = `<strong>${hw.simulated ? "Fit badges for" : hw.studio ? "Fit badges for your studio" : "Fit badges for this computer"}:</strong> ${esc(d.summary)}` +
      (hw.simulated ? `<span class="hw-sim">Preview: ${esc(hw.simulation_label)}</span>` : "");
    $("mdSimWrap").hidden = !d.dry_run || !d.simulations.length;
    $("mdPreviewNote").hidden = !d.dry_run;
    $("mdSim").innerHTML = `<option value="">This computer (detected)</option>` +
      d.simulations.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");
    $("mdSim").value = st.sim;
    $("mdCommercial").value = st.commercial;
    const hid = d.slots.filter((s) => s.hidden_count);
    $("mdFiltered").hidden = st.commercial === "any";
    $("mdFiltered").innerHTML = hid.length
      ? `<strong>Commercial use only is on:</strong> ${hid.reduce((n, s) => n + s.hidden_count, 0)} models hidden (${hid.map((s) => `${s.hidden_count} ${esc(s.label.toLowerCase())}`).join(", ")}).`
      : `<strong>Commercial use only is on:</strong> every model listed allows commercial use, so the filter hides no models.`;
    $("mdSlots").innerHTML = d.slots.map(slotCard).join("");
  }
  async function load() {
    const u = new URL("/api/hardware/models", location.origin);
    if (st.sim) u.searchParams.set("simulate", st.sim);
    if (st.commercial !== "any") u.searchParams.set("commercial", st.commercial);
    try {
      const r = await fetch(u, { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      render(d);
    } catch (e) {
      $("mdFound").innerHTML = `<span class="hw-error">Couldn’t load the models: ${esc(e.message)}</span>`;
    }
  }

  // ---------------------------------------------------------------- dry-run plan (no approval here)
  function planHtml(p, label) {
    const items = p.items || [];
    const dl = items.map((i) => `<li><strong>${esc(i.label)}</strong> · ${i.installed ? "already installed" : `up to ${gb(i.download_gb)}`}
        ${i.gated ? ` · <span class="hw-badge untested">gated download</span>` : ""}
        ${(i.commands || []).map((c) => `<code class="md-code">${esc(c.argv.join(" "))}</code>`).join("")}
        ${(i.manual_steps || []).map((m) => `<p class="hw-lic">First: ${esc(m)}</p>`).join("")}</li>`).join("");
    const acks = (p.license_acks_needed || []).map((m) => {
      const i = items.find((x) => x.model === m) || {};
      return `<li><strong>${esc(i.label || m)}</strong> · ${esc(i.license || "")}</li>`;
    }).join("");
    const changes = (p.slot_changes || []).map((c) => `<li><strong>${esc(c.slot)}</strong>: ${esc(c.from || "none")} → ${esc(c.to)}</li>`).join("");
    const disk = p.free_disk_gb == null ? "free disk not known"
      : `${gb(p.download_gb_upper_bound)} needed (upper bound) · ${gb(p.free_disk_gb)} free`;
    const diskBadge = p.disk_fits == null ? "" : p.disk_fits ? `<span class="hw-badge tested">Fits on disk</span>` : `<span class="hw-badge md-bad">Not enough disk</span>`;
    const errors = (p.errors || []).length ? `<div class="md-errors"><h3>Can’t plan this</h3><ul>${p.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : "";
    const approve = p.ok && p.approve_command ? `
      <div class="md-approve">
        <h3>Approve it yourself</h3>
        <p>Only you can approve a plan. Open Terminal on this computer. Paste this command and press Return.
          Agents can't approve: there is no approve button, route or MCP tool.</p>
        <div class="md-cmd"><code id="mdCmd">${esc(p.approve_command)}</code>
          <button class="btn btn-outline btn-sm" type="button" id="mdCopy">Copy</button></div>
        <p class="hw-lic" id="mdCopied" role="status">${acks ? "--accept-licenses means you accept the licenses listed above. " : ""}It prints a one-time token that works for 30 minutes. Applying needs that token and an explicit approve flag.</p>
      </div>` : "";
    return `<h2 id="mdPlanH">Dry-run plan · ${esc(label)}</h2>
      <p class="md-planid">${p.ok ? `Plan <code>${esc(p.plan_id)}</code> · ${p.kind === "install" ? "install" : "slot change only"}` : "No plan saved"}</p>
      ${errors}
      ${items.length ? `<h3>Downloads</h3><ul class="md-list">${dl}</ul>` : ""}
      <h3>Disk</h3><p class="md-row">${esc(disk)} ${diskBadge}</p>
      <h3>Licenses to accept</h3>${acks ? `<ul class="md-list">${acks}</ul>` : `<p class="md-row">None: open licenses only.</p>`}
      <h3>Slot changes</h3>${changes ? `<ul class="md-list">${changes}</ul>` : `<p class="md-row">None: the active model stays.</p>`}
      ${approve}
      <p class="credits-foot">${esc(p.note || "")}</p>`;
  }
  async function plan(b) {
    const body = { models: [b.dataset.model], slot_changes: b.dataset.swap ? { [b.dataset.slot]: b.dataset.model } : {}, commercial: st.commercial };
    const label = b.closest(".md-opt").querySelector("h4").textContent.trim();
    b.disabled = true;
    try {
      const r = await fetch("/api/setup/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const p = await r.json();
      if (!r.ok) throw new Error(p.detail || r.statusText);
      st.plan = p;
      $("mdPlanBody").innerHTML = planHtml(p, label);
    } catch (e) {
      $("mdPlanBody").innerHTML = `<h2 id="mdPlanH">Dry-run plan · ${esc(label)}</h2><p class="hw-error">Couldn’t make a plan: ${esc(e.message)}</p>`;
    } finally {
      b.disabled = false;
    }
    const dlg = $("mdPlan");
    if (!dlg.open) dlg.showModal();
    const copy = $("mdCopy");
    if (copy) copy.addEventListener("click", async () => {
      const text = $("mdCmd").textContent;
      try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; }
      catch { const sel = getSelection(); const rg = document.createRange(); rg.selectNodeContents($("mdCmd")); sel.removeAllRanges(); sel.addRange(rg); copy.textContent = "Selected: press Ctrl+C"; }
    });
  }
  $("mdSlots").addEventListener("click", (e) => { const b = e.target.closest(".md-planbtn"); if (b) plan(b); });
  $("mdCommercial").addEventListener("change", (e) => { st.commercial = e.target.value; setUrl(); load(); });
  $("mdSim").addEventListener("change", (e) => {
    st.sim = e.target.value; setUrl(); load();
    if (window.OpenSoulSettings && window.OpenSoulSettings.setSim) window.OpenSoulSettings.setSim(st.sim);
  });

  // ---------------------------------------------------------------- open / close (a full-page view, part of Settings)
  function setUrl() {
    const url = new URL(location.href);
    if (!view.hidden) { url.searchParams.set("models", "1"); url.searchParams.delete("settings"); } else url.searchParams.delete("models");
    if (url.searchParams.get("tab") === "models") url.searchParams.delete("tab"); // ?tab=models is an alias: ?models=1 is the address
    st.sim ? url.searchParams.set("simulate", st.sim) : url.searchParams.delete("simulate");
    st.commercial !== "any" ? url.searchParams.set("commercial", st.commercial) : url.searchParams.delete("commercial");
    history.replaceState(null, "", url);
  }
  const flowTabs = () => document.querySelectorAll("#ufTabs [data-tab]");
  function open() {
    const cur = new URLSearchParams(location.search); // follow the picker's Preview as and licence choice
    st.sim = cur.get("simulate") || ""; st.commercial = cur.get("commercial") || st.commercial;
    if (window.OpenSoulSettings) window.OpenSoulSettings.close();
    if (document.body.classList.contains("music-on")) { // leave Music the way Settings does
      const mb = $("ufMusicBtn"), mv = $("musicView");
      document.body.classList.remove("music-on");
      if (mv) mv.hidden = true;
      if (mb) { mb.classList.remove("active"); mb.removeAttribute("aria-current"); }
      const u = new URL(location.href); u.searchParams.delete("music"); history.replaceState(null, "", u);
    }
    view.hidden = false;
    document.body.classList.add("models-on");
    flowTabs().forEach((b) => { b.classList.remove("active"); b.removeAttribute("aria-current"); });
    btn.setAttribute("aria-current", "page");  // Models is part of Settings
    setUrl();
    window.scrollTo({ top: 0 });
    load();
  }
  // restore: give the step tab you were on its active look back (not when another tab or Music takes over).
  function close({ restore = true } = {}) {
    if (view.hidden) return;
    view.hidden = true;
    document.body.classList.remove("models-on");
    if (settings.hidden) btn.removeAttribute("aria-current");
    const u = window.OpenSoulUnified;
    if (restore && u && u.state && u.state.tab) {
      flowTabs().forEach((b) => { const on = b.dataset.tab === u.state.tab; b.classList.toggle("active", on); if (on) b.setAttribute("aria-current", "page"); });
    }
    setUrl();
  }
  $("hwModelsOpen").addEventListener("click", open);
  $("mdToSettings").addEventListener("click", () => { if (window.OpenSoulSettings) window.OpenSoulSettings.open(); });
  if ($("ufMusicBtn")) $("ufMusicBtn").addEventListener("click", () => close({ restore: false }));
  document.querySelectorAll("#ufTabs [data-tab], .view-switch .vs-btn, .step-chip").forEach((b) => b.addEventListener("click", () => close({ restore: false })));
  // Settings closes this view itself (hardware.js open() calls OpenSoulModels.close()).
  window.OpenSoulModels = { open, close, reload: load };
  // Deep links: ?models=1 (the old Settings -> Models address, with or without settings=1) and ?tab=models open the tab.
  if (qs.get("models") === "1" || qs.get("tab") === "models") setTimeout(open, 0);
})();
