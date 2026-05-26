/* main.js -- Soporte FTTH Turnos v5 */

/* ============================================================
   INLINE SHIFT EDITING (schedule weekly view)
   ============================================================ */
function updateShift(daId, shift, btn) {
  fetch('/api/assignment/' + daId + '/shift', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({shift: shift, reason: 'Edicion manual'})
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) { showToast('Error: ' + data.error, 'danger'); return; }
    // Update badge in the weekly schedule view
    var wrap = btn ? btn.closest('.cell-badge') : null;
    if (wrap) {
      var shiftColors = {
        'T1':'#3b82f6','T2':'#10b981','D':'#8b5cf6','DESC':'#6b7280',
        'EPS':'#ef4444','V':'#f59e0b','PERM':'#f97316','CAL':'#dc2626',
        'INCAP':'#b91c1c','CAP':'#06b6d4','LIC':'#a855f7','AUS':'#ec4899','OTRO':'#9ca3af'
      };
      wrap.style.background = shiftColors[shift] || '#9ca3af';
      var label = wrap.querySelector('.shift-label');
      if (label) label.textContent = shift;
    }
    showToast('Turno actualizado: ' + shift, 'success');
  })
  .catch(function(e) { showToast('Error de red', 'danger'); });
}

function toggleTicket(daId, btn) {
  fetch('/api/assignment/' + daId + '/ticket', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'}
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) { showToast('Error: ' + data.error, 'danger'); return; }
    var cell = btn ? btn.closest('td') : null;
    if (cell) {
      var icon = cell.querySelector('.bi-ticket-detailed, .bi-ticket');
      if (data.is_ticket && !icon) {
        var i = document.createElement('i');
        i.className = 'bi bi-ticket-detailed ms-1';
        i.style.color = '#d97706';
        cell.querySelector('.cell-badge').appendChild(i);
      } else if (!data.is_ticket && icon) {
        icon.remove();
      }
    }
    showToast(data.is_ticket ? 'Marcado como ticket' : 'Ticket removido', 'info');
  })
  .catch(function(e) { showToast('Error de red', 'danger'); });
}

/* ============================================================
   TOAST NOTIFICATION
   ============================================================ */
function showToast(msg, type) {
  var existing = document.getElementById('ftth-toast');
  if (existing) existing.remove();

  var colors = {success:'#10b981', danger:'#ef4444', info:'#3b82f6', warning:'#f59e0b'};
  var toast = document.createElement('div');
  toast.id = 'ftth-toast';
  toast.style.cssText = [
    'position:fixed', 'bottom:20px', 'right:20px', 'z-index:9999',
    'background:' + (colors[type] || '#374151'),
    'color:#fff', 'padding:8px 14px', 'border-radius:8px',
    'font-size:.8rem', 'font-weight:600',
    'box-shadow:0 4px 12px rgba(0,0,0,.2)',
    'transition:opacity .3s', 'max-width:300px'
  ].join(';');
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function() {
    toast.style.opacity = '0';
    setTimeout(function() { toast.remove(); }, 350);
  }, 2500);
}

/* ============================================================
   SIDEBAR KEYBOARD SHORTCUT
   ============================================================ */
document.addEventListener('keydown', function(e) {
  if (e.key === 'b' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    var btn = document.querySelector('.topbar-toggle');
    if (btn) btn.click();
  }
});

/* ============================================================
   AUTO-DISMISS FLASH ALERTS
   ============================================================ */
document.addEventListener('DOMContentLoaded', function() {
  var alerts = document.querySelectorAll('.alert-dismissible.fade.show');
  alerts.forEach(function(al) {
    setTimeout(function() {
      var bsAlert = bootstrap && bootstrap.Alert ? new bootstrap.Alert(al) : null;
      if (bsAlert) bsAlert.close();
    }, 5000);
  });
});
