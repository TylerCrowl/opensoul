/* First-run welcome (app/web/welcome.html): Welcome -> Preview or Connect a studio -> Ready.
   Talks to /api/launcher/* (app/launcher_routes.py), same-computer JSON only. No colours here; see launcher.css.
   Studio mode: Continue waits until Test connection has run for the address in the box, so the person sees what was
   found (or why not, or a public-address warning) before moving on. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var mode = "preview", tested = null, testedKey = "";

  function show(n) {
    document.querySelectorAll("[data-panel]").forEach(function (p) {
      var on = p.getAttribute("data-panel") === String(n);
      p.hidden = !on;
      if (on) { p.classList.remove("wl-in"); void p.offsetWidth; p.classList.add("wl-in"); }
    });
    document.querySelectorAll(".wl-steps li").forEach(function (li) {
      var s = +li.getAttribute("data-step");
      li.className = s === n ? "on" : s < n ? "done" : "";
      if (s === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    var h = document.querySelector('[data-panel="' + n + '"] h1');
    if (h) { h.tabIndex = -1; h.focus(); }
  }

  function key() { return $("wlUrl").value.trim() + "|" + $("wlApi").value.trim(); }

  function syncContinue() {
    var btn = $("wlSave");
    if (mode !== "studio") { btn.disabled = false; btn.textContent = "Continue"; btn.className = "wl-primary"; return; }
    var fresh = tested && testedKey === key();
    btn.disabled = !fresh;
    btn.title = fresh ? "" : "Test the connection first";
    var good = fresh && tested.ok && !tested.warning;
    btn.textContent = !fresh || good ? "Continue" : "Continue anyway";
    btn.className = !fresh || good ? "wl-primary" : "wl-secondary";
  }

  function pick(m, focus) {
    mode = m;
    $("wlPreview").setAttribute("aria-checked", String(m === "preview"));
    $("wlStudio").setAttribute("aria-checked", String(m === "studio"));
    $("wlPreview").tabIndex = m === "preview" ? 0 : -1;  // one tab stop for the group (P2-11)
    $("wlStudio").tabIndex = m === "studio" ? 0 : -1;
    $("wlStudioBox").hidden = m !== "studio";
    $("wlErr").textContent = "";
    syncContinue();
    if (m === "studio" && focus) $("wlUrl").focus();
  }

  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || "Something went wrong."); return d; }); });
  }

  var TITLES = {
    ok: "Connected", proxy_missing: "Connected, with one thing missing", nodes_missing: "Connected, but the OpenSoul nodes are missing",
    invalid: "Check the address",
    dns: "Can't find that computer", timeout: "No answer", refused: "Nothing answered on that port",
    unreachable: "Can't reach the studio", wrong_port: "Wrong port?", not_comfy: "That isn't ComfyUI"
  };

  function fact(dl, k, v) {
    if (!v) return;
    var dt = document.createElement("dt"), dd = document.createElement("dd");
    dt.textContent = k; dd.textContent = v; dl.appendChild(dt); dl.appendChild(dd);
  }

  function showResult(d) {
    var box = $("wlResult"), dl = $("wlFacts");
    var state = d.ok ? (d.api_ok && !(d.missing_nodes || []).length ? "ok" : "warn") : "bad";
    box.className = "wl-result " + state; box.hidden = false;
    $("wlResultTitle").textContent = TITLES[d.kind] || (d.ok ? "Connected" : "Couldn't connect");
    $("wlResultText").textContent = d.message || "";
    dl.textContent = "";
    if (d.ok) {
      fact(dl, "ComfyUI", d.comfyui ? "version " + d.comfyui : "found");
      fact(dl, "Graphics", d.gpu);
      fact(dl, "Memory", d.vram_gb ? d.vram_gb + " GB" : "");
      fact(dl, "API helper", d.api_ok ? "answering" : "not answering");
      fact(dl, "OpenSoul nodes", !d.nodes_checked ? "not checked" : (d.missing_nodes || []).length ? (d.missing_nodes.length + " missing") : "all found");
    }
    dl.hidden = !dl.firstChild;
    $("wlWarn").hidden = !d.warning;
    $("wlWarnText").textContent = d.warning || "";
    if (d.ok && d.api_ok && !d.warning && !(d.missing_nodes || []).length) { box.classList.add("wl-pop"); }
  }

  function testStudio() {
    var url = $("wlUrl").value.trim();
    if (!url) { $("wlErr").textContent = "Type your studio's address first."; $("wlUrl").focus(); return Promise.resolve(); }
    $("wlErr").textContent = "";
    var box = $("wlResult");
    box.className = "wl-result busy"; box.hidden = false;
    $("wlResultTitle").textContent = "Checking…"; $("wlResultText").textContent = ""; $("wlFacts").hidden = true;
    $("wlWarn").hidden = true;
    $("wlTest").disabled = true;
    var k = key();
    return post("/api/launcher/test", { url: url, api_url: $("wlApi").value.trim() }).then(function (d) {
      if (d.ok && d.url) $("wlUrl").value = d.url;
      tested = d; testedKey = key();
      if (!d.ok) testedKey = k;
      showResult(d);
      return d;
    }).catch(function (e) {
      tested = { ok: false, message: e.message }; testedKey = k;
      showResult(tested);
    }).finally(function () { $("wlTest").disabled = false; syncContinue(); });
  }

  function save() {
    $("wlErr").textContent = "";
    var studioMode = mode === "studio";
    var body = { mode: mode, studio_url: studioMode ? $("wlUrl").value.trim() : "",
                 studio_api_url: studioMode ? $("wlApi").value.trim() : "" };
    if (studioMode && !body.studio_url) { $("wlErr").textContent = "Type your studio's address first."; return; }
    $("wlSave").disabled = true;
    post("/api/launcher/config", body).then(function (d) {
      var studio = d.mode === "studio", good = studio && tested && tested.ok;
      $("wlDoneTitle").textContent = studio ? (good ? "Your studio is ready" : "Almost there") : "You're all set";
      $("wlDoneText").textContent = studio
        ? "OpenSoul will send its work to your studio at " + d.studio_url + "." +
          (good ? "" : " We could not connect to it. You can test again later from Change in the corner.")
        : "You're in Preview mode: sample results while you learn. Connect a studio any time for real renders.";
      $("wlModels").hidden = !studio;
      document.querySelector('[data-panel="3"]').classList.toggle("wl-celebrate", !studio || !!good);
      show(3);
    }).catch(function (e) { $("wlErr").textContent = e.message; })
      .finally(function () { syncContinue(); });
  }

  $("wlNext1").onclick = function () { show(2); };
  $("wlBack2").onclick = function () { show(1); };
  $("wlBack3").onclick = function () { show(2); };
  $("wlPreview").onclick = function () { pick("preview", true); };
  $("wlStudio").onclick = function () { pick("studio", true); };
  $("wlTest").onclick = testStudio;
  $("wlUrl").addEventListener("keydown", function (e) { if (e.key === "Enter") testStudio(); });
  ["wlUrl", "wlApi"].forEach(function (id) {
    $(id).addEventListener("input", function () { $("wlErr").textContent = ""; syncContinue(); });  // no stale error (P2-01)
  });
  $("wlSave").onclick = save;
  // arrow keys move between the two choices, like any radio group
  $("wlPreview").parentNode.addEventListener("keydown", function (e) {
    if (["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].indexOf(e.key) < 0) return;
    e.preventDefault();
    var next = mode === "preview" ? "studio" : "preview";
    pick(next); $(next === "preview" ? "wlPreview" : "wlStudio").focus();
  });

  fetch("/api/launcher/status").then(function (r) { return r.json(); }).then(function (s) {
    if (s.studio_url) $("wlUrl").value = s.studio_url;
    if (s.studio_api_url) $("wlApi").value = s.studio_api_url;
    pick(s.saved_mode === "studio" ? "studio" : "preview");
    if (location.hash === "#choose") show(2);
  }).catch(function () {});
  fetch("/api/setup/hardware").then(function (r) { return r.json(); }).then(function (h) {
    var gpu = h.hardware && h.hardware.gpu_class && h.hardware.gpu_class !== "none" && h.hardware.platform !== "apple";
    $("wlHw").textContent = "This computer: " + (h.summary || "unknown") + ". " +
      (gpu ? "It can possibly render on its own after you install the models."
           : "Preview mode works here. Real renders need a studio.");
  }).catch(function () { $("wlHw").textContent = ""; });
})();
