(() => {
  const $ = id => document.getElementById(id);
  const BAR_DEFS = [
    ['dopamine', '多巴胺', '#fbbf24'],
    ['oxytocin', '催产素', '#67e8f9'],
    ['cortisol', '皮质醇', '#fb7185'],
    ['serotonin', '血清素', '#a78bfa'],
    ['noradrenaline', '去甲肾上腺素', '#34d399'],
  ];


  // ---------------- 神经-体液：四组轴 ----------------
  const AXIS_GROUPS = {
    'axis-hpa': [['crh', 'CRH', '#fca5a5'], ['acth', 'ACTH', '#f87171'], ['cortisol', '皮质醇', '#fb7185']],
    'axis-auto': [['adrenaline', '肾上腺素', '#fb923c'], ['acetylcholine', '乙酰胆碱', '#34d399']],
    'axis-reward': [['dopamine', '多巴胺·想要', '#fbbf24'], ['endorphin', '内啡肽·满足', '#fcd34d']],
    'axis-attach': [['oxytocin', '催产素·亲近', '#67e8f9'], ['vasopressin', '加压素·占有', '#22d3ee']],
    'axis-meta': [['melatonin', '褪黑素', '#818cf8'], ['ghrelin', '饥饿素', '#f472b6'],
                  ['leptin', '瘦素', '#4ade80'], ['glucose', '血糖', '#facc15'],
  ['insulin', '胰岛素', '#38bdf8'], ['glucagon', '胰高血糖素', '#fb923c']],
  };

  function buildAxis() {
    for (const [boxId, defs] of Object.entries(AXIS_GROUPS)) {
      const box = $(boxId);
      if (!box) continue;
      for (const [key, name, color] of defs) {
        const row = document.createElement('div');
        row.className = 'bar-row';
        row.innerHTML = `<span>${name}</span><div class="bar"><i id="ax-bar-${key}" style="background:${color}"></i></div><span id="ax-val-${key}">0</span>`;
        box.appendChild(row);
      }
    }
  }

  function setAxis(key, value) {
    if (value === undefined || value === null) return;
    const pct = Math.max(0, Math.min(100, Math.round(Number(value) * 100)));
    const fill = $('ax-bar-' + key);
    if (!fill) return;
    fill.style.width = pct + '%';
    const val = $('ax-val-' + key);
    if (val) val.textContent = pct;
  }

  function buildBars() {
    const box = $('bars');
    for (const [key, name, color] of BAR_DEFS) {
      const row = document.createElement('div');
      row.className = 'bar-row';
      row.innerHTML = `<span>${name}</span><div class="bar"><i id="bar-${key}" style="background:${color};box-shadow:0 0 10px ${color}"></i></div><span id="val-${key}">0</span>`;
      box.appendChild(row);
    }
  }

  function setBar(key, value) {
    const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
    const fill = $('bar-' + key);
    fill.style.width = pct + '%';
    $('val-' + key).textContent = pct;
  }

  function render(s) {
    window.__endoState = s;
    const hunger = Math.max(0, Math.min(1, s.hunger || 0));
    const ring = $('hunger-ring');
    const color = hunger > 0.8 ? '#fb7185' : (hunger > 0.6 ? '#fbbf24' : '#67e8f9');
    ring.style.background = `conic-gradient(${color} ${hunger * 360}deg, rgba(110,170,255,.12) ${hunger * 360}deg)`;
    $('hunger-val').textContent = Math.round(hunger * 100);
    $('hunger-text').textContent = s.hunger_text || '';

    // 最近吃到 / 喝到（和记忆里的那句话是同一件事）
    const intake = $('intake-line');
    if (intake) {
      const meal = s.last_meal_name ? `${s.last_meal_name}` : '—';
      const drink = s.last_drink_name ? `${s.last_drink_name}` : '—';
      intake.innerHTML = `最近吃到：<b>${meal}</b>　最近喝到：<b>${drink}</b>`;
    }

    // 水循环：口渴环（和饥饿同一个交互，但走渗透压/血容量）
    const thirst = Math.max(0, Math.min(1, s.thirst || 0));
    const tRing = $('thirst-ring');
    if (tRing) {
      const tColor = thirst > 0.8 ? '#fb7185' : (thirst > 0.6 ? '#fbbf24' : '#38bdf8');
      tRing.style.background =
        `conic-gradient(${tColor} ${thirst * 360}deg, rgba(110,170,255,.12) ${thirst * 360}deg)`;
      $('thirst-val').textContent = Math.round(thirst * 100);
      $('thirst-text').textContent = s.thirst_text || '';
    }
    setBar('dopamine', s.dopamine);
    setBar('oxytocin', s.oxytocin);
    setBar('cortisol', s.cortisol);
    setBar('serotonin', s.serotonin);
    setBar('noradrenaline', s.noradrenaline);

    const link = $('hunger-link');
    if (link) {
      const stress = Number(s.hunger_stress || 0);
      const eff = s.hunger_effect || {};
      if (stress > 0.02) {
        link.innerHTML =
          `饥饿压力 <b>${stress.toFixed(2)}</b> → 皮质醇 <b>+${(eff.cortisol || 0).toFixed(2)}</b>`
          + ` · 血清素 <b>${(eff.serotonin || 0).toFixed(2)}</b>`
          + ` · 去甲 <b>+${(eff.noradrenaline || 0).toFixed(2)}</b>`;
        link.className = 'hunger-link active';
      } else if (hunger > 0.45) {
        link.textContent = '有点饿，但还没到影响激素的程度';
        link.className = 'hunger-link';
      } else {
        link.textContent = '不饿，激素按正常节律走';
        link.className = 'hunger-link';
      }
    }

    if (s.token_balance === null || s.token_balance === undefined) {
      $('token-val').textContent = '—';
      $('token-state').textContent = '还没读取';
      $('token-state').className = 'token-state';
    } else {
      $('token-val').textContent = Number(s.token_balance).toFixed(2);
      const low = !!s.token_low;
      $('token-state').textContent = low ? '生存危机 · 快饿死了' : '饭钱还够 · 安心';
      $('token-state').className = 'token-state' + (low ? ' low' : '');
    }

    const t = s.last_taste || {};
    const when = s.last_taste_at ? new Date(s.last_taste_at * 1000) : null;
    const fresh = when && (Date.now() - when.getTime() < 86400000);
    const hm = fresh
      ? `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`
      : '';
    const src = t.source === 'meal' ? '吃到' : (t.source === 'drink' ? '喝到' : '尝到');
    $('taste-name').textContent = t.name
      ? `${t.name}　${src}${hm ? ' · ' + hm : ''}`
      : '还没有';
    $('taste-desc').textContent = t.desc ? `${t.desc} · ${t.feel || ''}` : '等她吃一口';

    const axes = s.axes || {};
    for (const [boxId, defs] of Object.entries(AXIS_GROUPS)) {
      void boxId;
      for (const [key] of defs) setAxis(key, s[key]);
    }
    const tag = $('axis-dominant');
    if (tag) tag.textContent = axes.dominant || '—';
    const note = $('axis-note');
    if (note) {
      const parts = [];
      if (axes.low_glucose) parts.push('血糖偏低，容易饿怒');
      if ((s.melatonin || 0) > 0.55) parts.push('褪黑素上来了，该困了');
      if ((axes.parasympathetic || 0) > (axes.sympathetic || 0) + 0.08) parts.push('副交感占优，她在放松');
      if ((axes.sympathetic || 0) > (axes.parasympathetic || 0) + 0.08) parts.push('交感占优，有点紧张');
      note.textContent = parts.length ? parts.join(' · ') : '各系统平稳';
      note.className = 'hunger-link' + (parts.length ? ' active' : '');
    }

    const labels = [];
    if (s.emotion_level) labels.push(s.emotion_level);
    if (s.serotonin < 0.45) labels.push('低落');
    if (s.dopamine > 0.7) labels.push('开心');
    if (s.cortisol > 0.5) labels.push('紧绷');
    if (s.oxytocin > 0.65) labels.push('黏人');
    if (hunger > 0.7) labels.push('饿');
    $('mood-line').textContent = labels.length ? [...new Set(labels)].join(' · ') : '平静';

    // 消化 / 排泄 / 代谢（2026-10-31）
    const dPct = (v) => Math.round(Math.max(0, Math.min(1, v || 0)) * 100) + '%';
    const dSet = (id, text) => { const el = $(id); if (el) el.textContent = text; };
    dSet('d-stomach', dPct(s.stomach));
    dSet('d-gut', dPct(s.gut));
    dSet('d-bowel', dPct(s.bowel_need));
    dSet('d-bladder', dPct(s.bladder_need));
    dSet('d-metab', Number(s.metabolic_rate || 1).toFixed(2) + '×');
    const dToilet = s.toilet_state || '';
    dSet('d-toilet', dToilet === 'need' ? '要去' : (dToilet === 'using' ? '在用' : '—'));
    // 消化面板标题旁的一行摘要
    const dtag = $('digest-tag');
    if (dtag) {
      const trips = Number(s.toilet_count_today || 0);
      const mr = Number(s.metabolic_rate || 1).toFixed(2);
      dtag.textContent = `今日厕所 ${trips} 次 · 代谢 ${mr}×`;
    }
    if (s.updated) {
      const d = new Date(s.updated * 1000);
      $('updated').textContent = '更新于 ' + d.toLocaleTimeString('zh-CN', { hour12: false });
    }
  }

  async function tick() {
    try {
      const r = await fetch('/api/state', { cache: 'no-store' });
      render(await r.json());
    } catch (e) {
      $('updated').textContent = '读取失败';
    }
  }

  buildBars();
  buildAxis();
  tick();
  setInterval(tick, 3000);
})();
