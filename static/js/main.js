/* ============================================================
   SOPORTE FTTH -- main.js  (Alpine.js helpers + inline edit)
   ============================================================ */

/* scheduleEditor: Alpine component registered globally */
document.addEventListener('alpine:init', function () {
  Alpine.data('scheduleEditor', function (isLocked) {
    return {
      locked: isLocked,
    };
  });
});

/* ---- updateShift -------------------------------------------
   Called from the shift-picker dropdown.
   Sends PATCH /api/assignment/<id>/shift  { shift: "T2" }
   Then updates the badge in the DOM without page reload.
   ----------------------------------------------------------- */
function updateShift(assignmentId, newShift, btnEl) {
  fetch('/api/assignment/' + assignmentId + '/shift', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shift: newShift }),
  })
  .then(function (r) {
    if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || r.status); });
    return r.json();
  })
  .then(function (data) {
    /* Find the cell container (td) */
    var td = btnEl.closest('td');
    if (!td) return;

    /* Update badge color + text */
    var badge = td.querySelector('.badge');
    if (badge) {
      badge.textContent = data.shift;
      badge.style.backgroundColor = data.color;
    }

    /* Update cell background tint */
    td.style.backgroundColor = data.color + '18';

    /* Ticket icon */
    var ticketIcon = td.querySelector('.bi-ticket-detailed');
    if (data.is_ticket && !ticketIcon) {
      var icon = document.createElement('i');
      icon.className = 'bi bi-ticket-detailed text-warning d-block';
      icon.style.fontSize = '.6rem';
      var cellBadge = td.querySelector('.cell-badge');
      if (cellBadge) cellBadge.appendChild(icon);
    } else if (!data.is_ticket && ticketIcon) {
      ticketIcon.remove();
    }

    /* Manual edit indicator */
    var manualIcon = td.querySelector('.bi-pencil-fill');
    if (data.is_manual && !manualIcon) {
      var pen = document.createElement('i');
      pen.className = 'bi bi-pencil-fill text-info';
      pen.style.fontSize = '.55rem';
      var cellBadge2 = td.querySelector('.cell-badge');
      if (cellBadge2) cellBadge2.appendChild(pen);
    }

    showToast('Turno actualizado: ' + data.shift, 'success');
  })
  .catch(function (err) {
    showToast('Error: ' + err.message, 'danger');
  });
}

/* ---- toggleTicket ------------------------------------------
   Called from the shift-picker to flip is_ticket flag.
   ----------------------------------------------------------- */
function toggleTicket(assignmentId, btnEl) {
  fetch('/api/assignment/' + assignmentId + '/ticket', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  .then(function (r) {
    if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || r.status); });
    return r.json();
  })
  .then(function (data) {
    var td = btnEl.closest('td');
    if (!td) return;
    var ticketIcon = td.querySelector('.bi-ticket-detailed');
    if (data.is_ticket && !ticketIcon) {
      var icon = document.createElement('i');
      icon.className = 'bi bi-ticket-detailed text-warning d-block';
      icon.style.fontSize = '.6rem';
      var cellBadge = td.querySelector('.cell-badge');
      if (cellBadge) cellBadge.appendChild(icon);
    } else if (!data.is_ticket && ticketIcon) {
      ticketIcon.remove();
    }
    showToast(data.is_ticket ? 'Ticket asignado' : 'Ticket quitado', 'info');
  })
  .catch(function (err) {
    showToast('Error: ' + err.message, 'danger');
  });
}

/* ---- showToast ---------------------------------------------
   Lightweight toast notification (no Bootstrap toast needed).
   ----------------------------------------------------------- */
function showToast(message, type) {
  var container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = [
      'position:fixed', 'bottom:20px', 'right:20px',
      'z-index:9999', 'display:flex', 'flex-direction:column', 'gap:8px'
    ].join(';');
    document.body.appendChild(container);
  }

  var colors = {
    success: '#10b981', danger: '#ef4444',
    info: '#3b82f6', warning: '#f59e0b'
  };

  var toast = document.createElement('div');
  toast.style.cssText = [
    'padding:10px 16px',
    'border-radius:8px',
    'background:' + (colors[type] || '#374151'),
    'color:#fff',
    'font-size:.82rem',
    'box-shadow:0 4px 12px rgba(0,0,0,.2)',
    'opacity:0',
    'transition:opacity .2s',
    'max-width:280px'
  ].join(';');
  toast.textContent = message;
  container.appendChild(toast);

  /* Fade in */
  requestAnimationFrame(function () {
    requestAnimationFrame(function () { toast.style.opacity = '1'; });
  });

  /* Auto remove */
  setTimeout(function () {
    toast.style.opacity = '0';
    setTimeout(function () { toast.remove(); }, 250);
  }, 3000);
}
