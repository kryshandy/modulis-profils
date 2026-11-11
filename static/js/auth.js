/* Modulis Profils — OTP channel choice: the submit button says where the code will arrive.
   Progressive enhancement only (the form works without it); CSP-safe, no inline handlers. */
(function () {
  "use strict";
  var forms = document.querySelectorAll("[data-channel-form]");
  Array.prototype.forEach.call(forms, function (form) {
    var submit = form.querySelector("[type=submit]");
    var radios = form.querySelectorAll("input[type=radio][data-submit-label]");
    if (!submit || !radios.length) { return; }
    function update() {
      var checked = form.querySelector("input[type=radio][data-submit-label]:checked");
      if (checked) { submit.textContent = checked.getAttribute("data-submit-label"); }
    }
    Array.prototype.forEach.call(radios, function (radio) { radio.addEventListener("change", update); });
    update();
  });
})();
