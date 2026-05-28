/* ── Utility ──────────────────────────────────────────── */
function $(sel, ctx = document) { return ctx.querySelector(sel); }
function $$(sel, ctx = document) { return [...ctx.querySelectorAll(sel)]; }
function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }
function escape(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function toast(msg, ms = 2800) {
  const t = $('#toast');
  t.textContent = msg;
  show(t);
  setTimeout(() => hide(t), ms);
}

/* ── Tabs ─────────────────────────────────────────────── */
$$('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.tab').forEach(t => t.classList.remove('active'));
    $$('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`#panel-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'dict' && !$('.dict-category')) loadDict();
  });
});


/* ── Character counter ────────────────────────────────── */
const spellInput = $('#spell-input');
const spellCount = $('#spell-count');
spellInput.addEventListener('input', () => {
  const n = spellInput.value.length;
  spellCount.textContent = `${n} / 3000자`;
  spellCount.style.color = n > 2700 ? 'var(--red)' : '';
});

/* ── Spell check ──────────────────────────────────────── */
$('#spell-btn').addEventListener('click', async () => {
  const text = spellInput.value.trim();
  if (!text) { toast('텍스트를 입력해주세요.'); return; }

  const btn = $('#spell-btn');
  btn.disabled = true;
  btn.textContent = '교정 중…';
  hide($('#spell-result'));

  try {
    const res = await fetch('/api/spell-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      renderSpellError(data.error || '알 수 없는 오류');
      return;
    }
    renderSpellResult(data);
  } catch (e) {
    renderSpellError('서버에 연결할 수 없습니다.');
  } finally {
    btn.disabled = false;
    btn.textContent = '맞춤법 교정하기';
  }
});

$('#spell-clear').addEventListener('click', () => {
  spellInput.value = '';
  spellCount.textContent = '0 / 500자';
  hide($('#spell-result'));
});

