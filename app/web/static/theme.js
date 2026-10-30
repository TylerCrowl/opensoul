/* Light / dark / system theme. The choice is saved in localStorage ("opensoul.theme": "light" | "dark"; no key =
   System default) and applied before first paint by the small script in index.html's <head>; this file adds the
   Appearance card to Settings, keeps open tabs in sync and follows the system when the choice is System default. */
(() => {
  const KEY = "opensoul.theme";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const CHOICES = [["system", "System default"], ["light", "Light"], ["dark", "Dark"]];

  function get() {
    try { const t = localStorage.getItem(KEY); return t === "light" || t === "dark" ? t : "system"; } catch { return "system"; }
  }
  function apply(t) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
  }
  function shown() {
    const t = get();
    return t === "system" ? (media && media.matches ? "dark" : "light") : t;
  }
  function set(t) {
    try { if (t === "light" || t === "dark") localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch { /* private mode */ }
    apply(t);
    sync();
  }

  const slot = document.getElementById("settingsExtra");
  if (slot) {
    slot.innerHTML = `<section class="hw-card th-card" aria-labelledby="thH">
        <h2 id="thH">Appearance</h2>
        <fieldset class="th-seg">
          <legend class="visually-hidden">Theme</legend>
          ${CHOICES.map(([v, label]) => `<label class="th-opt"><input type="radio" name="osTheme" value="${v}"><span>${label}</span></label>`).join("")}
        </fieldset>
        <p class="th-note" id="thNote" aria-live="polite"></p>
      </section>`;
    slot.querySelectorAll('input[name="osTheme"]').forEach((r) => r.addEventListener("change", (e) => set(e.target.value)));
  }
  function sync() {
    const t = get();
    document.querySelectorAll('input[name="osTheme"]').forEach((r) => { r.checked = r.value === t; });
    const note = document.getElementById("thNote");
    if (note) {
      note.textContent = t === "system"
        ? `Follows your computer’s setting. Showing ${shown()} now.`
        : `Always ${t}. Saved on this browser.`;
    }
  }
  if (media && media.addEventListener) media.addEventListener("change", sync);
  window.addEventListener("storage", (e) => { if (e.key === KEY) { apply(get()); sync(); } });
  apply(get());
  sync();
  window.OpenSoulTheme = { get, set, shown };
})();
