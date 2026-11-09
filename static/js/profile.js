/* Click tracking on public profile pages. Optional enhancement: the page works without it.
   Data comes from data-* attributes only (strict CSP, no inline script). Fails silently. */
(function () {
  "use strict";
  try {
    var root = document.querySelector("[data-profile-id]");
    if (!root || !navigator.sendBeacon) { return; }
    var id = root.getAttribute("data-profile-id");
    if (!/^\d+$/.test(id || "")) { return; }
    document.addEventListener("click", function (event) {
      try {
        var el = event.target && event.target.closest ? event.target.closest("[data-track]") : null;
        if (!el) { return; }
        var kind = el.getAttribute("data-track");
        if (!/^[a-z]{2,16}$/.test(kind || "")) { return; }
        navigator.sendBeacon("/a/" + id + "/" + kind);
      } catch (e) { /* never break a click */ }
    }, true);
  } catch (e) { /* tracking is best effort */ }
})();
