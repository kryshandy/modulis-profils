/* Modulis Profils: video blocks (apps.blocks). The iframe is created only when the visitor asks for it:
   no third-party request, cookie or script before the click. Without JS the link opens the video. */
(function () {
  "use strict";
  var ALLOWED = ["https://www.youtube-nocookie.com/embed/", "https://player.vimeo.com/video/"];
  document.querySelectorAll("[data-video]").forEach(function (box) {
    var link = box.querySelector("a");
    var src = box.getAttribute("data-embed") || "";
    var ok = ALLOWED.some(function (prefix) { return src.indexOf(prefix) === 0; });
    if (!link || !ok) return;
    link.addEventListener("click", function (event) {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.button) return;
      event.preventDefault();
      var frame = document.createElement("iframe");
      frame.src = src;
      frame.title = box.getAttribute("data-title") || "";
      frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      frame.allowFullscreen = true;
      frame.referrerPolicy = "strict-origin-when-cross-origin";
      frame.className = "t-video__frame";
      box.replaceChildren(frame);
      frame.focus();
    });
  });
})();
