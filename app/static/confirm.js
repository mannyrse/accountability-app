document.addEventListener("submit", function (e) {
    var form = e.target;
    var message = form.dataset && form.dataset.confirm;
    if (!message) return;

    if (!window.confirm(message)) {
        e.preventDefault();
        return;
    }

    // Prevent a double-tap from redeeming twice
    var button = form.querySelector("button[type=submit]");
    if (button) button.disabled = true;
});

// Links with data-confirm (e.g. delete buttons) ask first and only follow if confirmed
document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a[data-confirm]");
    if (!link) return;

    if (!window.confirm(link.dataset.confirm)) {
        e.preventDefault();
    }
});