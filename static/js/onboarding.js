/* Onboarding wizard helpers.
   On unstable 3G a POST can fail and the text typed is lost: we keep a draft of the text fields
   in sessionStorage (this tab only) and restore it if the step is shown again empty. */
(function () {
  "use strict";
  var form = document.querySelector(".wizard__body form[method=post]");
  if (!form || !window.sessionStorage) { return; }
  var key = "draft:" + location.pathname;
  var SUBMITTED = "draft:submitted";

  function store() { try { return window.sessionStorage; } catch (e) { return null; } }
  var ss = store();
  if (!ss) { return; }

  // The previous step was saved successfully (we are on another page): forget its draft.
  var last = ss.getItem(SUBMITTED);
  if (last && last !== location.pathname) { ss.removeItem("draft:" + last); ss.removeItem(SUBMITTED); }

  var fields = Array.prototype.filter.call(form.elements, function (el) {
    return (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && /^(text|tel|email|search)$/.test(el.type))) && el.name;
  });

  var hasErrors = !!form.querySelector(".form-field__error, .alert--error");
  var draft = null;
  try { draft = JSON.parse(ss.getItem(key) || "null"); } catch (e) { draft = null; }
  if (draft && !hasErrors) {
    fields.forEach(function (el) {
      if (!el.value && draft[el.name]) {
        el.value = draft[el.name];
        el.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
  }

  var timer;
  form.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var data = {};
      fields.forEach(function (el) { if (el.value) { data[el.name] = el.value; } });
      try { ss.setItem(key, JSON.stringify(data)); } catch (e) { /* storage full: ignore */ }
    }, 400);
  });
  form.addEventListener("submit", function () { ss.setItem(SUBMITTED, location.pathname); });

  // Put the cursor in the first field with an error, else leave the autofocus as is.
  var bad = form.querySelector(".form-field--error input, .form-field--error textarea, .form-field--error select");
  if (bad) { bad.focus(); }
})();
