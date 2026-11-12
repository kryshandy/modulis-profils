/* Pro pages: progressive motion (strict CSP, data-* hooks). Without JS all is visible and works.
 prefers-reduced-motion: no reveal, parallax, counters or magnetic buttons. */
(function () {
"use strict";
var doc = document, root = doc.documentElement, win = window;
var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); };
var calm = win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches;
var fine = win.matchMedia && win.matchMedia("(hover: hover) and (pointer: fine)").matches;
var IO = "IntersectionObserver" in win;
var vh = function () { return win.innerHeight || root.clientHeight; };

/* Top bar state + scroll progress + parallax (one rAF per frame) */
var bar = doc.querySelector("[data-bar]"), progress = doc.querySelector(".t-progress");
var para = calm ? [] : $$("[data-parallax]");
var ticking = false;
function frame() {
ticking = false;
var y = win.scrollY || 0, max = root.scrollHeight - vh(), h = vh();
if (bar) { bar.classList.toggle("is-scrolled", y > 8); }
if (progress) { progress.style.setProperty("--p", max > 0 ? Math.min(1, y / max).toFixed(4) : 0); }
para.forEach(function (el) {
var r = el.getBoundingClientRect();
if (r.bottom < 0 || r.top > h) { return; }
var shift = ((r.top + r.height / 2) - h / 2) * -0.06;
var inner = el.getAttribute("data-parallax") === "inner" ? el.firstElementChild : null;
if (inner) { inner.style.transform = "translate3d(0," + (shift * 0.8).toFixed(1) + "px,0) scale(1.12)"; }
else { el.style.transform = "translate3d(0," + shift.toFixed(1) + "px,0)"; }
});
}
function onScroll() { if (!ticking) { ticking = true; win.requestAnimationFrame(frame); } }
win.addEventListener("scroll", onScroll, { passive: true });
win.addEventListener("resize", onScroll, { passive: true });
frame();

/* Reveal on scroll (below the fold only: nothing visible blinks) */
if (!calm && IO) {
var seen = new IntersectionObserver(function (entries) {
entries.forEach(function (e) {
if (!e.isIntersecting) { return; }
e.target.classList.add("is-in");
seen.unobserve(e.target);
});
}, { rootMargin: "0px 0px -8% 0px" });
var groups = new Map();
$$("[data-reveal]").forEach(function (el) {
if (el.getBoundingClientRect().top < vh()) { return; }
var n = groups.get(el.parentNode) || 0;
groups.set(el.parentNode, n + 1);
el.style.setProperty("--d", Math.min(n, 6) * 0.07 + "s");
el.classList.add("t-rv");
seen.observe(el);
});

/* Counters (below the fold only): 0 → value */
var count = new IntersectionObserver(function (entries) {
entries.forEach(function (e) {
if (!e.isIntersecting) { return; }
count.unobserve(e.target);
var el = e.target, end = parseInt(el.getAttribute("data-count"), 10), t0 = 0;
if (!(end > 1)) { return; }
(function step(t) {
t0 = t0 || t;
var k = Math.min(1, (t - t0) / 1100);
el.textContent = Math.round(end * (1 - Math.pow(1 - k, 3)));
if (k < 1) { win.requestAnimationFrame(step); }
})(win.performance.now());
});
}, { threshold: 0.6 });
$$("[data-count]").forEach(function (el) { if (el.getBoundingClientRect().top > vh()) { count.observe(el); } });
}

/* Dock hidden while the hero buttons are on screen */
var dock = doc.querySelector(".t-dock"), acts = doc.querySelector(".t-actions");
if (dock && acts && IO) { new IntersectionObserver(function (e) { dock.classList.toggle("is-off", e[0].isIntersecting); }).observe(acts); }

/* In-page navigation: highlight the section being read */
var navLinks = $$("[data-nav]");
if (navLinks.length && IO) {
var spy = new IntersectionObserver(function (entries) {
entries.forEach(function (e) {
if (!e.isIntersecting) { return; }
navLinks.forEach(function (a) { a.classList.toggle("is-active", a.getAttribute("data-nav") === e.target.id); });
});
}, { rootMargin: "-45% 0px -50% 0px" });
navLinks.forEach(function (a) { var s = doc.getElementById(a.getAttribute("data-nav")); if (s) { spy.observe(s); } });
}

