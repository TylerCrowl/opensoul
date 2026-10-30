/* Camera / effect tiles shared by Create (step 2) and the Storyboard shot sheet (unify step 7).
 * One look, one rule set: "Experimental" tag from the preset's `experimental` flag, the rendered example clip
 * when it exists, a quiet placeholder otherwise. Rendering only; each caller keeps its own state. */
(function () {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const label = (p) => (p.id === "static" ? "None / static" : p.label);

  /** Small "Experimental" tag: the move doesn't work reliably yet on the default model (see presets/README.md). */
  function tag(p) {
    return p && p.experimental
      ? `<span class="os-exp" title="Experimental: this move is not reliable yet on the default model">Experimental</span>` : "";
  }

  /** Motion glyphs: one small line icon per move (24-unit grid, drawn with currentColor). Presets name theirs in
   *  `glyph`; tests/test_tile_glyphs.py checks every preset has a preview clip or a glyph listed here. */
  const GLYPHS = {
    still: '<path d="M8 4h8v5H8z"/><path d="M12 9l-5 11M12 9l5 11M12 9v11"/>',
    in_soft: '<rect x="4" y="6" width="16" height="12" rx="2"/><rect x="9" y="9.5" width="6" height="5" rx="1"/>',
    in: '<path d="M4 9h5V4M15 4v5h5M20 15h-5v5M9 20v-5H4"/>',
    out: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    crash: '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M13 6.5l-4 6h5l-4 5"/>',
    left: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    right: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    orbit: '<path d="M7 16.2C4.6 15.3 3 13.8 3 12c0-2.8 4-5 9-5s9 2.2 9 5c0 2.4-3 4.4-7.2 4.9"/><path d="M11.5 14.5l2.5 2.4-2.5 2.4"/><circle cx="12" cy="12" r="1.6"/>',
    vertigo: '<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="9" y="9.5" width="6" height="5" rx="1"/><path d="M3.8 5.8L9 9.5M20.2 5.8L15 9.5M20.2 18.2L15 14.5M3.8 18.2L9 14.5"/>',
    fpv: '<path d="M4 19c3 0 4-5 7-8s5-4 8-4"/><path d="M15 4l4 3-3 4"/>',
    day_night: '<circle cx="12" cy="12" r="4.5"/><path d="M12 7.5a4.5 4.5 0 0 1 0 9z" fill="currentColor"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2"/>',
    globe_out: '<circle cx="12" cy="12" r="3.6"/><path d="M8.4 12h7.2M12 8.4c-1.4 2.2-1.4 5 0 7.2"/><path d="M3 7V3h4M17 3h4v4M21 17v4h-4M7 21H3v-4"/>',
    orbit_freeze: '<path d="M7 16.2C4.6 15.3 3 13.8 3 12c0-2.8 4-5 9-5s9 2.2 9 5c0 2.4-3 4.4-7.2 4.9"/><path d="M11.5 14.5l2.5 2.4-2.5 2.4"/><path d="M10.6 10.2v3.6M13.4 10.2v3.6"/>',
    outfit: '<path d="M12 8.5V7.6a2 2 0 1 0-2-2"/><path d="M12 8.5L3.5 15.5a1 1 0 0 0 .6 1.8h15.8a1 1 0 0 0 .6-1.8z"/>',
  };
  const glyphId = (p) => (p && (p.glyph || (GLYPHS[p.id] ? p.id : null))) || null;
  /** The move's glyph: a small corner badge over a preview clip, or `big` in the middle of the fallback card. */
  function glyph(p, big = false) {
    const g = GLYPHS[glyphId(p)];
    return g ? `<span class="os-glyph${big ? " big" : ""}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${g}</svg></span>` : "";
  }
  /** No preview clip (or it failed to load): a silhouette in a soft frame with the move's glyph. Never a blank card. */
  function fallback(p) {
    // A passed still (presets/demo_images.json tile_still) under the glyph when there is one, else a silhouette.
    if (p && p.tile_still) return `<span class="os-ph still" aria-hidden="true"><img src="${esc(p.tile_still)}" alt="" loading="lazy" />${glyph(p, true)}</span>`;
    return `<span class="os-ph" aria-hidden="true"><svg class="os-subj" viewBox="0 0 40 72"><use href="#i-subject"/></svg>${glyph(p, true)}</span>`;
  }
  /** Tile media: the example clip with the glyph in the corner, or the fallback card. */
  function media(p, on) {
    return p.thumb_ready && p.thumbnail
      ? `<video src="${esc(p.thumbnail)}" muted loop playsinline preload="metadata" ${on ? "autoplay" : ""}></video>${glyph(p)}`
      : fallback(p);
  }
  function onBadClip(t, id, list) {
    const v = t.querySelector("video"); if (!v) return;
    v.addEventListener("error", () => {
      const p = (list || []).find((x) => x.id === id) || { id };
      const g = t.querySelector(".os-frame > .os-glyph"); if (g) g.remove();
      v.insertAdjacentHTML("afterend", fallback(p)); v.remove();
    }, { once: true });
  }

  /** Compact tile row (shot sheet). Example clips play on hover and when picked; others show their first frame. */
  function html(list, { kind = "camera", selected = "static", name = "Camera" } = {}) {
    const cams = [...list].sort((a, b) => (a.id === "static" ? -1 : b.id === "static" ? 1 : 0));
    return `<div class="os-tiles" role="radiogroup" aria-label="${esc(name)}">${cams.map((p) => {
      const on = p.id === (selected || "static");
      return `<button type="button" class="os-tile" role="radio" aria-checked="${on}" tabindex="${on ? 0 : -1}" data-kind="${esc(kind)}" data-id="${esc(p.id)}" title="${esc(p.blurb || "")}">
        <span class="os-frame">${media(p, on)}${tag(p)}</span><span class="os-name">${esc(label(p))}</span></button>`;
    }).join("")}</div>`;
  }

  /** Click, arrow keys and hover preview. onPick(id) is called once per change. */
  function wire(root, onPick, list) {
    const group = root && root.querySelector(".os-tiles");
    if (!group) return;
    const tiles = [...group.querySelectorAll(".os-tile")];
    const pick = (t) => {
      if (t.getAttribute("aria-checked") === "true") return;
      tiles.forEach((x) => { const on = x === t; x.setAttribute("aria-checked", String(on)); x.tabIndex = on ? 0 : -1;
        const v = x.querySelector("video"); if (v) { if (on) v.play().catch(() => {}); else { v.pause(); v.currentTime = 0; } } });
      onPick(t.dataset.id);
    };
    tiles.forEach((t, i) => {
      t.addEventListener("click", () => pick(t));
      t.addEventListener("keydown", (e) => {
        const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
        if (!d) return;
        e.preventDefault();
        const n = tiles[(i + d + tiles.length) % tiles.length]; n.focus(); pick(n);
      });
      const v = t.querySelector("video");
      if (v) {
        t.addEventListener("mouseenter", () => v.play().catch(() => {}));
        t.addEventListener("mouseleave", () => { if (t.getAttribute("aria-checked") !== "true") { v.pause(); v.currentTime = 0; } });
      }
      onBadClip(t, t.dataset.id, list);
    });
  }

  // ---------------------------------------------------------------- stacked moves (up to rules.max_moves, in order)
  const BADGE = ["①", "②", "③", "④"];
  function clash(a, b, rules, list) {
    if (a === b) return null;
    const c = ((rules && rules.conflicts) || []).find((x) => (x.a.includes(a) && x.b.includes(b)) || (x.b.includes(a) && x.a.includes(b)));
    if (!c) return null;
    if (!c.short) return c.why;
    // Name both moves: "Crash zoom clashes with Dolly in: both push in."
    const name = (id) => { const p = (list || []).find((x) => x.id === id); return p ? label(p) : id; };
    return `${name(a)} clashes with ${name(b)}: ${c.short}.`;
  }
  /** Why `id` can't be added to `moves` (plain English), or null. */
  function blockedReason(id, moves, rules, list) {
    const max = (rules && rules.max_moves) || 3;
    const real = moves.filter((m) => m !== "static");
    if (id === "static" || real.includes(id) || !real.length) return null;  // static resets; a picked tile removes itself
    const alone = (rules && rules.alone) || {};
    if (alone[id]) return alone[id];
    const lone = real.find((m) => alone[m]);
    if (lone) return alone[lone];
    for (const m of real) { const w = clash(id, m, rules, list); if (w) return w; }  // the specific reason first
    if (real.length >= max) return maxWhy(rules);
    return null;
  }
  const maxWhy = (rules) => (rules && rules.max_why) || `Up to ${(rules && rules.max_moves) || 3} camera moves per shot. Click a picked move to remove it.`;
  /** Multi-select row: order badges on picked tiles, clashing tiles greyed; the reason shows in the inline hint line on hover/focus/tap (no tooltip, so the two never overlap). */
  function multiHTML(list, { selected = ["static"], rules = null, name = "Camera" } = {}) {
    const moves = selected.length ? selected : ["static"];
    const cams = [...list].sort((a, b) => (a.id === "static" ? -1 : b.id === "static" ? 1 : 0));
    const stacked = moves.filter((m) => m !== "static").length > 1;
    return `<div class="os-tiles multi" role="group" aria-label="${esc(name)}: up to ${(rules && rules.max_moves) || 3}, in order">${cams.map((p) => {
      const at = moves.indexOf(p.id), on = at >= 0;
      const why = on ? null : blockedReason(p.id, moves, rules, list);
      const badge = on && (stacked || p.id !== "static") ? `<span class="os-order" aria-hidden="true">${stacked ? BADGE[at] : "✓"}</span>` : "";
      const full = why && why === maxWhy(rules);
      return `<button type="button" class="os-tile${why ? " blocked" : ""}${full ? " full" : ""}" aria-pressed="${on}" data-id="${esc(p.id)}" ${why ? `aria-disabled="true" data-why="${esc(why)}"` : ""}
        ${why ? "" : `title="${esc(p.blurb || "")}"`}><span class="os-frame">${media(p, on)}${badge}${tag(p)}</span><span class="os-name">${esc(label(p))}</span></button>`;
    }).join("")}</div>`;
  }
  /** Tap to add (in order) or remove; static resets. onChange(newMoves). onHint(reason | null): a greyed tile's
   *  reason while it is hovered, focused or tapped; null when the pointer or focus leaves it. */
  function wireMulti(root, moves, rules, { onChange, onHint, list }) {
    const group = root && root.querySelector(".os-tiles.multi");
    if (!group) return;
    const hint = (why) => onHint && onHint(why || null);
    // Open with the picked moves in view: all of them when they fit, else the newest one.
    const ps = [...group.querySelectorAll('.os-tile[aria-pressed="true"]')].filter((t) => t.dataset.id !== "static");
    if (ps.length) {
      const L = Math.min(...ps.map((t) => t.offsetLeft)) - group.offsetLeft, last = ps.reduce((a, t) => (t.offsetLeft > a.offsetLeft ? t : a));
      const R = last.offsetLeft + last.offsetWidth - group.offsetLeft, W = group.clientWidth;
      group.scrollLeft = R - L <= W - 8 ? Math.max(0, L - 4) : Math.max(0, R - W + 4);
    }
    group.querySelectorAll(".os-tile").forEach((t) => {
      if (t.dataset.why) {
        ["mouseenter", "focus"].forEach((ev) => t.addEventListener(ev, () => hint(t.dataset.why)));
        ["mouseleave", "blur"].forEach((ev) => t.addEventListener(ev, () => hint(null)));
      }
      t.addEventListener("click", () => {
        const id = t.dataset.id;
        const real = moves.filter((m) => m !== "static");
        if (t.dataset.why) return hint(t.dataset.why);  // a tap (touch) shows the reason; nothing is saved
        let next;
        if (id === "static") next = ["static"];
        else if (real.includes(id)) next = real.filter((m) => m !== id);
        else next = [...real, id];
        onChange(next.length ? next : ["static"]);
      });
      const v = t.querySelector("video");
      if (v) {
        t.addEventListener("mouseenter", () => v.play().catch(() => {}));
        t.addEventListener("mouseleave", () => { if (t.getAttribute("aria-pressed") !== "true") { v.pause(); v.currentTime = 0; } });
      }
      onBadClip(t, t.dataset.id, list);
    });
  }

  window.OpenSoulTiles = { tag, html, wire, label, multiHTML, wireMulti, blockedReason, clash, GLYPHS, glyph, fallback };
})();
