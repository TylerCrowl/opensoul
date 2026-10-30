/* Corner chip in the main app when started from the desktop launcher: shows Preview / Studio, links to the
   welcome page to change it, and offers Quit (POST /api/launcher/quit). Hidden for dev servers. */
(function () {
  "use strict";
  fetch("/api/launcher/status").then(function (r) { return r.json(); }).then(function (s) {
    // OS-005: the hero line follows the mode, also for dev servers.
    if (s && s.mode === "studio") {
      document.querySelectorAll(".hero-qual").forEach(function (p) {
        p.textContent = "Studio connected. OpenSoul renders on your studio.";
        p.classList.add("hero-qual-studio");
      });
    }
    if (!s || !s.launched) return;
    var chip = document.createElement("div");
    chip.className = "ls-chip";
    chip.id = "lsChip";
    chip.setAttribute("role", "region");
    chip.setAttribute("aria-label", "OpenSoul app");
    var studio = s.mode === "studio";
    var label = document.createElement("span");
    label.className = "ls-mode " + (studio ? "ls-studio" : "ls-preview");
    label.textContent = studio ? "Studio connected" : "Preview mode";
    label.title = studio ? s.studio_url : "Sample results, no graphics card needed";
    var change = document.createElement("a");
    change.href = "/welcome#choose"; change.textContent = "Change";
    var quit = document.createElement("button");
    quit.type = "button"; quit.textContent = "Quit";
    quit.onclick = function () {
      if (!confirm("Quit OpenSoul? Your work is saved.")) return;
      fetch("/api/launcher/quit", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
        .then(function () { document.body.innerHTML = '<p class="ls-bye">OpenSoul has closed. You can close this tab.</p>'; });
    };
    chip.append(label, change, quit);
    // P2-14: when the server stops, the chip says so instead of still showing the mode.
    var offline = function () {
      label.className = "ls-mode ls-offline"; label.textContent = "Offline: OpenSoul has stopped";
      label.title = "Open OpenSoul again from Applications or the Start menu.";
      change.hidden = true; quit.hidden = true;
    };
    document.addEventListener("os:offline", offline);
    var timer = setInterval(function () {
      fetch("/api/launcher/status", { cache: "no-store" }).catch(function () { offline(); clearInterval(timer); });
    }, 15000);
    document.body.appendChild(chip);
    document.body.classList.add("ls-has-chip");  // page padding so the chip never covers the last buttons (P1-05)
  }).catch(function () {});
})();
