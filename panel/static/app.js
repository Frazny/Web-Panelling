// Bot Panel — Kyzen Style App.js

// Settings form save
const settingsForm = document.getElementById('settingsForm');
if (settingsForm) {
    settingsForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const section = this.dataset.section || 'general';
        const formData = new FormData(this);
        const values = {};
        this.querySelectorAll('input[type="checkbox"]').forEach(cb => { values[cb.name] = false; });
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
                const r = await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cfg) });
                const d = await r.json();
                showToast(d.ok ? 'Kaydedildi!' : 'Hata!', d.ok ? 'success' : 'error');
            } else {
                const r = await fetch('/api/config/section', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({section, values}) });
                const d = await r.json();
                showToast(d.ok ? 'Kaydedildi!' : 'Hata!', d.ok ? 'success' : 'error');
            }
        } catch { showToast('Bağlantı hatası!', 'error'); }
        finally {
            if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Kaydet'; }
        }
    });
}

// Ctrl+S
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        const form = document.getElementById('settingsForm');
        if (form) form.dispatchEvent(new Event('submit'));
    }
});

// Color theme
window.setThemeColor = function(themeName) {
    const gradients = {
        'cyberpunk': { color:'#ff007f', gradient:'linear-gradient(135deg,#ff007f 0%,#00f0ff 100%)', glow:'rgba(255,0,127,0.4)' },
        'sunset': { color:'#ff5e62', gradient:'linear-gradient(135deg,#ff5e62 0%,#ff9966 100%)', glow:'rgba(255,94,98,0.4)' },
        'emerald': { color:'#11998e', gradient:'linear-gradient(135deg,#11998e 0%,#38ef7d 100%)', glow:'rgba(17,153,142,0.4)' },
        'amethyst': { color:'#8a2387', gradient:'linear-gradient(135deg,#8a2387 0%,#e94057 100%)', glow:'rgba(138,35,135,0.4)' },
        'classic': { color:'#5865F2', gradient:'linear-gradient(135deg,#5865F2 0%,#8547FF 100%)', glow:'rgba(88,101,242,0.4)' },
        'toxic': { color:'#00FF87', gradient:'linear-gradient(135deg,#00FF87 0%,#60EFFF 100%)', glow:'rgba(0,255,135,0.4)' }
    };
    const t = gradients[themeName] || gradients['classic'];
    document.documentElement.style.setProperty('--primary-color', t.color);
    document.documentElement.style.setProperty('--primary-gradient', t.gradient);
    document.documentElement.style.setProperty('--primary-glow', t.glow);
    document.documentElement.style.setProperty('--primary-hover', t.color);
    localStorage.setItem('themeColor', themeName);
    document.querySelectorAll('.color-swatch').forEach(s => {
        s.classList.remove('active'); s.style.borderColor = 'transparent';
        if (s.getAttribute('data-theme') === themeName) { s.classList.add('active'); s.style.borderColor = 'white'; }
    });
};

// Backup download
window.downloadBackup = async function() {
    const r = await fetch('/api/config');
    const d = await r.json();
    const blob = new Blob([JSON.stringify(d,null,2)], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'bot_config_backup.json'; a.click();
    showToast('Yedek indirildi!', 'success');
};

window.restoreBackup = async function(input) {
    const file = input.files[0]; if (!file) return;
    const text = await file.text();
    try {
        const data = JSON.parse(text);
        const r = await fetch('/api/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        const d = await r.json();
        if(d.ok){showToast('Ayarlar yüklendi!','success');setTimeout(()=>location.reload(),1500);}
        else showToast('Hata!','error');
    } catch { showToast('Geçersiz JSON dosyası!','error'); }
};
