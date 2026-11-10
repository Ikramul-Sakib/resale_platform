/**
 * ValuLens — Base JavaScript
 *
 * Minimal JS: theme toggle, alert auto-dismiss, and utility functions.
 * No framework dependencies.
 */

(function () {
    "use strict";

    // -------------------------------------------------------------------------
    // Theme Toggle (persists to localStorage)
    // -------------------------------------------------------------------------
    const THEME_KEY = "valulens:theme";

    function getStoredTheme() {
        try {
            return localStorage.getItem(THEME_KEY);
        } catch (e) {
            return null;
        }
    }

    function setTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        try {
            localStorage.setItem(THEME_KEY, theme);
        } catch (e) {
            // localStorage unavailable — silent fail
        }
    }

    // Apply stored theme on load
    const stored = getStoredTheme();
    if (stored === "light" || stored === "dark") {
        setTheme(stored);
    }

    // Expose toggle for future use (e.g., a theme button)
    window.ValuLens = window.ValuLens || {};
    window.ValuLens.toggleTheme = function () {
        const current = document.documentElement.getAttribute("data-theme") || "dark";
        setTheme(current === "dark" ? "light" : "dark");
    };

    // -------------------------------------------------------------------------
    // Auto-dismiss alerts after 8 seconds
    // -------------------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", function () {
        const alerts = document.querySelectorAll(".alert");
        alerts.forEach(function (alert) {
            setTimeout(function () {
                alert.style.transition = "opacity 300ms ease";
                alert.style.opacity = "0";
                setTimeout(function () { alert.remove(); }, 300);
            }, 8000);
        });
    });

})();