function renderSpellResult(data) {
  const summary   = $('#spell-summary');
  const corrWrap  = $('#spell-corrections-wrap');
  const corrEl    = $('#spell-corrections');
  const rawEl     = $('#spell-raw');
  const resultEl  = $('#spell-result');

  // Summary banner — 교정 제안 수 기준으로 판단
  const engineBadge = data.engine ? `<span class="engine-badge">${escape(data.engine)}</span>` : '';
  const count = (data.corrections || []).length;
  if (count > 0) {
    summary.className = 'result-card errors';
    summary.innerHTML = `⚠️ <span>${count}개의 교정 제안이 있습니다. ${engineBadge}</span>`;
  } else {
    summary.className = 'result-card ok';
    summary.innerHTML = `✅ <span>맞춤법 오류가 발견되지 않았습니다. ${engineBadge}</span>`;
  }

  // Corrections
  if (data.corrections && data.corrections.length) {
    corrEl.innerHTML = data.corrections.map(c =>
      `<div class="correction-item" style="flex-direction:column;align-items:flex-start;gap:.3rem">
        <div style="display:flex;align-items:center;gap:.75rem">
          <span class="orig">${escape(c.original)}</span>
          <span class="arrow">→</span>
          <span class="sugg">${escape(c.suggestion)}</span>
        </div>
        ${c.rule ? `<div class="correction-rule">${escape(c.rule)}</div>` : ''}
      </div>`
    ).join('');
    show(corrWrap);
  } else {
    hide(corrWrap);
  }

  // Raw output
  rawEl.textContent = data.raw || '(출력 없음)';

  show(resultEl);
  resultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderSpellError(msg) {
  const summary  = $('#spell-summary');
  const resultEl = $('#spell-result');
  summary.className = 'result-card errors';
  summary.innerHTML = `❌ <span>${escape(msg)}</span>`;
  hide($('#spell-corrections-wrap'));
  $('#spell-raw').textContent = '';
  show(resultEl);
}

/* ── Foreign word conversion ──────────────────────────── */
$('#foreign-btn').addEventListener('click', async () => {
  const text = $('#foreign-input').value.trim();
  if (!text) { toast('텍스트를 입력해주세요.'); return; }

  const btn = $('#foreign-btn');
  btn.disabled = true;
  btn.textContent = '순화 중…';
  hide($('#foreign-result'));

  try {
    const res = await fetch('/api/foreign-convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      toast(data.error || '오류 발생'); return;
    }
    renderForeignResult(data);
  } catch {
    toast('서버에 연결할 수 없습니다.');
  } finally {
    btn.disabled = false;
    btn.textContent = '외래어 순화하기';
  }
});

$('#foreign-clear').addEventListener('click', () => {
  $('#foreign-input').value = '';
  hide($('#foreign-result'));
});

function highlightForeignWords(text, changes) {
  let result = escape(text);
  changes.forEach(({ from }) => {
    const re = new RegExp(escapeRegex(from), 'g');
    result = result.replace(re, `<mark>${from}</mark>`);
  });
  return result;
}

function highlightConverted(text, changes) {
  let result = escape(text);
  changes.forEach(({ to }) => {
    const re = new RegExp(escapeRegex(to), 'g');
    result = result.replace(re, `<span class="replaced">${to}</span>`);
  });
  return result;
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function renderForeignResult(data) {
  const { original, converted, changes, change_count } = data;

  const summary = $('#foreign-summary');
  if (change_count > 0) {
    summary.className = 'result-card info';
    summary.innerHTML = `🔄 <span>${change_count}개의 외래어를 한국어로 순화했습니다.</span>`;
  } else {
    summary.className = 'result-card ok';
    summary.innerHTML = `✅ <span>순화할 외래어가 발견되지 않았습니다.</span>`;
  }

  $('#foreign-before').innerHTML = highlightForeignWords(original, changes);
  $('#foreign-after').innerHTML  = highlightConverted(converted, changes);

  const changesEl = $('#foreign-changes');
  if (changes.length) {
    changesEl.innerHTML = `
      <table class="change-table">
        <thead><tr><th>외래어</th><th></th><th>순화어 (국립국어원)</th></tr></thead>
        <tbody>${changes.map(c =>
          `<tr>
            <td class="from-cell">${escape(c.from)}</td>
            <td class="arrow">→</td>
            <td class="to-cell">${escape(c.to)}</td>
          </tr>`).join('')}
        </tbody>
      </table>`;
  } else {
    changesEl.innerHTML = '<p style="color:var(--gray-400);font-size:.875rem">변환된 항목이 없습니다.</p>';
  }

  show($('#foreign-result'));
  $('#foreign-result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ── Dictionary tab ───────────────────────────────────── */
let dictData = null;

async function loadDict() {
  if (dictData) { renderDict(dictData); return; }
  try {
    const r = await fetch('/api/foreign-words');
    dictData = await r.json();
    renderDict(dictData);
  } catch {
    $('#dict-content').innerHTML = '<p style="color:var(--red)">사전을 불러올 수 없습니다.</p>';
  }
}

function renderDict(data) {
  const container = $('#dict-content');
  let html = '';
  for (const [cat, entries] of Object.entries(data)) {
    const rows = Object.entries(entries);
    if (!rows.length) continue;
    html += `<div class="dict-category">
      <div class="dict-category-title">${escape(cat)}</div>
      ${rows.map(([f, k]) =>
        `<div class="dict-row" data-foreign="${escape(f).toLowerCase()}" data-korean="${escape(k).toLowerCase()}">
          <span class="f">${escape(f)}</span>
          <span class="ar">→</span>
          <span class="k">${escape(k)}</span>
        </div>`).join('')}
    </div>`;
  }
  container.innerHTML = html;
}

$('#dict-search').addEventListener('input', function () {
  const q = this.value.trim().toLowerCase();
  $$('.dict-row').forEach(row => {
    const match = !q || row.dataset.foreign.includes(q) || row.dataset.korean.includes(q);
    row.classList.toggle('hidden-row', !match);
  });
  $$('.dict-category').forEach(cat => {
    const visible = $$('.dict-row:not(.hidden-row)', cat).length > 0;
    cat.style.display = visible ? '' : 'none';
  });
});
