/**
 * ValuLens — scan upload page.
 *
 * Shows a local preview of the selected photo and an "Uploading…" state on
 * submit. The page works without JavaScript.
 */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const input = document.querySelector("[data-scan-preview-input]");
        const preview = document.querySelector("[data-scan-preview]");
        const img = document.querySelector("[data-scan-preview-img]");
        const form = document.querySelector("[data-scan-upload-form]");
        let objectUrl = null;

        if (input && preview && img) {
            input.addEventListener("change", function () {
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    objectUrl = null;
                }
                const file = input.files && input.files[0];
                if (!file || !file.type.startsWith("image/")) {
                    preview.hidden = true;
                    return;
                }
                objectUrl = URL.createObjectURL(file);
                img.src = objectUrl;
                preview.hidden = false;
            });
        }

        if (form) {
            form.addEventListener("submit", function () {
                const button = form.querySelector("[data-scan-submit]");
                const status = form.querySelector("[data-scan-uploading]");
                if (button) {
                    button.disabled = true;
                }
                if (status) {
                    status.hidden = false;
                }
            });
        }
    });
})();
