/* Subscription Relay - admin UI helpers (Bootstrap handles the rest). */

function showToast(message, ok = true) {
  const toastEl = document.getElementById('toast');
  const body = document.getElementById('toast-body');
  body.textContent = message;
  toastEl.classList.toggle('text-bg-dark', ok);
  toastEl.classList.toggle('text-bg-danger', !ok);
  bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2500 }).show();
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  if (btn) flashBtn(btn);
}

function flashBtn(btn, text) {
  if (btn.dataset.flashing) return;
  btn.dataset.flashing = '1';
  const orig = btn.textContent;
  btn.textContent = text || '✓ 已复制';
  setTimeout(() => { btn.textContent = orig; delete btn.dataset.flashing; }, 1500);
}

function cardOf(el) { return el.closest('.sub-card'); }

async function apiCall(url, method) {
  const resp = await fetch(url, { method: method || 'POST' });
  if (resp.status === 204) return {};
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new Error((data && (data.detail || data.message)) || ('HTTP ' + resp.status));
  }
  return data;
}

/* ---- index page ---- */

function toggleSource(btn) {
  const card = cardOf(btn);
  const span = card.querySelector('.source-masked');
  const full = card.dataset.sourceFull;
  if (span.dataset.shown === '1') {
    span.textContent = span.dataset.masked;
    span.dataset.shown = '';
    btn.textContent = '显示';
  } else {
    span.dataset.masked = span.textContent;
    span.textContent = full;
    span.dataset.shown = '1';
    btn.textContent = '隐藏';
  }
}

function copyRelay(btn) { copyText(cardOf(btn).dataset.relayUrl, btn); }

function copySource(btn) { copyText(cardOf(btn).dataset.sourceFull, btn); }

function copyCurl(btn) {
  const url = cardOf(btn).dataset.relayUrl;
  copyText('curl -L "' + url + '"', btn);
}

function copyWget(btn) {
  const url = cardOf(btn).dataset.relayUrl;
  copyText('wget -O subscription.txt "' + url + '"', btn);
}

function openSub(btn) { window.open(cardOf(btn).dataset.relayUrl, '_blank'); }

async function testSub(btn) {
  const card = cardOf(btn);
  btn.disabled = true;
  try {
    const data = await apiCall('/api/subscriptions/' + card.dataset.id + '/test');
    showToast(data.message, data.ok);
  } catch (e) {
    showToast('测试失败：' + e.message, false);
  } finally {
    btn.disabled = false;
  }
}

async function refreshSub(btn) {
  const card = cardOf(btn);
  btn.disabled = true;
  try {
    const data = await apiCall('/api/subscriptions/' + card.dataset.id + '/refresh');
    showToast(data.message, data.ok);
    if (data.ok) setTimeout(() => location.reload(), 800);
  } catch (e) {
    showToast(e.message, false);
  } finally {
    btn.disabled = false;
  }
}

async function regenToken(btn) {
  const card = cardOf(btn);
  if (!confirm('重新生成 Token 后，旧中转地址将立即失效，确认继续？')) return;
  btn.disabled = true;
  try {
    const data = await apiCall('/api/subscriptions/' + card.dataset.id + '/regenerate-token');
    card.dataset.relayUrl = data.relay_url;
    const row = card.querySelector('.relay-url');
    if (row) row.textContent = data.relay_url;
    showToast('Token 已重新生成，旧地址已失效');
  } catch (e) {
    showToast('生成失败：' + e.message, false);
  } finally {
    btn.disabled = false;
  }
}

async function deleteSub(btn) {
  const card = cardOf(btn);
  if (!confirm('确认删除该订阅？缓存和状态记录将一并清除。')) return;
  btn.disabled = true;
  try {
    await apiCall('/api/subscriptions/' + card.dataset.id, 'DELETE');
    card.remove();
    showToast('已删除');
  } catch (e) {
    showToast('删除失败：' + e.message, false);
    btn.disabled = false;
  }
}

/* ---- edit page ---- */

function genToken(btn) {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let bin = '';
  bytes.forEach(b => { bin += String.fromCharCode(b); });
  const token = btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  btn.closest('.input-group').querySelector('input').value = token;
  flashBtn(btn, '✓ 已生成');
}

function toggleUaMode(select) {
  document.getElementById('ua-fixed-wrap').style.display =
    select.value === 'fixed' ? '' : 'none';
}

function saveSub(form) {
  const subId = form.dataset.subId;
  const fd = new FormData(form);
  const payload = {
    name: (fd.get('name') || '').trim(),
    source_url: (fd.get('source_url') || '').trim(),
    access_token: (fd.get('access_token') || '').trim(),
    enabled: fd.get('enabled') === 'on',
    cache_ttl: fd.get('cache_ttl') ? parseInt(fd.get('cache_ttl'), 10) : null,
    user_agent_mode: fd.get('user_agent_mode') || null,
    user_agent: (fd.get('user_agent') || '').trim() || null,
  };
  const errBox = document.getElementById('form-error');
  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;

  let url = '/api/subscriptions';
  let method = 'POST';
  if (!subId) {
    payload.id = (fd.get('id') || '').trim() || null;
  } else {
    url += '/' + subId;
    method = 'PUT';
  }

  fetch(url, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(async resp => {
    if (!resp.ok) {
      const data = await resp.json().catch(() => null);
      const detail = data && data.detail;
      const msg = Array.isArray(detail)
        ? detail.map(d => d.msg).join('；')
        : (detail || ('HTTP ' + resp.status));
      throw new Error(msg);
    }
    location.href = '/admin';
  }).catch(e => {
    errBox.textContent = e.message;
    errBox.classList.remove('d-none');
    submitBtn.disabled = false;
  });
  return false;
}
