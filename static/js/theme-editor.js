/* Espace pro › Modèles: preview device toggle and live customizer (strict CSP: no inline script, no eval).
   Progressive enhancement: without JS, the customizer form posts normally and the arrows are submit buttons. */
(function () {
  "use strict";
  var doc = document;

  function $(sel, root) { return (root || doc).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

  /* 1. Mobile / desktop toggle ------------------------------------------------------------ */
  // Desktop = the real 1280 px page, scaled down to the column (CSSOM styles are allowed by the CSP).
  var DESKTOP_WIDTH = 1280;
  var DESKTOP_HEIGHT = 900;
  function fit(box) {
    var stage = $("[data-stage]", box);
    var device = $(".tm-preview__device", box);
    var frame = $("[data-preview-frame]", box);
    if (!stage || !device || !frame) { return; }
    if (stage.getAttribute("data-stage") !== "desktop") {
      frame.style.transform = "";
      frame.style.width = "";
      frame.style.height = "";
      device.style.height = "";
      return;
    }
    var scale = Math.min(1, device.clientWidth / DESKTOP_WIDTH);
    frame.style.width = DESKTOP_WIDTH + "px";
    frame.style.height = DESKTOP_HEIGHT + "px";
    frame.style.transform = "scale(" + scale.toFixed(4) + ")";
    device.style.height = Math.round(DESKTOP_HEIGHT * scale) + "px";
  }
  $$("[data-preview]").forEach(function (box) {
    var stage = $("[data-stage]", box);
    $$("[data-device]", box).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var device = btn.getAttribute("data-device");
        stage.setAttribute("data-stage", device === "desktop" ? "desktop" : "mobile");
        $$("[data-device]", box).forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
        fit(box);
      });
    });
    box.classList.add("is-enhanced");
    window.addEventListener("resize", function () { fit(box); });
  });

  /* 2. Customizer ---------------------------------------------------------------------------- */
  var form = $("[data-theme-editor]");
  if (!form || !window.fetch || !window.FormData) { return; }
  var frame = $("[data-preview-frame]");
  var status = $("[data-preview-status]");
  var saveState = $("[data-save-state]");
  var timer = null;
  var pending = null;
  var MESSAGES = { saving: "Enregistrement…", saved: "Brouillon enregistré ✓", offline: "Pas de connexion : réessaie." };

  function setState(text) { if (saveState) { saveState.textContent = text; } }

  function refreshButtons() {
    var items = $$("[data-section]", form);
    items.forEach(function (li, i) {
      var up = $('[data-move="up"]', li);
      var down = $('[data-move="down"]', li);
      if (up) { up.disabled = i === 0; }
      if (down) { down.disabled = i === items.length - 1; }
    });
  }

  function save() {
    var data = new FormData(form);
    data.delete("move");
    data.delete("next");
    if (pending && pending.abort) { pending.abort(); }
    pending = window.AbortController ? new AbortController() : null;
    setState(MESSAGES.saving);
    if (status) { status.hidden = false; }
    fetch(form.action, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-Requested-With": "theme-editor" },
      signal: pending ? pending.signal : undefined
    }).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (res) {
      if (!res.ok || !res.body.ok) {
        setState((res.body && res.body.error) || "Erreur");
        if (status) { status.hidden = true; }
        return;
      }
      setState(MESSAGES.saved);
      var url = res.body.preview_url;
      if (frame && typeof url === "string" && url.charAt(0) === "/") {
        frame.addEventListener("load", function done() {
          frame.removeEventListener("load", done);
          if (status) { status.hidden = true; }
        });
        frame.src = url;
      }
    }).catch(function (err) {
      if (err && err.name === "AbortError") { return; }
      setState(MESSAGES.offline);
      if (status) { status.hidden = true; }
    });
  }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(save, delay);
  }

  // A preset fills the colour inputs; touching a colour switches to "Mes couleurs".
  form.addEventListener("change", function (e) {
    var t = e.target;
    if (t.name === "preset" && t.value !== "custom") {
      ["primary", "accent", "background", "surface", "text"].forEach(function (key) {
        var input = $('[data-color="' + key + '"]', form);
        var value = t.getAttribute("data-" + key);
        if (input && /^#[0-9a-fA-F]{6}$/.test(value || "")) { input.value = value.toLowerCase(); }
      });
    }
    if (t.hasAttribute && t.hasAttribute("data-color")) {
      var custom = $("[data-custom]", form);
      if (custom) { custom.checked = true; }
    }
    schedule(t.type === "text" ? 600 : 150);
  });
  form.addEventListener("input", function (e) {
    if (e.target.type === "text") { schedule(700); }
    if (e.target.type === "color") {
      var custom = $("[data-custom]", form);
      if (custom) { custom.checked = true; }
      schedule(400);
    }
  });

  // Up / down arrows reorder the list in place, then save (no reload).
  form.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-move]") : null;
    if (!btn) { return; }
    e.preventDefault();
    var li = btn.closest("[data-section]");
    if (!li) { return; }
    if (btn.getAttribute("data-move") === "up" && li.previousElementSibling) {
      li.parentNode.insertBefore(li, li.previousElementSibling);
    } else if (btn.getAttribute("data-move") === "down" && li.nextElementSibling) {
      li.parentNode.insertBefore(li.nextElementSibling, li);
    }
    refreshButtons();
    var again = $('[data-move="' + btn.getAttribute("data-move") + '"]', li);
    if (again && !again.disabled) { again.focus(); } else { btn.blur(); }
    schedule(100);
  });

  // "Enregistrer le brouillon" saves in place; "Valider et publier" keeps the normal submit.
  form.addEventListener("submit", function (e) {
    var submitter = e.submitter;
    if (submitter && submitter.name === "next") { return; }
    e.preventDefault();
    clearTimeout(timer);
    save();
  });
})();
