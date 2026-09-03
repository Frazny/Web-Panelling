// ═══════════════════════════════════════════════
//  Bot Panel — Premium App JS v2.0
// ═══════════════════════════════════════════════

// ── Toast ────────────────────────────────────────
function showToast(message, type = 'success') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    document.body.appendChild(container);
  }

  const icons = { success: '✅', error: '❌', warning: '⚠️' };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${icons[type] || '💬'}</span><span>${message}</span>`;
  container.appendChild(toast);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add('toast-show'));
  });

  setTimeout(() => {
    toast.classList.remove('toast-show');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
  }, 3200);
}

// ── Modal ─────────────────────────────────────────
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.style.animation = 'fadeIn .2s ease reverse';
    setTimeout(() => { el.style.display = 'none'; el.style.animation = ''; }, 180);
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal').forEach(m => {
      if (m.style.display !== 'none') closeModal(m.id);
    });
  }
});

// ── Ctrl+S kaydet ─────────────────────────────────
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    const form = document.getElementById('settingsForm');
    if (form) form.dispatchEvent(new Event('submit'));
  }
});

// ── Ripple effect on buttons ──────────────────────
document.addEventListener('click', e => {
  const btn = e.target.closest('.btn');
  if (!btn) return;
  const rect = btn.getBoundingClientRect();
  const ripple = document.createElement('span');
  const size = Math.max(rect.width, rect.height);
  ripple.style.cssText = `
    position:absolute; border-radius:50%; pointer-events:none;
    width:${size}px; height:${size}px;
    left:${e.clientX - rect.left - size/2}px;
    top:${e.clientY - rect.top - size/2}px;
    background:rgba(255,255,255,0.15);
    transform:scale(0); animation:rippleAnim .5s ease;
  `;
  if (!document.getElementById('ripple-style')) {
    const s = document.createElement('style');
    s.id = 'ripple-style';
    s.textContent = '@keyframes rippleAnim{to{transform:scale(2.5);opacity:0}}';
    document.head.appendChild(s);
  }
  btn.style.position = 'relative';
  btn.style.overflow = 'hidden';
  btn.appendChild(ripple);
  setTimeout(() => ripple.remove(), 500);
});

// ── Intersection Observer — fade-in cards ─────────
const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'translateY(0)';
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.card, .stat-card, .cog-card').forEach(el => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(16px)';
  el.style.transition = 'opacity .4s ease, transform .4s ease';
  observer.observe(el);
});

// ── Settings form ─────────────────────────────────
const settingsForm = document.getElementById('settingsForm');
if (settingsForm) {
  settingsForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    const section = this.dataset.section || 'general';
    const formData = new FormData(this);
    const values = {};

    // Önce tüm checkbox'ları false olarak işaretle
    this.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      values[cb.name] = false;
    });

    for (const [key, val] of formData.entries()) {
      const input = this.querySelector(`[name="${key}"]`);
      if (input?.type === 'checkbox') values[key] = true;
      else if (input?.type === 'number') values[key] = Number(val);
      else values[key] = val;
    }

    const submitBtn = this.querySelector('[type="submit"]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = '⏳ Kaydediliyor...'; }

    try {
      if (section === 'general') {
        const cfg = await fetch('/api/config').then(r => r.json());
        Object.assign(cfg, values);
        const r = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(cfg),
        });
        const d = await r.json();
        showToast(d.ok ? '✅ Kaydedildi!' : '❌ Hata!', d.ok ? 'success' : 'error');
      } else {
        const r = await fetch('/api/config/section', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ section, values }),
        });
        const d = await r.json();
        showToast(d.ok ? '✅ Kaydedildi!' : '❌ Hata!', d.ok ? 'success' : 'error');
      }
    } catch {
      showToast('❌ Bağlantı hatası!', 'error');
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Kaydet'; }
    }
  });
}
