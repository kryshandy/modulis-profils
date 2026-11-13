/* Modulis Profils: platform public pages (home). Progressive enhancement only, the page is complete without it.
   Scroll reveals: elements marked .pf-reveal that are below the fold fade in when they enter the viewport.
   Nothing happens with prefers-reduced-motion or without IntersectionObserver. CSP-safe (no inline code). */
(function () {
  "use strict";
  var items = document.querySelectorAll(".pf-reveal");
  if (!items.length || !("IntersectionObserver" in window)) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

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
})();
