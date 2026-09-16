/**
 * dong-ui theme controller — light / dark with optional system default.
 * Reimplements CloudCLI-style class toggle (original code).
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "dong-ui-theme";
  var LIGHT_META = "#f6f4ef";
  var DARK_META = "#141414";

  function systemPrefersDark() {
    return (
      global.matchMedia &&
      global.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function getStored() {
    try {
      var v = global.localStorage.getItem(STORAGE_KEY);
      if (v === "light" || v === "dark") return v;
    } catch (_) {}
    return null;
  }

  function setStored(mode) {
    try {
      if (mode === "light" || mode === "dark") {
        global.localStorage.setItem(STORAGE_KEY, mode);
      } else {
        global.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (_) {}
  }

  function resolveMode(preference) {
    if (preference === "light" || preference === "dark") return preference;
    return systemPrefersDark() ? "dark" : "light";
  }

  function updateMeta(mode) {
    var color = mode === "dark" ? DARK_META : LIGHT_META;
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    if (!metas.length) {
      var m = document.createElement("meta");
      m.setAttribute("name", "theme-color");
      m.setAttribute("content", color);
      document.head.appendChild(m);
      return;
    }
    metas.forEach(function (meta) {
      meta.setAttribute("content", color);
      meta.removeAttribute("media");
    });
  }

  function apply(mode) {
    var root = document.documentElement;
    var dark = mode === "dark";
    root.classList.toggle("dark", dark);
    root.style.colorScheme = dark ? "dark" : "light";
    updateMeta(mode);
    document.querySelectorAll("[data-dong-theme-toggle]").forEach(function (el) {
      el.setAttribute("aria-checked", dark ? "true" : "false");
      el.setAttribute(
        "aria-label",
        dark ? "Mudar para modo claro" : "Mudar para modo escuro"
      );
      var sun = el.querySelector('[data-icon="sun"]');
      var moon = el.querySelector('[data-icon="moon"]');
      if (sun) sun.classList.toggle("is-active", !dark);
      if (moon) moon.classList.toggle("is-active", dark);
    });
    try {
      document.dispatchEvent(
        new CustomEvent("dong-ui-themechange", { detail: { mode: mode } })
      );
    } catch (_) {}
  }

  function currentResolved() {
    return resolveMode(getStored());
  }

  function setTheme(preference) {
    if (preference === "system") {
      setStored(null);
      apply(resolveMode(null));
      return;
    }
    if (preference !== "light" && preference !== "dark") return;
    setStored(preference);
    apply(preference);
  }

  function toggle() {
    var next = currentResolved() === "dark" ? "light" : "dark";
    setTheme(next);
    return next;
  }

  function ensureToggleMarkup(el) {
    if (!el || el.getAttribute("data-dong-ready") === "1") return;
    el.classList.add("dong-theme-toggle");
    el.setAttribute("type", el.getAttribute("type") || "button");
    el.setAttribute("role", "switch");
    if (!el.innerHTML.trim()) {
      el.innerHTML =
        '<span class="dong-theme-toggle__track" aria-hidden="true">' +
        '<svg class="dong-theme-toggle__icon" data-icon="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>' +
        '<svg class="dong-theme-toggle__icon" data-icon="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z"/></svg>' +
        '<span class="dong-theme-toggle__knob"></span>' +
        "</span>";
    }
    el.setAttribute("data-dong-ready", "1");
  }

  function bindToggle(el) {
    if (!el) return;
    ensureToggleMarkup(el);
    el.addEventListener("click", function (e) {
      e.preventDefault();
      toggle();
    });
  }

  function initTheme(opts) {
    opts = opts || {};
    apply(currentResolved());

    if (opts.toggleEl) bindToggle(opts.toggleEl);
    document.querySelectorAll("[data-dong-theme-toggle]").forEach(bindToggle);

    if (global.matchMedia) {
      var mq = global.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (getStored() == null) apply(resolveMode(null));
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }

    return {
      get: currentResolved,
      set: setTheme,
      toggle: toggle,
    };
  }

  // Apply ASAP to reduce flash (call again from DOMContentLoaded for toggles)
  try {
    apply(currentResolved());
  } catch (_) {}

  var DongUI = {
    initTheme: initTheme,
    setTheme: setTheme,
    toggleTheme: toggle,
    getTheme: currentResolved,
  };

  global.DongUI = DongUI;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initTheme();
    });
  } else {
    initTheme();
  }
})(typeof window !== "undefined" ? window : globalThis);
