/* Modulis Profils — Espace pro behaviours. Vanilla JS, progressive enhancement, CSP-safe
   (no eval, no inline handlers: everything is wired from data-* attributes). */
(function () {
  "use strict";
  var doc = document;
  doc.documentElement.classList.add("js");

  function $(sel, root) { return (root || doc).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }
  function csrf() { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; }

  /* Toast --------------------------------------------------------------------------------- */
  var toastTimer;
  function toast(message, kind) {
    var el = $("#toast");
    if (!el) {
      el = doc.createElement("div");
      el.id = "toast"; el.className = "toast"; el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
      doc.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.toggle("toast--error", kind === "error");
    el.hidden = false;
    requestAnimationFrame(function () { el.classList.add("is-visible"); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove("is-visible");
      setTimeout(function () { el.hidden = true; }, 300);
    }, kind === "error" ? 5000 : 2600);
  }
  window.ModulisToast = toast;

  /* HTMX glue ---------------------------------------------------------------------------- */
  doc.addEventListener("htmx:configRequest", function (e) {
    e.detail.headers["X-CSRFToken"] = csrf();
  });
  doc.body.addEventListener("toast", function (e) {
    var d = e.detail || {};
    toast(d.message || d.value || "OK", d.kind);
  });
  doc.addEventListener("htmx:beforeSwap", function (e) {
    var xhr = e.detail.xhr;
    if (xhr && xhr.responseURL && xhr.responseURL.indexOf("/espace/connexion") !== -1) {
      window.location.href = xhr.responseURL; // session expired: go to the login page
      e.detail.shouldSwap = false;
    }
  });
  doc.addEventListener("htmx:sendError", function () {
    toast(doc.documentElement.lang === "en" ? "No connection. Try again." : "Pas de connexion. Réessaie dans un instant.", "error");
  });
  doc.addEventListener("htmx:responseError", function (e) {
    var xhr = e.detail && e.detail.xhr;
    if (xhr && xhr.getResponseHeader("HX-Trigger")) { return; } // the server already sent its own message
    toast(doc.documentElement.lang === "en" ? "Something went wrong." : "Oups, une erreur. Réessaie.", "error");
  });
  doc.addEventListener("htmx:afterSwap", function (e) { init(e.detail.target || doc); });
  doc.addEventListener("htmx:afterRequest", function (e) {
    $$(".is-busy", e.detail.elt).forEach(resetBusy);
  });
  window.addEventListener("offline", function () { toast("Pas de connexion internet.", "error"); });

  /* Busy buttons (avoid double submit on slow networks) ------------------------------------ */
  function resetBusy(btn) {
    btn.classList.remove("is-busy");
    if (btn.dataset.label) { btn.textContent = btn.dataset.label; }
  }
  doc.addEventListener("submit", function (e) {
    var form = e.target;
    var confirmText = form.getAttribute("data-confirm");
    if (confirmText && !window.confirm(confirmText)) { e.preventDefault(); return; }
    var btn = e.submitter || $("[type=submit][data-busy]", form);
    if (btn && btn.hasAttribute("data-busy")) {
      // Not `disabled`: a disabled submitter would drop its name/value from the POST.
      btn.dataset.label = btn.textContent;
      btn.textContent = btn.getAttribute("data-busy");
      btn.classList.add("is-busy");
    }
  });
  window.addEventListener("pageshow", function () { $$(".is-busy").forEach(resetBusy); });

  /* Clicks: copy, print, insert sentence ---------------------------------------------------- */
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) { return navigator.clipboard.writeText(text); }
    return new Promise(function (resolve, reject) {
      var ta = doc.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.className = "sr-only";
      doc.body.appendChild(ta); ta.select();
      try { doc.execCommand("copy") ? resolve() : reject(); } catch (err) { reject(err); }
      doc.body.removeChild(ta);
    });
  }
  doc.addEventListener("click", function (e) {
    var t = e.target.closest("[data-copy],[data-print],[data-insert]");
    if (!t) { return; }
    if (t.hasAttribute("data-copy")) {
      copy(t.getAttribute("data-copy")).then(
        function () { toast(t.getAttribute("data-copied") || "Copié ✓"); },
        function () { toast("Copie impossible : appuie longuement sur le lien.", "error"); }
      );
    } else if (t.hasAttribute("data-print")) {
      window.print();
    } else {
      var field = doc.getElementById(t.getAttribute("data-insert-target"));
      if (!field) { return; }
      var sentence = t.getAttribute("data-insert");
      var current = field.value.replace(/\s+$/, "");
      field.value = current ? current + " " + sentence : sentence;
      field.dispatchEvent(new Event("input", { bubbles: true }));
      t.classList.add("is-used");
      field.focus();
    }
  });

  /* Auto-submit selects (profile switcher) ------------------------------------------------ */
  doc.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches("select[data-autosubmit]")) { t.form.submit(); }
    if (t.matches("input[type=file][data-preview]")) { preview(t); }
    if (t.matches("input[type=file][data-files-label]")) {
      var out = $("[data-files-output]", t.closest("form"));
      if (out) { out.textContent = t.files.length ? t.files.length + " photo(s) choisie(s) ✓" : ""; }
    }
  });

  function preview(input) {
    var picker = input.closest("[data-photo-picker]");
    if (!picker || !input.files || !input.files[0]) { return; }
    $$("input[type=file][name='" + input.name + "']", picker).forEach(function (other) {
      if (other !== input) { other.value = ""; } // only one file is sent
    });
    var img = $("[data-preview-img]", picker);
    var empty = $("[data-preview-empty]", picker);
    if (img && window.URL) {
      img.src = URL.createObjectURL(input.files[0]);
      img.hidden = false;
      if (empty) { empty.hidden = true; }
    }
    var name = $("[data-preview-name]", picker);
    if (name) { name.textContent = input.files[0].name + " ✓"; }
  }

  /* Character counter --------------------------------------------------------------------- */
  function counter(field) {
    var out = $('[data-counter-for="' + field.id + '"] [data-counter-text]');
    if (!out) { return; }
    var min = parseInt(field.getAttribute("data-min") || "0", 10);
    var n = field.value.trim().length;
    var wrap = out.parentNode;
    if (n >= min) {
      out.textContent = n + " caractères ✓ Assez long pour Google";
      wrap.classList.add("is-ok");
    } else {
      out.textContent = n + " / " + min + " caractères — encore " + (min - n) + " pour Google";
      wrap.classList.remove("is-ok");
    }
  }
  doc.addEventListener("input", function (e) {
    if (e.target.matches("textarea[data-counter]")) { counter(e.target); }
    if (e.target.matches("input[data-filter-select]")) { filterSelect(e.target); }
  });

  /* Searchable select: filters <option>s as you type -------------------------------------- */
  function normalize(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function filterSelect(input) {
    var select = doc.getElementById(input.getAttribute("data-filter-select"));
    if (!select) { return; }
    var q = normalize(input.value.trim());
    var first = null;
    $$("option", select).forEach(function (opt) {
      var keep = !q || !opt.value || opt.value === "other" || normalize(opt.textContent).indexOf(q) !== -1;
      opt.hidden = !keep; opt.disabled = !keep && !opt.selected;
      if (keep && q && opt.value && opt.value !== "other" && !first) { first = opt; }
    });
    $$("optgroup", select).forEach(function (g) {
      g.hidden = !$$("option", g).some(function (o) { return !o.hidden; });
    });
    if (first && select.value !== first.value) {
      select.value = first.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  /* Conditional blocks: data-show-when="select-id=value" ---------------------------------- */
  function showWhen(block) {
    var parts = block.getAttribute("data-show-when").split("=");
    var ctl = doc.getElementById(parts[0]);
    if (!ctl) { return; }
    var update = function () { block.hidden = ctl.value !== parts[1]; };
    ctl.addEventListener("change", update);
    update();
  }

  /* Resend countdown (verify page) -------------------------------------------------------- */
  function countdown(btn) {
    var left = parseInt(btn.getAttribute("data-countdown") || "0", 10);
    if (!left) { return; }
    var label = btn.textContent;
    var tpl = btn.getAttribute("data-countdown-label") || "%s s";
    btn.disabled = true;
    var tick = function () {
      if (left <= 0) { btn.disabled = false; btn.textContent = label; return; }
      btn.textContent = tpl.replace("%s", left);
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  }

  /* "Ma position" button: fills latitude/longitude from navigator.geolocation -------------- */
  function geolocate(btn) {
    var root = btn.closest("[data-geo-root]") || doc;
    var lat = $('[data-geo="lat"]', root);
    var lng = $('[data-geo="lng"]', root);
    var status = $("[data-geo-status]", root);
    var say = function (key) { if (status) { status.textContent = btn.getAttribute(key) || ""; } };
    if (!lat || !lng) { return; }
    if (!("geolocation" in navigator)) { say("data-geo-unsupported"); return; }
    btn.addEventListener("click", function () {
      btn.disabled = true;
      say("data-geo-busy");
      navigator.geolocation.getCurrentPosition(function (pos) {
        lat.value = pos.coords.latitude.toFixed(6);
        lng.value = pos.coords.longitude.toFixed(6);
        btn.disabled = false;
        say("data-geo-ok");
      }, function () {
        btn.disabled = false;
        say("data-geo-error");
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
    });
  }

  /* "Plus" sheet of the bottom nav: close on outside tap and Escape ------------------------ */
  doc.addEventListener("click", function (e) {
    $$("details.more[open]").forEach(function (d) { if (!d.contains(e.target)) { d.open = false; } });
  });
  doc.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    $$("details.more[open]").forEach(function (d) {
      d.open = false;
      var s = $("summary", d);
      if (s) { s.focus(); }
    });
  });

  /* Init (on load and after every HTMX swap) ---------------------------------------------- */
  function init(root) {
    $$(".js-only[hidden]", root).forEach(function (el) { el.hidden = false; });
    $$("textarea[data-counter]", root).forEach(counter);
    $$("[data-show-when]", root).forEach(showWhen);
    $$("[data-countdown]", root).forEach(countdown);
    $$("[data-geolocate]", root).forEach(geolocate);
  }
  if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", function () { init(doc); }); }
  else { init(doc); }
})();
