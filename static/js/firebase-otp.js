/* Modulis Profils — OTP by SMS through Firebase Authentication (ADR-0009).
   ES module, CSP-safe: configuration comes from data-* attributes of #firebase-otp, no inline script.
   Our server has already checked the number (whitelist, limits, blocked numbers, switches) before
   this page could start a send. Firebase sends and checks the SMS; we post the resulting ID token
   (with the CSRF token) to data-verify-url, where the server verifies it before logging in.
   Anti SMS-pumping: this script asks Firebase for AT MOST ONE SMS per page load, and only when the
   server set data-autostart (a fresh challenge it has just created). Every resend goes through our
   server ("resend" form: delay, hourly caps, new challenge), never a client-only retry. */

const root = document.querySelector("[data-firebase-otp]");
const form = document.querySelector("[data-firebase-form]");

if (root && form) {
  start().catch(() => showError(root.dataset.msgLoad));
}

function $(sel) { return document.querySelector(sel); }

function setStatus(text) {
  const el = $("[data-firebase-status]");
  if (el) { el.textContent = text || ""; }
}

function showError(text) {
  const el = $("[data-firebase-error]");
  setStatus("");
  if (!el) { return; }
  el.textContent = text || "";
  el.hidden = !text;
}

function csrfToken() {
  const input = form.querySelector("input[name=csrfmiddlewaretoken]");
  return input ? input.value : "";
}

function messageFor(error) {
  const d = root.dataset;
  const code = (error && error.code) || "";
  switch (code) {
    case "auth/invalid-verification-code":
    case "auth/missing-verification-code":
      return d.msgInvalidCode;
    case "auth/code-expired":
    case "auth/session-expired":
      return d.msgExpired;
    case "auth/too-many-requests":
      return d.msgTooMany;
    case "auth/quota-exceeded":
      return d.msgQuota;
    case "auth/captcha-check-failed":
    case "auth/invalid-app-credential":
    case "auth/missing-app-credential":
    case "auth/recaptcha-not-enabled":
      return d.msgCaptcha;
    case "auth/network-request-failed":
      return d.msgNetwork;
    case "auth/invalid-phone-number":
    case "auth/operation-not-allowed":
      return d.msgPhone;
    default:
      return d.msgGeneric;
  }
}

async function start() {
  const d = root.dataset;
  if (!/^\d+\.\d+\.\d+$/.test(d.sdkVersion || "")) { throw new Error("bad sdk version"); }
  const base = "https://www.gstatic.com/firebasejs/" + d.sdkVersion + "/";
  const [appSdk, authSdk] = await Promise.all([import(base + "firebase-app.js"), import(base + "firebase-auth.js")]);

  const app = appSdk.initializeApp({
    apiKey: d.apiKey, authDomain: d.authDomain, projectId: d.projectId, appId: d.appId,
  });
  const auth = authSdk.getAuth(app);
  auth.languageCode = d.lang || "fr";

  const submit = form.querySelector("[type=submit]");
  const codeInput = form.querySelector("input[name=code]");
  const retryWrap = $("[data-firebase-retry-wrap]");
  const retryButton = $("[data-firebase-retry]");
  let verifier = null;
  let confirmation = null;
  let attempted = false; // one Firebase send per page load, whatever happens

  function resetVerifier() {
    if (verifier) { try { verifier.clear(); } catch (e) { /* already cleared */ } }
    verifier = null;
    const container = $("#recaptcha-container");
    if (container) { container.textContent = ""; }
  }

  async function send() {
    if (attempted) { return; }
    attempted = true;
    showError("");
    if (retryWrap) { retryWrap.hidden = true; }
    setStatus(d.msgSending);
    try {
      resetVerifier();
      verifier = new authSdk.RecaptchaVerifier(auth, "recaptcha-container", { size: "invisible" });
      confirmation = await authSdk.signInWithPhoneNumber(auth, d.phone, verifier);
      setStatus(d.msgSent);
      if (codeInput) { codeInput.focus(); }
    } catch (error) {
      confirmation = null;
      resetVerifier();
      showError(messageFor(error));
      // Retrying always goes through the server (new challenge, server-side limits).
      if (retryWrap && serverResend() && error && error.code !== "auth/too-many-requests" && error.code !== "auth/quota-exceeded") {
        retryWrap.hidden = false;
      }
    }
  }

  function serverResend() {
    const input = document.querySelector("form input[name=action][value=resend]");
    return input ? input.form : null;
  }

  if (retryButton) {
    retryButton.addEventListener("click", () => {
      const resendForm = serverResend();
      if (resendForm) { resendForm.requestSubmit(); }
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!confirmation) { showError(d.msgNotSent); return; }
    const code = (codeInput ? codeInput.value : "").replace(/\s+/g, "");
    if (!/^\d{6}$/.test(code)) { showError(d.msgInvalidCode); return; }
    if (submit) { submit.disabled = true; }
    showError("");
    setStatus(d.msgChecking);
    try {
      const credential = await confirmation.confirm(code);
      const idToken = await credential.user.getIdToken();
      const body = new URLSearchParams({ action: "firebase", id_token: idToken });
      const response = await fetch(d.verifyUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" },
        body: body,
      });
      const data = await response.json().catch(() => ({}));
      // Our server keeps its own session: the Firebase session is not needed any more.
      await authSdk.signOut(auth).catch(() => {});
      if (response.ok && typeof data.redirect === "string" && /^\/(?![\/\\])/.test(data.redirect)) {
        window.location.assign(data.redirect);
        return;
      }
      showError(data.error || d.msgGeneric);
    } catch (error) {
      showError(messageFor(error));
    } finally {
      if (submit) { submit.disabled = false; }
    }
  });

  if (d.autostart === "1") {
    send();
  } else {
    setStatus(d.msgReload);
  }
}
