// ─────────────────────────────────────────────
// Bot Panel — Global App JS
// ─────────────────────────────────────────────

// ── Toast Bildirimi ──────────────────────────
function showToast(message, type = 'success') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.style.cssText = 'position:fixed;bottom:24px;right:24px;display:flex;flex-direction:column;gap:8px;z-index:9999';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  container.appendChild(toast);

  // Fade-in
  requestAnimationFrame(() => toast.classList.add('toast-show'));

  setTimeout(() => {
    toast.classList.remove('toast-show');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
  }, 3000);
}

// ── Modal ────────────────────────────────────
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

// Escape tuşu ile modal kapat
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
  }
});

// ── Dashboard: Auto-refresh stats ────────────
setInterval(() => {
  const statsEl = document.getElementById('stat-members');
  if (!statsEl) return;

  fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
      if (data.total_members !== undefined) {
        document.getElementById('stat-members').textContent = data.total_members;
        document.getElementById('stat-tickets').textContent = data.open_tickets;
        document.getElementById('stat-warns').textContent = data.total_warns;
        document.getElementById('stat-balance').textContent = data.total_balance;
        document.getElementById('stat-tags').textContent = data.total_tags;
      }
    })
    .catch(() => {});
}, 30000);

// ── Ayarlar: Ctrl+S kısayolu ─────────────────
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    const form = document.getElementById('settingsForm');
    if (form) form.dispatchEvent(new Event('submit'));
  }
});
