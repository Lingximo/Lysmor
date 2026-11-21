(() => {
  const canvas = document.getElementById('scene');
  const ctx = canvas.getContext('2d');
  const statusEl = document.getElementById('status');
  const toastEl = document.getElementById('toast');
  const avatarImg = new Image();
  avatarImg.src = '/brain/avatar.png';

  const TYPE = {
    person: { label: '人物', color: '#67e8f9' },
    fact: { label: '事实', color: '#fbbf24' },
    topic: { label: '话题', color: '#a78bfa' },
    memory: { label: '记忆', color: '#4dd0e1' },
    skill: { label: '技能', color: '#34d399' },
    place: { label: '地点', color: '#fb7185' },
    object: { label: '物品', color: '#f472b6' },
  };

  // 2026-11-05：太空感渲染开关（?fx=classic 回退旧画法）
  const FX = (new URLSearchParams(location.search).get('fx') || '') !== 'classic';
  // 全局亮度系数：整体压暗时只改这一个数（0=全黑，1=原来）
  const DIM = 0.55;
  // 2026-11-05 22:10 星尘材质（照部署者给的参考图）：颗数 / 柔光强度 两个旋钮
  const DUST_N = 4200;        // 星尘颗数（细尘+亮星）：卡就降到 2600，想更密加到 6000
  const HALO_GAIN = 0.34;     // 柔光强度：0.2 更淡、0.5 更亮（还要乘 DIM）
  // 2026-11-05 22:50：星盘从 R=520 撑到 820，透视焦距要跟着放大，
  // 否则有星星会穿过"镜头平面"（z→-760 时 persp 会爆掉）。
  const FOCAL = 1500;

  const state = {
    nodes: [],
    links: [],
    byId: new Map(),
    hidden: new Set(),
    selected: null,
    hover: null,
    rotX: -0.30,
    rotY: 0.2,
    zoom: 1,
    auto: true,
    dragging: false,
    moved: 0,
    lastX: 0,
    lastY: 0,
    width: 0,
    height: 0,
    dpr: 1,
    stars: [],
    dust: [],
    showLinks: false,
    searchIds: new Set(),
    time: 0,
    decay: null,
    memories: [],
    decaySel: null,
    decayHover: null,
    chart: null,
  };

  const REGION_COLOR = {
    brainstem: '#8ab4ff',
    amygdala: '#fb7185',
    hippocampus: '#67e8f9',
    prefrontal: '#a78bfa',
    scn: '#fbbf24',
    temporal: '#34d399',
    parietal: '#f472b6',
    association: '#94a3b8',
  };

  function typeInfo(type) {
    return TYPE[type] || { label: type || '其他', color: '#8fa8c9' };
  }

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove('show'), 1800);
  }

  function resize() {
    state.dpr = Math.min(window.devicePixelRatio || 1, 2);
    state.width = window.innerWidth;
    state.height = window.innerHeight;
    canvas.width = Math.floor(state.width * state.dpr);
    canvas.height = Math.floor(state.height * state.dpr);
    canvas.style.width = state.width + 'px';
    canvas.style.height = state.height + 'px';
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    makeStars();
    if (FX) { buildNebula(); makeDust(); if (!coreGlow) makeCoreGlow(); }
  }

  function makeStars() {
    state.stars = Array.from({ length: 260 }, () => ({
      x: Math.random() * state.width,
      y: Math.random() * state.height,
      r: Math.random() * 1.4 + 0.2,
      a: Math.random() * 0.5 + 0.08,
      p: Math.random() * Math.PI * 2,
      z: Math.random(),                  // 0 远 → 1 近：视差 + 亮度
      warm: Math.random() < 0.18,        // 少数暖色星，别整片冷蓝
    }));
  }

  async function load() {
    statusEl.textContent = '连接中…';
    try {
      const [graph, stats, recent, decay] = await Promise.all([
        fetch('/api/graph').then(r => r.json()),
        fetch('/api/stats').then(r => r.json()),
        fetch('/api/recent').then(r => r.json()),
        fetch('/api/decay').then(r => r.json()),
      ]);
      buildGraph(graph);
      renderStats(stats);
      renderRecent(recent.items || []);
      renderDecay(decay);
      statusEl.textContent = '在线';
      statusEl.style.color = '#67e8f9';
    } catch (err) {
      statusEl.textContent = '离线';
      statusEl.style.color = '#fb7185';
      toast('加载失败：' + err.message);
    }
  }

  function buildGraph(data) {
    const raw = data.nodes || [];
    const nodes = raw.map((n, i) => {
      const rnd = (k) => {
        const s = Math.sin((i + 1) * 12.9898 + k * 78.233) * 43758.5453;
        return s - Math.floor(s);
      };
      // 银河里每个点都是"记忆"：靠中心的是重要的/常被想起的
      const imp = Math.max(0, Math.min(1, Number(n.importance || n.r || 0.5)));
      const rr = Math.pow(rnd(1), 0.55) * (0.35 + 0.65 * (1 - imp));
      const orb = galaxyOrbit(rr, rnd(2));
      return {
        ...n,
        rad: orb.rad,
        ang: orb.ang,
        w: orbitSpeed(orb.rad) * (0.8 + rnd(5) * 0.4),
        y0: (rnd(6) - 0.5) * (20 + orb.rad * 0.08),
        avy: 3 + rnd(7) * 8,
        aph: rnd(8) * Math.PI * 2,
        x: Math.cos(orb.ang) * orb.rad,
        y: 0,
        z: Math.sin(orb.ang) * orb.rad,
        vx: 0, vy: 0, vz: 0,
        r: 1.1 + Math.sqrt(n.degree || 0) * 0.55 + imp * 1.6,
      };
    });
    nodes.forEach(n => { n.y = n.y0; });
    const byId = new Map(nodes.map(n => [n.id, n]));
    const links = (data.links || [])
      .map(l => ({ ...l, s: byId.get(l.source), t: byId.get(l.target) }))
      .filter(l => l.s && l.t);
    state.nodes = nodes;
    state.links = links;
    state.byId = byId;
    state.selected = null;
    state.searchIds.clear();
    renderLegend();
    document.getElementById('detail').textContent = '点一颗星看看';
  }

  function renderStats(stats) {
    document.getElementById('stat-nodes').textContent = stats.nodes ?? '-';
    document.getElementById('stat-edges').textContent = stats.edges ?? '-';
    document.getElementById('stat-atoms').textContent = stats.atoms ?? '-';
    document.getElementById('stat-memories').textContent = stats.memories ?? '-';
  }

  function renderLegend() {
    const counts = {};
    for (const n of state.nodes) counts[n.type] = (counts[n.type] || 0) + 1;
    const box = document.getElementById('legend');
    box.innerHTML = '';
    for (const [type, info] of Object.entries(TYPE)) {
      if (!counts[type]) continue;
      const row = document.createElement('div');
      row.className = 'legend-item' + (state.hidden.has(type) ? ' off' : '');
      row.innerHTML = `<span class="legend-dot" style="color:${info.color};background:${info.color}"></span>
        <span>${info.label}</span><span class="legend-count">${counts[type]}</span>`;
      row.onclick = () => {
        if (state.hidden.has(type)) state.hidden.delete(type);
        else state.hidden.add(type);
        renderLegend();
      };
      box.appendChild(row);
    }
  }

  function renderRecent(items) {
    const box = document.getElementById('recent');
    box.innerHTML = '';
    if (!items.length) {
      box.textContent = '还没有长期记忆';
      return;
    }
    for (const item of items) {
      const div = document.createElement('div');
      div.className = 'recent-item';
      const time = item.created_at ? String(item.created_at).replace('T', ' ').slice(0, 16) : '';
      div.innerHTML = `<p>${escapeHtml(item.text || '')}</p><span>${escapeHtml(time)}</span>`;
      div.onclick = () => toast(item.text || '');
      box.appendChild(div);
    }
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, s => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
  }

  // ---------------------------------------------------------------- 脑区 / 遗忘曲线
  function renderDecay(data) {
    if (!data || !data.items) return;
    state.decay = data;

    // 脑区
    const box = document.getElementById('regions');
    box.innerHTML = '';
    if (!data.regions.length) {
      box.textContent = '还没有记忆';
    }
    for (const r of data.regions) {
      const row = document.createElement('div');
      row.className = 'region-row';
      const pct = Math.round(r.avg_clarity * 100);
      row.innerHTML =
        `<span class="region-dot" style="color:${r.color};background:${r.color}"></span>
         <span class="region-name">${escapeHtml(r.name)}</span>
         <span class="region-role">${escapeHtml(r.role)}</span>
         <span class="region-bar"><i style="width:${pct}%;background:${r.color}"></i></span>
         <span class="region-count">${r.count}</span>`;
      row.title = r.hint + `\n平均清晰度 ${pct}%`;
      box.appendChild(row);
    }

    // 阶段
    const phases = document.getElementById('phases');
    phases.innerHTML = '';
    const order = ['刻在心里', '记得清楚', '还新鲜', '有点模糊', '快忘了', '几乎想不起'];
    for (const name of order) {
      const n = data.phases[name];
      if (!n) continue;
      const chip = document.createElement('span');
      chip.className = 'phase-chip';
      chip.innerHTML = `${name}<b>${n}</b>`;
      phases.appendChild(chip);
    }

    document.getElementById('vital-clarity').textContent =
      Math.round((data.avg_clarity || 0) * 100) + '%';
    document.getElementById('vital-drop').textContent =
      (data.today_drop || 0).toFixed(3);

    // 最该被想起：清晰度最低、且没被保护的
    const fading = document.getElementById('fading');
    fading.innerHTML = '';
    const risky = data.items.filter(i => !i.protected).slice(0, 4);
    if (!risky.length) {
      fading.innerHTML = '<div class="fading-empty">都记得挺牢，没有快忘掉的</div>';
    }
    for (const item of risky) {
      const div = document.createElement('div');
      div.className = 'fading-item';
      div.textContent = item.summary || '(无摘要)';
      div.title = `清晰度 ${(item.clarity * 100).toFixed(1)}% · ${item.age_days} 天 · 想起过 ${item.accesses} 次`;
      div.onclick = () => {
        state.decaySel = item.id;
        drawDecay();
        toast(item.summary || '');
      };
      fading.appendChild(div);
    }

    // 3D 场景里的"记忆年轮"点
    state.memories = data.items.map(item => ({
      id: item.id,
      item,
      color: REGION_COLOR[item.region] || '#8fa8c9',
    }));

    drawDecay();
  }

  function initChart() {
    const cv = document.getElementById('decay-canvas');
    if (!cv) return null;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth || 272;
    const h = cv.clientHeight || 178;
    cv.width = Math.floor(w * dpr);
    cv.height = Math.floor(h * dpr);
    const c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { cv, c, w, h };
  }

  function chartGeom(w, h) {
    const padL = 26, padR = 8, padT = 12, padB = 18;
    return { x0: padL, y0: padT, iw: w - padL - padR, ih: h - padT - padB };
  }

  function drawDecay() {
    const data = state.decay;
    const chart = initChart();
    if (!data || !chart) return;
    const { c, w, h } = chart;
    const g = chartGeom(w, h);
    c.clearRect(0, 0, w, h);

    const maxAge = Math.max(30, Math.ceil(Math.max(...data.items.map(i => i.age_days), 1)));
    const X = d => g.x0 + (d / maxAge) * g.iw;
    const Y = v => g.y0 + (1 - v) * g.ih;

    // 网格
    c.strokeStyle = 'rgba(110,170,255,0.12)';
    c.lineWidth = 1;
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      c.beginPath();
      c.moveTo(g.x0, Y(v));
      c.lineTo(g.x0 + g.iw, Y(v));
      c.stroke();
      c.fillStyle = 'rgba(127,147,184,0.75)';
      c.font = '8px "Microsoft YaHei", sans-serif';
      c.textAlign = 'right';
      c.fillText(v.toFixed(2), g.x0 - 4, Y(v) + 3);
    }
    c.fillStyle = 'rgba(127,147,184,0.75)';
    c.textAlign = 'center';
    for (const d of [0, Math.round(maxAge / 2), maxAge]) {
      c.fillText(d + '天', X(d), g.y0 + g.ih + 12);
    }

    // 保护线 / 清退线
    const drawLine = (v, color, label) => {
      c.save();
      c.setLineDash([4, 4]);
      c.strokeStyle = color;
      c.beginPath();
      c.moveTo(g.x0, Y(v));
      c.lineTo(g.x0 + g.iw, Y(v));
      c.stroke();
      c.restore();
      c.fillStyle = color;
      c.font = '8px "Microsoft YaHei", sans-serif';
      c.textAlign = 'left';
      c.fillText(label, g.x0 + 2, Y(v) - 3);
    };
    drawLine(0.7, 'rgba(52,211,153,0.5)', '保护线 0.70');
    drawLine(0.45, 'rgba(251,113,133,0.5)', '清退线 0.45');

    // 参考曲线
    const palette = ['#67e8f9', '#a78bfa', '#fb7185', '#34d399'];
    data.profiles.forEach((p, idx) => {
      c.beginPath();
      for (let i = 0; i <= 60; i++) {
        const t = (i / 60) * maxAge;
        const v = Math.exp(-t / Math.max(0.5, p.stability));
        const x = X(t), y = Y(v);
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.strokeStyle = palette[idx % palette.length] + '88';
      c.lineWidth = 1.2;
      c.stroke();
    });

    // 选中记忆的曲线（加粗）
    if (state.decaySel != null) {
      const item = data.items.find(i => i.id === state.decaySel);
      if (item) {
        c.beginPath();
        for (let i = 0; i <= 60; i++) {
          const t = (i / 60) * maxAge;
          const v = item.protected ? 1 : Math.exp(-t / Math.max(0.5, item.stability));
          const x = X(t), y = Y(v);
          i ? c.lineTo(x, y) : c.moveTo(x, y);
        }
        c.strokeStyle = '#ffffff';
        c.lineWidth = 1.8;
        c.stroke();
      }
    }

    // 真实记忆散点
    for (const item of data.items) {
      const x = X(Math.min(item.age_days, maxAge));
      const y = Y(item.clarity);
      const color = REGION_COLOR[item.region] || '#8fa8c9';
      const r = 1.6 + item.clarity * 1.8;
      c.beginPath();
      c.arc(x, y, r + 2.5, 0, Math.PI * 2);
      c.fillStyle = color + '22';
      c.fill();
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fillStyle = color + (item.protected ? 'ff' : 'cc');
      c.fill();
      if (state.decaySel === item.id) {
        c.beginPath();
        c.arc(x, y, r + 4, 0, Math.PI * 2);
        c.strokeStyle = '#ffffff';
        c.lineWidth = 1.2;
        c.stroke();
      }
    }

    // 图例
    const legend = document.getElementById('decay-legend');
    legend.innerHTML = data.profiles.map((p, i) =>
      `<span><i style="background:${palette[i % palette.length]}"></i>${escapeHtml(p.name)}</span>`
    ).join('');
  }

  function chartPointAt(ev) {
    const cv = document.getElementById('decay-canvas');
    if (!cv || !state.decay) return null;
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const g = chartGeom(rect.width, rect.height);
    const maxAge = Math.max(30, Math.ceil(Math.max(...state.decay.items.map(i => i.age_days), 1)));
    let best = null;
    for (const item of state.decay.items) {
      const x = g.x0 + (Math.min(item.age_days, maxAge) / maxAge) * g.iw;
      const y = g.y0 + (1 - item.clarity) * g.ih;
      const d = Math.hypot(mx - x, my - y);
      if (d < 10 && (!best || d < best.d)) best = { d, item };
    }
    return best ? best.item : null;
  }

  function tick() {
    const nodes = state.nodes;
    if (FX) {
      // 银河模式：差速旋转 + 上下浮动 + 一点点自由漂移。
      // 不再"钉死在家、绕着中心刚性转"——每颗星速度不同，看起来是活的。
      const dt = 0.016;
      for (const n of nodes) {
        n.ang += n.w * dt;
        n.x = Math.cos(n.ang) * n.rad + Math.sin(state.time * 0.21 + n.aph) * 6;
        n.z = Math.sin(n.ang) * n.rad + Math.cos(state.time * 0.18 + n.aph) * 6;
        n.y = n.y0 + Math.sin(state.time * 0.3 + n.aph) * n.avy;
      }
      return;
    }
    for (const n of nodes) {
      n.vx += -n.x * 0.00024;
      n.vy += -n.y * 0.00024;
      n.vz += -n.z * 0.00024;
    }
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; }
        const f = 3800 / (d2 + 36);
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; a.vz += (dz / d) * f;
        b.vx -= (dx / d) * f; b.vy -= (dy / d) * f; b.vz -= (dz / d) * f;
      }
    }
    for (const l of state.links) {
      if (state.hidden.has(l.s.type) || state.hidden.has(l.t.type)) continue;
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, dz = l.t.z - l.s.z;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const f = (d - 118) * 0.0011;
      l.s.vx += (dx / d) * f; l.s.vy += (dy / d) * f; l.s.vz += (dz / d) * f;
      l.t.vx -= (dx / d) * f; l.t.vy -= (dy / d) * f; l.t.vz -= (dz / d) * f;
    }
    for (const n of nodes) {
      n.vx *= 0.9; n.vy *= 0.9; n.vz *= 0.9;
      n.x += n.vx; n.y += n.vy; n.z += n.vz;
    }
  }

  // 记忆年轮：年龄取对数映射到半径，越老越靠外
  function memoryRing(ageDays) {
    return 120 + Math.log1p(Math.max(0, ageDays)) * 90;
  }

  function ringPoints(ring, seg = 64) {
    const pts = [];
    for (let i = 0; i <= seg; i++) {
      const a = (i / seg) * Math.PI * 2;
      pts.push(project({
        x: Math.cos(a) * ring,
        y: Math.sin(a) * ring * 0.42,
        z: Math.sin(a) * ring * 0.8,
      }));
    }
    return pts;
  }

  function project(n) {
    const cy = Math.cos(state.rotY), sy = Math.sin(state.rotY);
    let x = n.x * cy - n.z * sy;
    let z = n.x * sy + n.z * cy;
    const cx = Math.cos(state.rotX), sx = Math.sin(state.rotX);
    let y = n.y * cx - z * sx;
    z = n.y * sx + z * cx;
    // 焦距放大的同时夹一下：不管星转多远，都不会突然变成巨物或翻面
    const persp = Math.max(0.32, Math.min(2.6, FOCAL / (FOCAL + z))) * state.zoom;
    return {
      x: state.width / 2 + x * persp,
      y: state.height / 2 + y * persp,
      z,
      scale: persp,
    };
  }

  function isVisible(n) {
    return !state.hidden.has(n.type);
  }

  // ------------------------------------------------------------ 太空感渲染
  // 2026-11-05：只改"怎么画"，不动力学/布局。不满意加 ?fx=classic 回退旧画法。
  let nebula = null;
  const glowCache = new Map();

  function hexA(hex, a) {
    let h = String(hex || '#8fa8c9').replace('#', '');
    if (h.length === 3) h = h.split('').map(x => x + x).join('');
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // 预渲染的柔光球：比每帧 shadowBlur 便宜一个数量级
  function glowSprite(color) {
    if (glowCache.has(color)) return glowCache.get(color);
    const S = 128;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    grad.addColorStop(0, 'rgba(255,255,255,0.95)');
    grad.addColorStop(0.16, hexA(color, 0.95));
    grad.addColorStop(0.42, hexA(color, 0.38));
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grad;
    g.beginPath();
    g.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
    g.fill();
    glowCache.set(color, c);
    return c;
  }

  // 2026-11-05 22:10 部署者给的参考图：每颗星是"小小的白芯 + 一圈带颜色的柔光"。
  // 这套材质就是照它做的：芯小、晕软、颜色是星的色温，不是整片发光。
  const haloCache = new Map();
  function haloSprite(hex) {
    if (haloCache.has(hex)) return haloCache.get(hex);
    const S = 96;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    grad.addColorStop(0, 'rgba(255,255,255,0.98)');
    grad.addColorStop(0.10, hexA(hex, 0.92));
    grad.addColorStop(0.28, hexA(hex, 0.42));
    grad.addColorStop(0.60, hexA(hex, 0.13));
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grad;
    g.beginPath();
    g.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
    g.fill();
    haloCache.set(hex, c);
    return c;
  }

  // 背景星云：一次画到离屏画布，每帧只贴图，不重算渐变
  function buildNebula() {
    const w = Math.max(2, state.width), h = Math.max(2, state.height);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');

    // 底：深深海蓝（2026-11-05 §66：原来太蓝了，压成接近黑的深蓝）
    const base = g.createLinearGradient(0, 0, 0, h);
    base.addColorStop(0, '#05040e');
    base.addColorStop(0.55, '#0a0818');
    base.addColorStop(1, '#03020a');
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);

    g.globalCompositeOperation = 'lighter';

    // 银河那条"光带"（压扁的椭圆）：太空照里最像银河的一笔
    g.save();
    g.translate(w * 0.5, h * 0.52);
    g.scale(1, 0.26);
    const band = g.createRadialGradient(0, 0, 0, 0, 0, Math.max(w, h) * 0.46);
    band.addColorStop(0, 'rgba(126,120,225,0.12)');
    band.addColorStop(0.35, 'rgba(92,80,180,0.07)');
    band.addColorStop(0.70, 'rgba(38,48,96,0.025)');
    band.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = band;
    g.beginPath();
    g.arc(0, 0, Math.max(w, h) * 0.46, 0, Math.PI * 2);
    g.fill();
    g.restore();

    // 几团星云：深海军蓝为主，紫/青只留一点点，别再整片发蓝
    const blobs = [
      [0.30, 0.40, 0.55, 'rgba(26,44,96,0.26)', 'rgba(14,24,58,0.08)'],
      [0.68, 0.34, 0.50, 'rgba(46,32,86,0.20)', 'rgba(26,16,52,0.07)'],
      [0.58, 0.68, 0.55, 'rgba(14,52,74,0.14)', 'rgba(6,26,38,0.05)'],
      [0.40, 0.74, 0.44, 'rgba(52,28,64,0.10)', 'rgba(24,12,32,0.04)'],
      [0.50, 0.50, 0.62, 'rgba(22,36,84,0.16)', 'rgba(10,18,44,0.06)'],
      [0.16, 0.20, 0.34, 'rgba(70,120,200,0.14)', 'rgba(20,40,90,0.05)'],
    ];
    for (const [x, y, r, c1, c2] of blobs) {
      const R = Math.max(w, h) * r;
      const grad = g.createRadialGradient(x * w, y * h, 0, x * w, y * h, R);
      grad.addColorStop(0, c1);
      grad.addColorStop(0.55, c2);
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = grad;
      g.beginPath();
      g.arc(x * w, y * h, R, 0, Math.PI * 2);
      g.fill();
    }
    // 静态微星：给背景一点颗粒感（2026-11-05：1400 → 700，
    // 星尘自己有柔光了，背景再铺一层就显脏、也不像参考图那种"中间一团、四周很空"）
    for (let i = 0; i < 700; i++) {
      const a = Math.random() * 0.14;
      const t = Math.random();
      const col = t < 0.60 ? '190,215,255' : (t < 0.85 ? '255,255,255' : '255,228,196');
      g.fillStyle = `rgba(${col},${a})`;
      const rr = Math.random() < 0.94 ? 0.55 : 1.0;
      g.beginPath();
      g.arc(Math.random() * w, Math.random() * h, rr, 0, Math.PI * 2);
      g.fill();
    }
    // 暗角：边缘压暗，中间那点"星系核"更亮
    g.globalCompositeOperation = 'source-over';
    const vg = g.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.20,
      w / 2, h / 2, Math.max(w, h) * 0.80);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(0.72, 'rgba(0,0,0,0.35)');
    vg.addColorStop(1, 'rgba(0,0,0,0.86)');
    g.fillStyle = vg;
    g.fillRect(0, 0, w, h);
    nebula = c;
  }

  // 核心大光晕：白热 → 暖白 → 淡紫 → 消失，一张贴图反复用
  let coreGlow = null;
  function makeCoreGlow() {
    const S = 512;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    gr.addColorStop(0, 'rgba(255,255,255,0.55)');
    gr.addColorStop(0.06, 'rgba(255,248,235,0.40)');
    gr.addColorStop(0.16, 'rgba(220,225,255,0.18)');
    gr.addColorStop(0.32, 'rgba(130,140,255,0.08)');
    gr.addColorStop(0.60, 'rgba(70,70,180,0.03)');
    gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr;
    g.beginPath();
    g.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
    g.fill();
    coreGlow = c;
  }

  function drawCoreGlow() {
    if (!coreGlow) return;
    const pulse = 0.5 + 0.5 * Math.sin(state.time * 1.3);
    const S = Math.min(state.width, state.height) * (0.78 + pulse * 0.03);
    ctx.globalCompositeOperation = 'lighter';
    // 0.9 → 0.45 → 0.26：只当"氛围"，不当"光源"
    ctx.globalAlpha = 0.10 * DIM;
    ctx.drawImage(coreGlow, state.width / 2 - S / 2, state.height / 2 - S / 2, S, S);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  function drawStars() {
    const t = state.time;
    for (const s of state.stars) {
      const px = ((s.x + state.rotY * 90 * (s.z || 0)) % state.width + state.width) % state.width;
      const tw = 0.55 + 0.45 * Math.sin(t * (1.4 + (s.z || 0)) + s.p);
      const a = Math.min(1, s.a * tw);
      ctx.globalAlpha = a;
      ctx.fillStyle = s.warm ? 'rgba(255,236,206,1)' : 'rgba(196,220,255,1)';
      const rr = s.r * (0.6 + (s.z || 0) * 0.9);
      ctx.beginPath();
      ctx.arc(px, s.y, rr, 0, Math.PI * 2);
      ctx.fill();
      if (s.r > 1.15 && tw > 0.88) {
        ctx.globalAlpha = a * 0.45;
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(px - rr * 4, s.y); ctx.lineTo(px + rr * 4, s.y);
        ctx.moveTo(px, s.y - rr * 4); ctx.lineTo(px, s.y + rr * 4);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  // ------------------------------------------------------------ 银河
  // 2026-11-05 22:50：部署者要"分布散一点"——盘半径 R 520→820、径向分布更均匀
  // （指数 1.65→1.15）、旋臂更糊（spread 加大）、厚度 96→190，从"薄饼"变成"一团"。
  function galaxyPos(rSel, aSel) {
    const R = 820;
    const r = Math.pow(Math.min(0.999, Math.max(0, rSel)), 1.5) * R;
    const arms = 2;
    const arm = Math.floor(aSel * arms) % arms;
    const spread = 0.42 + 1.05 * (r / R);
    const theta = (arm / arms) * Math.PI * 2 + r * 0.0125
      + ((aSel * 935.7) % 1 - 0.5) * spread;
    const y = (Math.random() - 0.5) * (190 + r * 0.50);
    return { x: Math.cos(theta) * r, y, z: Math.sin(theta) * r };
  }

  // 自然流动：每颗星有自己的角速度和一点垂直摆动，不是整个盘刚性转。
  function galaxyOrbit(rSel, aSel) {
    const R = 820;
    const rad = Math.pow(Math.min(0.999, Math.max(0, rSel)), 1.5) * R;
    const arms = 2;
    const arm = Math.floor(aSel * arms) % arms;
    const spread = 0.42 + 1.05 * (rad / R);
    const ang = (arm / arms) * Math.PI * 2 + rad * 0.0125
      + ((aSel * 935.7) % 1 - 0.5) * spread;
    return { rad, ang };
  }

  // 内圈转得快、外圈慢（差速旋转）——真实的星系就是这样，也才不会像"整体在转"
  function orbitSpeed(rad) {
    return 0.09 / (0.55 + rad / 380);
  }

  // 2026-11-06：照「意识海」参考图重做材质——
  //   细尘（不发光，量大，负责"臂"的密度）
  // + 亮星（带柔光，量少，负责"粒"的层次）
  // + 核心一团暖白光（参考图最抢眼的就是那颗亮核）
  function makeDust() {
    const N = DUST_N;
    const out = new Array(N);
    for (let i = 0; i < N; i++) {
      const rnd = (k) => {
        const s = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453;
        return s - Math.floor(s);
      };
      const orb = galaxyOrbit(Math.pow(rnd(1), 0.55), rnd(2));
      const isStar = rnd(13) < 0.26;          // 26% 是亮星，其余是细尘
      const t = rnd(6);
      let col, hex;
      if (t < 0.52) { col = 'rgba(226,236,255,1)'; hex = '#eaf3ff'; }
      else if (t < 0.82) { col = 'rgba(196,214,255,1)'; hex = '#a9c2ff'; }
      else if (t < 0.92) { col = 'rgba(214,196,255,1)'; hex = '#c0a8ff'; }
      else { col = 'rgba(255,236,206,1)'; hex = '#ffd9a8'; }
      out[i] = {
        rad: orb.rad,
        ang: orb.ang,
        w: orbitSpeed(orb.rad) * (0.75 + rnd(7) * 0.5),
        y0: (rnd(8) - 0.5) * (120 + orb.rad * 0.30),   // 盘更薄
        avy: 3 + rnd(9) * 8,
        aph: rnd(10) * Math.PI * 2,
        x: Math.cos(orb.ang) * orb.rad,
        y: 0,
        z: Math.sin(orb.ang) * orb.rad,
        s: isStar ? (1.0 + rnd(3) * 1.4) : (0.5 + rnd(3) * 0.7),
        a: isStar ? (0.55 + rnd(4) * 0.45) : (0.20 + rnd(4) * 0.35),
        c: col,
        hex,
        star: isStar,
        core: 1 + Math.max(0, 1 - orb.rad / 260) * 0.8,   // 越靠中心越亮
        halo: 0.55 + rnd(11) * 0.8,
        bloom: isStar && rnd(12) < 0.12,
      };
      out[i].y = out[i].y0;
    }
    state.dust = out;
  }

  function drawDust() {
    const dt = 0.016;
    ctx.globalCompositeOperation = 'lighter';
    for (const d of state.dust) {
      d.ang += d.w * dt;
      d.x = Math.cos(d.ang) * d.rad;
      d.z = Math.sin(d.ang) * d.rad;
      d.y = d.y0 + Math.sin(state.time * 0.35 + d.aph) * d.avy;
      const p = project(d);
      if (!p || p.scale <= 0.02) continue;
      const a = Math.min(1, d.a * (d.core || 1) * Math.min(1, p.scale * 1.15));
      if (a < 0.02) continue;
      const s = Math.max(0.6, d.s * p.scale * (d.star ? 1.5 : 1.05));

      if (d.star) {
        const S = Math.max(5, s * 6.0 * (d.halo || 1) * (d.bloom ? 1.8 : 1));
        const spr = haloSprite(d.hex || '#cfe3ff');
        ctx.globalAlpha = Math.min(0.55, a * HALO_GAIN * DIM * (d.bloom ? 1.4 : 1));
        ctx.drawImage(spr, p.x - S / 2, p.y - S / 2, S, S);
      }
      ctx.globalAlpha = Math.min(1, a * 1.05);
      ctx.fillStyle = d.c || 'rgba(214,232,255,1)';
      ctx.fillRect(p.x - s / 2, p.y - s / 2, s, s);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  // 核心：暖白亮核（参考图最亮的那一颗）
  let coreSprite = null;
  function makeCoreSprite() {
    const S = 512;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const g = cv.getContext('2d');
    const gr = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    gr.addColorStop(0, 'rgba(255,255,255,0.95)');
    gr.addColorStop(0.05, 'rgba(255,248,228,0.80)');
    gr.addColorStop(0.15, 'rgba(255,214,168,0.34)');
    gr.addColorStop(0.38, 'rgba(160,130,230,0.12)');
    gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr;
    g.beginPath();
    g.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
    g.fill();
    coreSprite = cv;
  }

  function drawGalaxyCore() {
    if (!coreSprite) makeCoreSprite();
    const pulse = 0.5 + 0.5 * Math.sin(state.time * 1.1);
    const S = Math.min(state.width, state.height) * (0.62 + pulse * 0.02);
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.50;
    ctx.drawImage(coreSprite, state.width / 2 - S / 2, state.height / 2 - S / 2, S, S);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }
  function draw() {
    state.time += 0.01;
    // 相机自转放得很慢：主要动感交给每颗星自己的差速公转
    if (state.auto && !state.dragging) state.rotY += 0.00055;
    tick();

    ctx.clearRect(0, 0, state.width, state.height);

    if (FX && nebula) {
      // 极慢的漂移（±6px），避免"贴纸"感
      const dx = Math.sin(state.time * 0.05) * 6;
      const dy = Math.cos(state.time * 0.04) * 6;
      ctx.drawImage(nebula, dx - 6, dy - 6, state.width + 12, state.height + 12);
      // 银河模式下不再画旧的"屏幕平铺星星"——4200 颗盘面星尘已经把天填满了，
      // 两套星星叠在一起只会显得脏（旧的那套留在 classic 里）。
      drawGalaxyCore();
      drawDust();
      // 2026-11-05：部署者要"不要光晕，只有星星淡淡发光"——核心光晕整个关掉
    } else {
      for (const s of state.stars) {
        const a = s.a * (0.6 + 0.4 * Math.sin(state.time * 2 + s.p));
        ctx.fillStyle = `rgba(150,200,255,${a})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    const links = [];
    for (const l of state.links) {
      if (!isVisible(l.s) || !isVisible(l.t)) continue;
      const a = project(l.s), b = project(l.t);
      links.push({ a, b, depth: (a.z + b.z) / 2 });
    }
    links.sort((p, q) => q.depth - p.depth);
    ctx.lineWidth = 0.7;
    if (FX) {
      // 银河模式下默认不画连线——参考图是一片星海，没有网格。
      // 想看关系就按 L，才会画出很淡的曲线。
      if (state.showLinks) {
      ctx.globalCompositeOperation = 'lighter';
      for (const l of links) {
        const alpha = Math.max(0.03, Math.min(0.20, 0.20 - (l.depth + 200) / 2400));
        const mx = (l.a.x + l.b.x) / 2 + (l.a.y - l.b.y) * 0.05;
        const my = (l.a.y + l.b.y) / 2 + (l.b.x - l.a.x) * 0.05;
        ctx.strokeStyle = `rgba(96,164,255,${alpha})`;
        ctx.beginPath();
        ctx.moveTo(l.a.x, l.a.y);
        ctx.quadraticCurveTo(mx, my, l.b.x, l.b.y);
        ctx.stroke();
      }
      // 沿连线跑的数据点：位置按时间算，不额外占内存
      const step = Math.max(1, Math.floor(links.length / 120));
      for (let i = 0; i < links.length; i += step) {
        const l = links[i];
        const u = (state.time * 0.22 + i * 0.137) % 1;
        const mx = (l.a.x + l.b.x) / 2 + (l.a.y - l.b.y) * 0.05;
        const my = (l.a.y + l.b.y) / 2 + (l.b.x - l.a.x) * 0.05;
        const x = (1 - u) * (1 - u) * l.a.x + 2 * (1 - u) * u * mx + u * u * l.b.x;
        const y = (1 - u) * (1 - u) * l.a.y + 2 * (1 - u) * u * my + u * u * l.b.y;
        ctx.globalAlpha = 0.5;
        ctx.fillStyle = 'rgba(190,225,255,1)';
        ctx.beginPath();
        ctx.arc(x, y, 1.1, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      }
    } else {
      for (const l of links) {
        const alpha = Math.max(0.035, Math.min(0.22, 0.22 - (l.depth + 200) / 2200));
        ctx.strokeStyle = `rgba(110,170,255,${alpha})`;
        ctx.beginPath();
        ctx.moveTo(l.a.x, l.a.y);
        ctx.lineTo(l.b.x, l.b.y);
        ctx.stroke();
      }
    }

    const nodes = state.nodes.filter(isVisible).map(n => ({ n, p: project(n) }))
      .sort((a, b) => b.p.z - a.p.z);
    for (const { n, p } of nodes) {
      const info = typeInfo(n.type);
      const r = FX
        ? Math.max(0.9, n.r * p.scale * 0.8)
        : Math.max(2.5, n.r * p.scale * 1.35);
      const dim = state.searchIds.size && !state.searchIds.has(n.id);
      const alpha = dim ? 0.18 : 1;
      ctx.globalAlpha = alpha;
      if (FX) {
        // 星海：绝大多数是 1~2 像素的小点，只有重要的/被选中的才带柔光
        const hot = state.selected === n.id || state.hover === n.id
          || (n.importance || 0) >= 0.55 || (n.degree || 0) >= 10;
        const depthK = Math.max(0.4, Math.min(1, 0.5 + (1 - (p.z + 260) / 520) * 0.5));
        if (hot) {
          const spr = glowSprite(info.color);
          const S = Math.max(9, r * 9);
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = alpha * 0.16 * depthK * DIM;
          ctx.drawImage(spr, p.x - S / 2, p.y - S / 2, S, S);
          ctx.globalCompositeOperation = 'source-over';
        }
        ctx.globalAlpha = alpha;
        ctx.fillStyle = hot ? '#ffffff' : info.color;
        // 圆点，不是方块（原来 fillRect 会看成小正方形）
        const s = Math.max(1.0, r);
        ctx.beginPath();
        ctx.arc(p.x, p.y, s * 0.62, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.shadowBlur = 14 * p.scale;
        ctx.shadowColor = info.color;
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 1.9);
        grad.addColorStop(0, info.color);
        grad.addColorStop(0.35, info.color + 'aa');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 1.9, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = info.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (state.selected === n.id || state.hover === n.id) {
        ctx.shadowBlur = 24;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      if (state.selected === n.id || state.hover === n.id || (!FX && !dim && n.degree >= 14)) {
        ctx.shadowBlur = 0;
        ctx.fillStyle = state.selected === n.id ? '#ffffff' : 'rgba(215,235,255,0.82)';
        ctx.font = '10px "Microsoft YaHei", sans-serif';
        ctx.textAlign = 'center';
        const text = n.label.length > 16 ? n.label.slice(0, 15) + '…' : n.label;
        ctx.fillText(text, p.x, p.y + r + 13);
      }
    }
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;

    // 记忆年轮：离中心越远越老，越暗越淡（我们的记忆是这么放着的）
    if (state.memories.length) {
      // 先画年轮导引圈：1 / 3 / 10 / 30 天
      ctx.font = '9px "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'center';
      for (const days of [1, 3, 10, 30]) {
        const ring = memoryRing(days);
        const pts = ringPoints(ring);
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.strokeStyle = 'rgba(120,180,255,0.09)';
        ctx.lineWidth = 1;
        ctx.stroke();
        const tip = pts[Math.round(pts.length * 0.12)];
        if (tip) {
          ctx.fillStyle = 'rgba(127,147,184,0.5)';
          ctx.fillText(days + ' 天', tip.x, tip.y - 4);
        }
      }

      for (const m of state.memories) {
        const item = m.item;
        const ang = (item.id * 2.399963) % (Math.PI * 2);
        const ring = memoryRing(item.age_days);
        const pt = {
          x: Math.cos(ang) * ring,
          y: Math.sin(ang) * ring * 0.42,
          z: Math.sin(ang) * ring * 0.8,
        };
        const p = project(pt);
        const alpha = 0.1 + item.clarity * 0.8;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = m.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.1 + item.clarity * 1.6, 0, Math.PI * 2);
        ctx.fill();
        if (state.decaySel === item.id) {
          ctx.globalAlpha = 1;
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
    }

    drawCore();
    requestAnimationFrame(draw);
  }

  function drawCore() {
    const cx = state.width / 2;
    const cy = state.height / 2;
    const pulse = 0.5 + 0.5 * Math.sin(state.time * 1.7);
    const r = 26 + pulse * 1.2;
    // 2026-11-05 §65：部署者要"不要光晕，只有星星淡淡发光"——
    // 核心那团径向光整个删掉，只留头像 + 一圈很淡的细边。
    if (avatarImg.complete && avatarImg.naturalWidth) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.clip();
      ctx.drawImage(avatarImg, cx - r, cy - r, r * 2, r * 2);
      ctx.restore();
      ctx.strokeStyle = 'rgba(150,235,255,0.26)';
      ctx.lineWidth = 1.2;
      ctx.shadowBlur = 4;
      ctx.shadowColor = 'rgba(103,232,249,0.5)';
      ctx.beginPath();
      ctx.arc(cx, cy, r + 3, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
    } else {
      ctx.strokeStyle = 'rgba(140,245,255,0.55)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 1.6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = '#dffcff';
      ctx.font = '12px "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('TA', cx, cy + 4);
    }
  }

  function nodeAt(mx, my) {
    let best = null;
    for (const n of state.nodes) {
      if (!isVisible(n)) continue;
      const p = project(n);
      const r = Math.max(9, n.r * p.scale * 1.35 + 8);
      const dx = mx - p.x, dy = my - p.y;
      if (dx * dx + dy * dy <= r * r && (!best || p.z < best.z)) best = { n, z: p.z };
    }
    return best ? best.n : null;
  }

  async function selectNode(n) {
    state.selected = n.id;
    const box = document.getElementById('detail');
    box.innerHTML = '<span style="color:#7f93b8">读取中…</span>';
    try {
      const detail = await fetch('/api/node?id=' + encodeURIComponent(n.id)).then(r => r.json());
      const info = typeInfo(detail.type || n.type);
      const neighbors = (detail.neighbors || []).slice(0, 12).map(x =>
        `<div class="neighbor">${escapeHtml(x.label)} <span>· ${escapeHtml(x.relation || '')}</span></div>`
      ).join('');
      box.innerHTML = `<h3>${escapeHtml(detail.value || n.label)}</h3>
        <span class="tag" style="color:${info.color}">${escapeHtml(info.label)}</span>
        <span class="tag">${detail.neighbors ? detail.neighbors.length : 0} 条关系</span>
        ${neighbors || '<div style="color:#7f93b8;font-size:11px">没有相邻节点</div>'}`;
    } catch (err) {
      box.textContent = '读取失败：' + err.message;
    }
  }

  function resetView() {
    state.rotX = -0.30;
    state.rotY = 0.2;
    state.zoom = 1;
    toast('视角已重置');
  }

  canvas.addEventListener('mousedown', e => {
    state.dragging = true;
    state.moved = 0;
    state.lastX = e.clientX;
    state.lastY = e.clientY;
  });
  window.addEventListener('mousemove', e => {
    if (!state.dragging) {
      const hit = nodeAt(e.clientX, e.clientY);
      state.hover = hit ? hit.id : null;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
      return;
    }
    const dx = e.clientX - state.lastX;
    const dy = e.clientY - state.lastY;
    state.moved += Math.abs(dx) + Math.abs(dy);
    state.rotY += dx * 0.006;
    state.rotX = Math.max(-1.2, Math.min(1.2, state.rotX + dy * 0.006));
    state.lastX = e.clientX;
    state.lastY = e.clientY;
  });
  window.addEventListener('mouseup', e => {
    if (!state.dragging) return;
    state.dragging = false;
    if (state.moved < 6) {
      const hit = nodeAt(e.clientX, e.clientY);
      if (hit) selectNode(hit);
    }
  });
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    state.zoom = Math.max(0.35, Math.min(3.2, state.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
  }, { passive: false });

  canvas.addEventListener('touchstart', e => {
    if (e.touches.length === 1) {
      state.dragging = true;
      state.moved = 0;
      state.lastX = e.touches[0].clientX;
      state.lastY = e.touches[0].clientY;
    }
  }, { passive: true });
  canvas.addEventListener('touchmove', e => {
    if (!state.dragging || e.touches.length !== 1) return;
    const dx = e.touches[0].clientX - state.lastX;
    const dy = e.touches[0].clientY - state.lastY;
    state.moved += Math.abs(dx) + Math.abs(dy);
    state.rotY += dx * 0.006;
    state.rotX = Math.max(-1.2, Math.min(1.2, state.rotX + dy * 0.006));
    state.lastX = e.touches[0].clientX;
    state.lastY = e.touches[0].clientY;
  }, { passive: true });
  canvas.addEventListener('touchend', () => { state.dragging = false; }, { passive: true });

  document.getElementById('rotate-btn').onclick = e => {
    state.auto = !state.auto;
    e.currentTarget.classList.toggle('active', state.auto);
  };
  document.getElementById('reset-btn').onclick = resetView;
  document.getElementById('refresh-btn').onclick = () => { load(); toast('已刷新'); };

  // L 键：银河模式下切换"关系连线"（默认关着，参考图里没有网格）
  window.addEventListener('keydown', e => {
    if (e.target && /input|textarea/i.test(e.target.tagName)) return;
    if (e.key === 'l' || e.key === 'L') {
      state.showLinks = !state.showLinks;
      toast(state.showLinks ? '显示关系连线' : '只看星海');
    }
  });

  const search = document.getElementById('search');
  const results = document.getElementById('search-results');
  let searchTimer = null;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = search.value.trim();
    if (!q) {
      results.classList.remove('show');
      state.searchIds.clear();
      return;
    }
    searchTimer = setTimeout(async () => {
      try {
        const data = await fetch('/api/search?q=' + encodeURIComponent(q)).then(r => r.json());
        results.innerHTML = '';
        state.searchIds = new Set((data.items || []).map(x => x.id));
        if (!data.items || !data.items.length) {
          results.innerHTML = '<div class="search-item"><b>没有搜到</b><span>换个词试试</span></div>';
        } else {
          for (const item of data.items) {
            const div = document.createElement('div');
            div.className = 'search-item';
            const info = typeInfo(item.type);
            div.innerHTML = `<b>${escapeHtml(item.label)}</b><span style="color:${info.color}">${escapeHtml(info.label)}</span>`;
            div.onclick = () => {
              const n = state.byId.get(item.id);
              if (n) selectNode(n);
              results.classList.remove('show');
            };
            results.appendChild(div);
          }
        }
        results.classList.add('show');
      } catch (err) {
        results.innerHTML = '<div class="search-item"><b>搜索失败</b><span>' + escapeHtml(err.message) + '</span></div>';
        results.classList.add('show');
      }
    }, 220);
  });
  search.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const first = results.querySelector('.search-item');
      if (first) first.click();
    }
  });
  document.getElementById('search-btn').onclick = () => {
    const first = results.querySelector('.search-item');
    if (first) first.click();
    else toast('先输入关键词');
  };
  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap')) results.classList.remove('show');
  });

  window.addEventListener('resize', resize);
  resize();

  const decayCanvas = document.getElementById('decay-canvas');
  if (decayCanvas) {
    const note = document.getElementById('decay-note');
    decayCanvas.addEventListener('mousemove', e => {
      const hit = chartPointAt(e);
      decayCanvas.style.cursor = hit ? 'pointer' : 'default';
      if (hit) {
        note.innerHTML =
          `清晰度 <b style="color:#9fd3ff">${(hit.clarity * 100).toFixed(1)}%</b>`
          + ` · ${hit.age_days} 天前 · 想起 ${hit.accesses} 次 · ${hit.phase}<br>`
          + escapeHtml(hit.summary);
      } else {
        note.textContent = '点图上的点，看是哪条记忆';
      }
    });
    decayCanvas.addEventListener('mouseleave', () => {
      note.textContent = '点图上的点，看是哪条记忆';
    });
    decayCanvas.addEventListener('click', e => {
      const hit = chartPointAt(e);
      if (hit) {
        state.decaySel = hit.id;
        drawDecay();
        toast(hit.summary || '');
      }
    });
    window.addEventListener('resize', () => drawDecay());
  }

  load();
  requestAnimationFrame(draw);
})();
