(function () {
  'use strict';

  var showPasswordToggles = document.querySelectorAll('[data-show-password]');
  showPasswordToggles.forEach(function (toggle) {
    toggle.addEventListener('change', function () {
      var input = document.getElementById('id_password');
      if (!input) return;
      input.type = toggle.checked ? 'text' : 'password';
    });
  });

  var rejectOverlay = document.querySelector('[data-reject-overlay]');
  var openButtons = document.querySelectorAll('[data-open-reject]');
  if (rejectOverlay && typeof rejectOverlay.showModal === 'function') {
    openButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        rejectOverlay.showModal();
        var reason = rejectOverlay.querySelector('#rejection_reason');
        if (reason) {
          reason.classList.remove('is-invalid');
          reason.parentElement.classList.remove('is-invalid');
        }
      });
    });
    rejectOverlay.querySelectorAll('[data-close-reject]').forEach(function (button) {
      button.addEventListener('click', function () { rejectOverlay.close(); });
    });
    rejectOverlay.querySelector('form').addEventListener('submit', function () {
      var reason = rejectOverlay.querySelector('#rejection_reason');
      if (reason) {
        var invalid = reason.value.trim().length === 0;
        reason.classList.toggle('is-invalid', invalid);
        reason.parentElement.classList.toggle('is-invalid', invalid);
        if (invalid) { event.preventDefault(); }
      }
    });
    rejectOverlay.addEventListener('click', function (e) {
      if (e.target === rejectOverlay) rejectOverlay.close();
    });
  }
})();