/* Magnetic buttons (mouse only) */
if (fine && !calm) {
$$("[data-magnetic]").forEach(function (b) {
b.addEventListener("pointermove", function (e) {
var r = b.getBoundingClientRect();
var x = (e.clientX - r.left - r.width / 2) * 0.22, y = (e.clientY - r.top - r.height / 2) * 0.32;
b.style.transform = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px,0)";
});
b.addEventListener("pointerleave", function () { b.style.transform = ""; });
});
}

/* Lightbox: native modal <dialog>, focus kept inside, arrows / Escape / swipe */
var dlg = doc.querySelector("[data-lightbox]"), links = $$("[data-lb]");
if (dlg && typeof dlg.showModal === "function" && links.length) {
var img = dlg.querySelector("[data-lb-img]"), cap = dlg.querySelector("[data-lb-cap]");
var counter = dlg.querySelector("[data-lb-count]"), at = 0, opener = null, x0 = null;
var show = function (n) {
at = (n + links.length) % links.length;
var a = links[at], thumb = a.querySelector("img");
img.src = a.href;
img.alt = thumb ? thumb.alt : "";
if (thumb) { img.width = thumb.width; img.height = thumb.height; img.setAttribute("width", thumb.getAttribute("width")); img.setAttribute("height", thumb.getAttribute("height")); }
cap.textContent = a.getAttribute("data-lb-caption") || "";
counter.textContent = (at + 1) + " / " + links.length;
};
links.forEach(function (a, n) {
a.addEventListener("click", function (e) {
if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
e.preventDefault();
opener = a;
img.loading = "eager";
show(n);
dlg.showModal();
dlg.querySelector("[data-lb-close]").focus();
});
});
dlg.addEventListener("click", function (e) {
var t = e.target;
if (t === dlg || t.closest("[data-lb-close]")) { dlg.close(); }
else if (t.closest("[data-lb-prev]")) { show(at - 1); }
else if (t.closest("[data-lb-next]")) { show(at + 1); }
});
dlg.addEventListener("keydown", function (e) {
if (e.key === "ArrowLeft") { show(at - 1); }
else if (e.key === "ArrowRight") { show(at + 1); }
else if (e.key === "Tab") {
var f = $$("button", dlg), first = f[0], last = f[f.length - 1];
if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
}
});
dlg.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
dlg.addEventListener("touchend", function (e) {
if (x0 === null) { return; }
var dx = e.changedTouches[0].clientX - x0;
x0 = null;
if (Math.abs(dx) > 50) { show(at + (dx < 0 ? 1 : -1)); }
});
dlg.addEventListener("close", function () { if (opener) { opener.focus(); } });
}

/* Open now: recomputed in Douala time (UTC+1, no DST), cached pages stay right */
var hours = doc.querySelector("[data-hours]");
if (hours) {
var rows = $$("tbody tr", hours);
var label = function (k) { return hours.getAttribute("data-l-" + k) || ""; };
var pad = function (n) { return (n < 10 ? "0" : "") + n; };
var ranges = function (k) {
return (rows[k].getAttribute("data-ranges") || "").split(",").filter(Boolean).map(function (r) { return r.split("-"); });
};
var update = function () {
if (rows.length !== 7) { return; }
var d = new Date(Date.now() + 36e5), wd = (d.getUTCDay() + 6) % 7;
var hm = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()), closes = "", detail = "";
ranges(wd).forEach(function (r) { if (r[0] <= hm && hm < r[1]) { closes = r[1]; } });
if (closes) { detail = label("closes").replace("{t}", closes); }
for (var o = 0; o < 8 && !detail; o++) {
var k = (wd + o) % 7;
var next = ranges(k).map(function (r) { return r[0]; }).filter(function (s) { return o || s > hm; })[0];
if (!next) { continue; }
var day = rows[k].querySelector("th").firstChild.textContent.trim().toLowerCase();
detail = (o === 0 ? label("opens") : o === 1 ? label("tomorrow") : label("day").replace("{d}", day)).replace("{t}", next);
}
rows.forEach(function (r, k) { r.classList.toggle("is-today", k === wd); });
$$("[data-open-state]").forEach(function (el) {
el.classList.toggle("is-open", !!closes);
el.querySelector("[data-open-label]").textContent = label(closes ? "open" : "closed");
el.querySelector("[data-open-detail]").textContent = detail;
});
};
update();
win.setInterval(update, 60000);
}
})();
