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
function aiWhatsapp(id, nome) {
  openModal('Mensagem WhatsApp — ' + nome, true);
  fetch('/ai/whatsapp/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) { showError(d.error); return; }
      const msg = d.mensagem || '';
      modalBody.innerHTML = `
        <p class="text-muted text-sm mb-3">Mensagem gerada pela IA Escard. Revise antes de enviar.</p>
        <div class="copy-box" id="waMsgBox">${escHtml(msg)}</div>
        <button class="btn btn-primary" onclick="copyText(document.getElementById('waMsgBox').textContent, this)">
          Copiar mensagem
        </button>`;
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
