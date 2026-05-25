// main.js — Sistema de Horarios Soporte Técnico

// ── Auto-dismiss alerts ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss success alerts after 4s
  document.querySelectorAll('.alert-success').forEach(el => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      bsAlert.close();
    }, 4000);
  });

  // Loading spinner on form submit
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function() {
      const btn = this.querySelector('[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Procesando...`;
      }
    });
  });

  // Highlight current day column in schedule table
  const today = new Date();
  const todayFmt = `${String(today.getDate()).padStart(2,'0')}/${String(today.getMonth()+1).padStart(2,'0')}`;
  document.querySelectorAll('.schedule-table th small').forEach(el => {
    if (el.textContent.trim() === todayFmt) {
      const th = el.closest('th');
      if (th) th.classList.add('table-warning');
    }
  });

  // Tooltips
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipTriggerList.forEach(el => new bootstrap.Tooltip(el));
});

// ── Confirm dangerous actions ───────────────────────────────────────────────
function confirmAction(msg) {
  return confirm(msg || '¿Estás seguro?');
}

// ── Copy table to clipboard ─────────────────────────────────────────────────
function copyScheduleTable() {
  const table = document.querySelector('.schedule-table');
  if (!table) return;
  const range = document.createRange();
  range.selectNode(table);
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(range);
  document.execCommand('copy');
  window.getSelection().removeAllRanges();
  alert('Tabla copiada al portapapeles ✅');
}

// ── Print schedule ──────────────────────────────────────────────────────────
function printSchedule() {
  window.print();
}
