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

/* Landing page: interactive city & trade filtering (#villes, #metiers, #pages-recentes). */
(function () {
  "use strict";
  var cityList = document.getElementById("pf-city-list");
  if (!cityList) return;

  var controls = document.getElementById("pf-cities-controls");
  var searchInput = document.getElementById("pf-city-search");
  var allBtn = document.getElementById("pf-city-all");
  var citiesEmpty = document.getElementById("pf-cities-empty");
  var banner = document.getElementById("pf-city-banner");
  var bannerTitle = document.getElementById("pf-city-banner-title");
  var bannerMeta = document.getElementById("pf-city-banner-meta");
  var bannerLink = document.getElementById("pf-city-banner-link");
  var bannerLinkLabel = document.getElementById("pf-city-banner-link-label");
  var bannerReset = document.getElementById("pf-city-banner-reset");
  var comboList = document.getElementById("pf-combo-list");
  var prosList = document.getElementById("pf-pros-list");
  var prosEmpty = document.getElementById("pf-pros-empty");
  var prosReset = document.getElementById("pf-pros-reset");

  var cityButtons = Array.prototype.slice.call(cityList.querySelectorAll(".pf-city"));
  var comboButtons = comboList ? Array.prototype.slice.call(comboList.querySelectorAll(".pf-combo")) : [];
  var proCards = prosList ? Array.prototype.slice.call(prosList.querySelectorAll(".pro-card")) : [];

  if (controls) controls.hidden = false;

  var state = { city: "", trade: "" };

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
  }

  function applyFilters() {
    var activeCityBtn = null;

    cityButtons.forEach(function (btn) {
      var active = btn.dataset.citySlug === state.city && state.city !== "";
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      if (active) activeCityBtn = btn;
    });

    if (allBtn) {
      var allActive = state.city === "" && state.trade === "";
      allBtn.classList.toggle("is-active", allActive);
      allBtn.setAttribute("aria-pressed", allActive ? "true" : "false");
    }

    var visibleCombos = 0;
    comboButtons.forEach(function (btn) {
      var li = btn.parentElement;
      var matchesCity = !state.city || btn.dataset.citySlug === state.city;
      li.hidden = !matchesCity;
      if (matchesCity) visibleCombos += 1;
      var comboActive = btn.dataset.citySlug === state.city && btn.dataset.tradeSlug === state.trade && state.trade !== "";
      btn.classList.toggle("is-active", comboActive);
      btn.setAttribute("aria-pressed", comboActive ? "true" : "false");
    });

    var visiblePros = 0;
    proCards.forEach(function (card) {
      var okCity = !state.city || card.dataset.city === state.city;
      var okTrade = !state.trade || card.dataset.trade === state.trade;
      var show = okCity && okTrade;
      card.hidden = !show;
      if (show) visiblePros += 1;
    });
    if (prosEmpty) prosEmpty.hidden = visiblePros > 0 || proCards.length === 0;

    if (banner && bannerTitle && bannerMeta) {
      if (!activeCityBtn) {
        banner.hidden = true;
      } else {
        var name = activeCityBtn.dataset.cityName || "";
        var count = Number(activeCityBtn.dataset.cityCount || 0);
        var url = activeCityBtn.dataset.cityUrl || "";
        bannerTitle.textContent = name;
        bannerMeta.textContent = count + (count > 1 ? " pros référencés" : " pro référencé") +
          (visibleCombos > 0 ? " · " + visibleCombos + (visibleCombos > 1 ? " métiers" : " métier") : "");
        if (bannerLink && bannerLinkLabel) {
          if (url) {
            bannerLink.href = url;
            bannerLinkLabel.textContent = "Voir les pros à " + name;
            bannerLink.hidden = false;
          } else {
            bannerLink.hidden = true;
          }
        }
        banner.hidden = false;
      }
    }
  }

  function resetAll() {
    state.city = "";
    state.trade = "";
    if (searchInput && searchInput.value) {
      searchInput.value = "";
      filterCitySearch();
    }
    applyFilters();
  }

  function filterCitySearch() {
    if (!searchInput) return;
    var q = norm(searchInput.value);
    var shown = 0;
    Array.prototype.slice.call(cityList.children).forEach(function (li) {
      var match = !q || norm(li.dataset.cityItem).indexOf(q) !== -1;
      li.hidden = !match;
      if (match) shown += 1;
    });
    if (citiesEmpty) citiesEmpty.hidden = shown > 0;
  }

  cityButtons.forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (btn.tagName === "A") e.preventDefault();
      var slug = btn.dataset.citySlug || "";
      state.city = state.city === slug ? "" : slug;
      state.trade = "";
      applyFilters();
    });
  });

  comboButtons.forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (btn.tagName === "A") e.preventDefault();
      var cSlug = btn.dataset.citySlug || "";
      var tSlug = btn.dataset.tradeSlug || "";
      if (state.city === cSlug && state.trade === tSlug) {
        state.trade = "";
      } else {
        state.city = cSlug;
        state.trade = tSlug;
      }
      applyFilters();
    });
  });

  if (allBtn) allBtn.addEventListener("click", resetAll);
  if (bannerReset) bannerReset.addEventListener("click", resetAll);
  if (prosReset) prosReset.addEventListener("click", resetAll);
  if (searchInput) searchInput.addEventListener("input", filterCitySearch);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && (state.city || state.trade || (searchInput && searchInput.value))) resetAll();
  });
})();
