/* ── Modal ──────────────────────────────────────────────────────────────────── */
const modal        = document.getElementById('aiModal');
const modalTitle   = document.getElementById('modalTitle');
const modalBody    = document.getElementById('modalBody');

function openModal(title, loading = false) {
  modalTitle.textContent = title;
  if (loading) {
    modalBody.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>Consultando IA Escard…</p>
      </div>`;
  }
  modal.classList.add('open');
}

function closeModal() {
  modal.classList.remove('open');
}

function showError(msg) {
  modalBody.innerHTML = `<div class="alert alert-danger">⚠ ${msg}</div>`;
}

modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ── Clipboard ──────────────────────────────────────────────────────────────── */
function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = '✓ Copiado!';
    btn.style.background = '#16A34A';
    setTimeout(() => { btn.textContent = orig; btn.style.background = ''; }, 2200);
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  });
}

/* ── Helpers para modais de WA / Email ──────────────────────────────────────── */
let _modalWaUrl   = '';
let _modalMailUrl = '';

function _openWa()   { if (_modalWaUrl)   window.open(_modalWaUrl, 'whatsapp_escard'); }
function _openMail() { if (_modalMailUrl) window.location.href = _modalMailUrl; }

function _copiarMsg(elId, btn) {
  const el   = document.getElementById(elId);
  const text = el ? (el.value !== undefined ? el.value : el.textContent) : '';
  const done = () => {
    const orig = btn.textContent;
    btn.textContent = '✅ Copiado!';
    setTimeout(() => { btn.textContent = orig; }, 2000);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(done).catch(() => {
      if (el && el.select) { el.select(); document.execCommand('copy'); done(); }
    });
  } else if (el && el.select) { el.select(); document.execCommand('copy'); done(); }
}

function _copiarEmail(subjId, bodyId, btn) {
  const s = (document.getElementById(subjId)?.value || '').trim();
  const b = (document.getElementById(bodyId)?.value  || '').trim();
  const done = () => {
    const orig = btn.textContent;
    btn.textContent = '✅ Copiado!';
    setTimeout(() => { btn.textContent = orig; }, 2000);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText('Assunto: ' + s + '\n\n' + b).then(done);
  }
}

/* ── AI: Score do Lead ───────────────────────────────────────────────────────── */
function aiScore(id, nome) {
  openModal('Score do Lead — ' + nome, true);
  fetch('/ai/score/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) { showError(d.error); return; }
      const s = d.score;
      const cls = s >= 70 ? 'score-high' : s >= 40 ? 'score-mid' : 'score-low';
      const lbl = s >= 70 ? 'Lead quente' : s >= 40 ? 'Potencial médio' : 'Lead frio';
      const fortes = (d.pontos_fortes || []).map(p => `<li>${p}</li>`).join('');
      const fracos  = (d.pontos_fracos  || []).map(p => `<li>${p}</li>`).join('');
      modalBody.innerHTML = `
        <div class="score-ring ${cls}">${s}</div>
        <p class="score-label">${lbl}</p>
        <p style="margin-bottom:12px">${d.justificativa}</p>
        ${fortes ? `<p class="fw-600 mb-2">Pontos fortes</p><ul style="padding-left:18px;margin-bottom:12px">${fortes}</ul>` : ''}
        ${fracos  ? `<p class="fw-600 mb-2">Atenção</p><ul style="padding-left:18px">${fracos}</ul>`  : ''}`;
    })
    .catch(e => showError(e.message));
}

/* ── AI: Mensagem WhatsApp ───────────────────────────────────────────────────── */
const _WA_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>`;

function aiWhatsapp(id, nome, telefone) {
  openModal('Mensagem WhatsApp — ' + nome, true);
  fetch('/ai/whatsapp/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) { showError(d.error); return; }
      const msg = d.mensagem || '';
      const tel = (telefone || '').replace(/\D/g, '');
      _modalWaUrl = tel ? `https://wa.me/55${tel}?text=${encodeURIComponent(msg)}` : '';
      modalBody.innerHTML = `
        <p class="text-muted text-sm mb-3">Mensagem gerada pela IA Escard. Revise antes de enviar.</p>
        <textarea id="waMsgBox" rows="7"
          style="width:100%;padding:12px;border:1px solid var(--border);border-radius:6px;font-size:13px;line-height:1.6;resize:vertical;font-family:inherit;color:var(--text)">${escHtml(msg)}</textarea>
        <div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap">
          <button onclick="_copiarMsg('waMsgBox',this)"
            style="background:#6c757d;color:#fff;padding:10px 20px;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-family:inherit">📋 Copiar</button>
          ${_modalWaUrl ? `<button onclick="_openWa()"
            style="background:#25D366;color:#fff;padding:10px 20px;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-family:inherit">📱 Abrir WhatsApp</button>` : ''}
        </div>`;
    })
    .catch(e => showError(e.message));
}

/* ── AI: Próxima Ação ───────────────────────────────────────────────────────── */
function aiProximaAcao(id, titulo) {
  openModal('Próxima ação — ' + titulo, true);
  fetch('/ai/proxima-acao/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) { showError(d.error); return; }
      const urgCls = 'urgency-' + (d.urgencia || 'media');
      modalBody.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <span class="urgency-badge ${urgCls}">${(d.urgencia || 'media').toUpperCase()}</span>
          <span class="text-muted text-sm">Prazo: <strong>${d.prazo || '—'}</strong></span>
        </div>
        <p style="font-size:15px;font-weight:600;margin-bottom:10px">${escHtml(d.acao || '')}</p>
        ${d.motivo ? `<p class="text-muted text-sm">${escHtml(d.motivo)}</p>` : ''}`;
    })
    .catch(e => showError(e.message));
}

/* ── Kanban drag-and-drop ───────────────────────────────────────────────────── */
let dragId = null;

function onDragStart(e, id) {
  dragId = id;
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragEnd(e) {
  e.currentTarget.classList.remove('dragging');
  document.querySelectorAll('.kanban-col').forEach(c => c.classList.remove('drag-over'));
}

function onDragOver(e) {
  e.preventDefault();
  e.currentTarget.closest('.kanban-col').classList.add('drag-over');
}

function onDragLeave(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) {
    e.currentTarget.classList.remove('drag-over');
  }
}

function onDrop(e, estagio) {
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');
  if (!dragId) return;
  fetch(`/oportunidades/${dragId}/mover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ estagio }),
  })
    .then(r => r.json())
    .then(d => { if (d.ok) location.reload(); else alert('Erro: ' + d.error); })
    .catch(err => alert('Erro de rede: ' + err.message));
}

/* ── Util ───────────────────────────────────────────────────────────────────── */
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ── Auto-dismiss alerts ─────────────────────────────────────────────────────── */
document.querySelectorAll('.alert').forEach(el => {
  setTimeout(() => { el.style.transition = 'opacity .5s'; el.style.opacity = '0';
    setTimeout(() => el.remove(), 500); }, 4000);
});
