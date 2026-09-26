function animateNumber(element, from, to) {
    const goingUp = to > from;
    const duration = 300;

    element.style.transition = `transform ${duration}ms ease, opacity ${duration}ms ease`;
    element.style.transform = goingUp ? 'translateY(-10px)' : 'translateY(10px)';
    element.style.opacity = '0';

    setTimeout(function () {
        element.style.transition = 'none';
        element.textContent = to;
        element.style.transform = goingUp ? 'translateY(10px)' : 'translateY(-10px)';

        void element.offsetWidth;

        element.style.transition = `transform ${duration}ms ease, opacity ${duration}ms ease`;
        element.style.transform = 'translateY(0)';
        element.style.opacity = '1';
    }, duration);
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.check').forEach(function (checkbox) {
        checkbox.addEventListener('change', function () {
            const habitId = parseInt(this.dataset.habitId);
            const checked = this.checked;
            const row = this.closest('.row');
            const tag = row.querySelector('.tag');
            const isBad = row.classList.contains('bad');

            const currentEl = document.getElementById('current-points');
            const lifetimeEl = document.getElementById('lifetime-points');
            const oldCurrent = parseInt(currentEl.textContent);
            const oldLifetime = parseInt(lifetimeEl.textContent);

            fetch('/toggle-checkin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ habit_id: habitId, checked: checked })
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.current_points !== oldCurrent) {
                        animateNumber(currentEl, oldCurrent, data.current_points);
                    }
                    if (data.lifetime_points !== oldLifetime) {
                        animateNumber(lifetimeEl, oldLifetime, data.lifetime_points);
                    }
                    const atRisk = isBad ? checked : !checked;
                    tag.classList.toggle('at-risk', atRisk);
                });
        });
    });
});