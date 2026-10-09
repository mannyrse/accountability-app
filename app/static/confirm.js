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