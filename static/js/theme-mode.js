/* Modulis Profils — Light / Dark / Auto theme controller.
   CSP-safe (external script, no inline code/eval). Loaded in <head> to set data-theme before first paint. */
(function () {
  "use strict";
  var KEY = "modulis-theme";
  var ORDER = ["auto", "light", "dark"];
  var LABELS = {
    auto: "Thème : Automatique (système)",
    light: "Thème : Clair",
    dark: "Thème : Sombre",
  };
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function readStored() {
    try {
      var val = window.localStorage.getItem(KEY);
      return val === "light" || val === "dark" ? val : "auto";
    } catch (_) {
      return "auto";
    }
  }

  function writeStored(mode) {
    try {
      if (mode === "auto") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, mode);
    } catch (_) {
      /* private browsing / storage disabled */
    }
  }

  function apply(mode) {
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode);
    else root.removeAttribute("data-theme");
  }

  function syncButtons(mode) {
    var effective = mode === "auto" ? (mq && mq.matches ? "dark" : "light") : mode;
    var label = LABELS[mode] || LABELS.auto;
    var btns = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < btns.length; i++) {
      var btn = btns[i];
      btn.setAttribute("data-theme-state", mode);
      btn.setAttribute("data-effective-theme", effective);
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
      btn.setAttribute("aria-pressed", effective === "dark" ? "true" : "false");
    }
  }

  var current = readStored();
  apply(current);

  function init() {
    syncButtons(current);
    document.addEventListener("click", function (e) {
      var btn = e.target && e.target.closest ? e.target.closest("[data-theme-toggle]") : null;
      if (!btn) return;
      var idx = ORDER.indexOf(current);
      current = ORDER[(idx + 1) % ORDER.length];
      writeStored(current);
      apply(current);
      syncButtons(current);
    });
    if (mq && mq.addEventListener) {
      mq.addEventListener("change", function () {
        if (current === "auto") syncButtons(current);
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
