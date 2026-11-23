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

  var revokeOverlay = document.querySelector('[data-revoke-lender-overlay]');
  var openRevokeButtons = document.querySelectorAll('[data-open-revoke-lender]');
  if (revokeOverlay && typeof revokeOverlay.showModal === 'function') {
    openRevokeButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        var actionUrl = button.getAttribute('data-action-url');
        var userName = button.getAttribute('data-user-name');
        var form = revokeOverlay.querySelector('form');
        if (form && actionUrl) {
          form.action = actionUrl;
        }
        var targetEl = revokeOverlay.querySelector('[data-revoke-target-name]');
        if (targetEl && userName) {
          targetEl.textContent = '“' + userName + '”';
        }
        var reason = revokeOverlay.querySelector('#revoke_lender_reason');
        if (reason) {
          reason.selectedIndex = 0;
          reason.classList.remove('is-invalid');
          if (reason.parentElement) {
            reason.parentElement.classList.remove('is-invalid');
          }
        }
        var detail = revokeOverlay.querySelector('#revoke_lender_detail');
        if (detail) {
          detail.value = '';
        }
        revokeOverlay.showModal();
      });
    });
    revokeOverlay.querySelectorAll('[data-close-revoke]').forEach(function (button) {
      button.addEventListener('click', function () { revokeOverlay.close(); });
    });
    var revokeForm = revokeOverlay.querySelector('form');
    if (revokeForm) {
      revokeForm.addEventListener('submit', function (event) {
        var reason = revokeOverlay.querySelector('#revoke_lender_reason');
        if (reason) {
          var invalid = !reason.value || reason.value.trim().length === 0;
          reason.classList.toggle('is-invalid', invalid);
          if (reason.parentElement) {
            reason.parentElement.classList.toggle('is-invalid', invalid);
          }
          if (invalid) { event.preventDefault(); }
        }
      });
    }
    revokeOverlay.addEventListener('click', function (e) {
      if (e.target === revokeOverlay) revokeOverlay.close();
    });
  }

  var systemTimeEl = document.getElementById('system-time');
  if (systemTimeEl) {
    var updateClock = function () {
      var now = new Date();
      var options = {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Asia/Manila'
      };
      try {
        var formatted = new Intl.DateTimeFormat('en-US', options).format(now);
        systemTimeEl.textContent = formatted + ' (PHT)';
        systemTimeEl.setAttribute('datetime', now.toISOString());
      } catch (e) {
        // Fallback
      }
    };
    setInterval(updateClock, 30000);
  }
})();
