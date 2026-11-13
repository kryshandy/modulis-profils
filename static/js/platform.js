/* Modulis Profils: platform public pages (home). Progressive enhancement only, the page is complete without it.
   Scroll reveals: elements marked .pf-reveal that are below the fold fade in when they enter the viewport.
   Nothing happens with prefers-reduced-motion or without IntersectionObserver. CSP-safe (no inline code). */
(function () {
  "use strict";
  var items = document.querySelectorAll(".pf-reveal");
  if (!items.length || !("IntersectionObserver" in window)) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (window.location.hash) return; // opened on an anchor (/#comment): show the page as is

  var fold = window.innerHeight;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      entry.target.classList.remove("is-pending");
      io.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

  items.forEach(function (el) {
    // Only what is still below the fold waits: nothing visible ever disappears.
    if (el.getBoundingClientRect().top < fold) return;
    el.classList.add("is-pending");
    io.observe(el);
  });
  // Safety net: anything in the viewport still hidden after 1.5 s is shown.
  function rescue() {
    document.querySelectorAll(".pf-reveal.is-pending").forEach(function (el) {
      var box = el.getBoundingClientRect();
      if (box.top < window.innerHeight && box.bottom > 0) {
        el.classList.add("is-in");
        el.classList.remove("is-pending");
        io.unobserve(el);
      }
    });
  }
  window.setTimeout(rescue, 1500);
  window.addEventListener("hashchange", function () { window.setTimeout(rescue, 600); });
})();
