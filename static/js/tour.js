/* Guided walkthrough of the dashboard home. No library, CSP-safe.
   Steps = elements with data-tour="n" (+ data-tour-title / data-tour-text), first visible one per n.
   Keyboard: Esc = skip, arrows = previous / next, Tab stays inside the tooltip. */
(function () {
  "use strict";
  var doc = document;
  var root = doc.querySelector("[data-tour-root]");
  if (!root) { return; }
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var label = function (k, d) { return root.getAttribute("data-label-" + k) || d; };
  var state = null;

  function visible(el) {
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  }

  function collect() {
    var byStep = {};
    Array.prototype.forEach.call(doc.querySelectorAll("[data-tour]"), function (el) {
      var n = parseInt(el.getAttribute("data-tour"), 10);
      if (!isNaN(n) && !byStep[n] && visible(el)) { byStep[n] = el; }
    });
    return Object.keys(byStep).map(Number).sort(function (a, b) { return a - b; }).map(function (n) { return byStep[n]; });
  }

  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }

  function build() {
    var backdrop = el("div", "tour-backdrop");
    var spot = el("div", "tour-spot");
    var tip = el("div", "tour-tip");
    tip.setAttribute("role", "dialog");
    tip.setAttribute("aria-modal", "true");
    tip.setAttribute("aria-labelledby", "tour-title");
    tip.setAttribute("aria-describedby", "tour-text");
    var count = el("p", "tour-tip__count");
    var title = el("h2", "tour-tip__title"); title.id = "tour-title";
    var text = el("p", "tour-tip__text"); text.id = "tour-text";
    var actions = el("div", "tour-tip__actions");
    var skip = el("button", "btn btn--link btn--small", label("skip", "Passer")); skip.type = "button";
    var nav = el("div");
    var prev = el("button", "btn btn--ghost btn--small", label("prev", "Retour")); prev.type = "button";
    var next = el("button", "btn btn--primary btn--small", label("next", "Suivant")); next.type = "button";
    nav.appendChild(prev); nav.appendChild(next);
    actions.appendChild(skip); actions.appendChild(nav);
    tip.appendChild(count); tip.appendChild(title); tip.appendChild(text); tip.appendChild(actions);
    doc.body.appendChild(backdrop); doc.body.appendChild(spot); doc.body.appendChild(tip);
    skip.addEventListener("click", function () { finish(); });
    prev.addEventListener("click", function () { go(state.index - 1); });
    next.addEventListener("click", function () { state.index >= state.steps.length - 1 ? finish() : go(state.index + 1); });
    return { backdrop: backdrop, spot: spot, tip: tip, count: count, title: title, text: text, prev: prev, next: next };
  }

  function place() {
    if (!state) { return; }
    var target = state.steps[state.index];
    var r = target.getBoundingClientRect();
    var pad = 6;
    var s = state.ui.spot.style;
    s.top = (r.top - pad) + "px"; s.left = (r.left - pad) + "px";
    s.width = (r.width + 2 * pad) + "px"; s.height = (r.height + 2 * pad) + "px";
    var tip = state.ui.tip;
    if (window.innerWidth < 600) { tip.style.top = ""; tip.style.left = ""; return; } // bottom sheet (CSS)
    var tr = tip.getBoundingClientRect();
    var top = r.bottom + 14;
    if (top + tr.height > window.innerHeight - 12) { top = Math.max(12, r.top - tr.height - 14); }
    var left = Math.min(Math.max(12, r.left), window.innerWidth - tr.width - 12);
    tip.style.top = top + "px"; tip.style.left = left + "px";
  }

  function go(i) {
    if (i < 0 || i >= state.steps.length) { return; }
    state.index = i;
    var target = state.steps[i];
    var ui = state.ui;
    ui.count.textContent = (i + 1) + " " + label("of", "sur") + " " + state.steps.length;
    ui.title.textContent = target.getAttribute("data-tour-title") || "";
    ui.text.textContent = target.getAttribute("data-tour-text") || "";
    ui.prev.hidden = i === 0;
    ui.next.textContent = i === state.steps.length - 1 ? label("done", "Terminer") : label("next", "Suivant");
    // On phones the bottom sheet covers the lower part: keep the target in the upper half.
    var r = target.getBoundingClientRect();
    var top = window.innerWidth < 600
      ? r.top + window.pageYOffset - 72
      : r.top + window.pageYOffset - Math.max(72, (window.innerHeight - r.height) / 2);
    window.scrollTo({ top: Math.max(0, top), behavior: reduced ? "auto" : "smooth" });
    place();
    setTimeout(place, reduced ? 0 : 350);
    ui.next.focus();
  }

  function onKey(e) {
    if (!state) { return; }
    if (e.key === "Escape") { e.preventDefault(); finish(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); state.ui.next.click(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(state.index - 1); }
    else if (e.key === "Tab") {
      var f = Array.prototype.filter.call(state.ui.tip.querySelectorAll("button"), function (b) { return !b.hidden; });
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (f.indexOf(doc.activeElement) === -1) { e.preventDefault(); first.focus(); }
    }
  }

  function save() {
    var url = root.getAttribute("data-tour-done-url");
    var meta = doc.querySelector('meta[name="csrf-token"]');
    if (!url || !window.fetch) { return; }
    fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": meta ? meta.content : "", "X-Requested-With": "fetch" }
    }).catch(function () { /* retried at next visit */ });
  }

  function finish() {
    if (!state) { return; }
    var ui = state.ui;
    [ui.backdrop, ui.spot, ui.tip].forEach(function (n) { n.parentNode.removeChild(n); });
    doc.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place, true);
    if (state.opener && state.opener.focus) { state.opener.focus(); }
    state = null;
    save();
  }

  function start() {
    if (state) { return; }
    var steps = collect();
    if (!steps.length) { return; }
    state = { steps: steps, index: 0, opener: doc.activeElement, ui: build() };
    doc.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    go(0);
  }
  window.ModulisTour = { start: start };

  if (root.getAttribute("data-tour-autostart") === "1") {
    if (window.history && history.replaceState && /[?&]visite=1/.test(location.search)) {
      history.replaceState(null, "", location.pathname);
    }
    setTimeout(start, reduced ? 0 : 400);
  }
})();
