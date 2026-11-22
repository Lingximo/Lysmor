/* TA · 大平层（科幻材质 + 斜 45° 固定视角）
 * 视角：正交 45°，地面在屏幕上的高度压到 cos45；家具体块向上拉出侧面。
 * 材质：深色金属 / 复合板材 / 青色光边 / 全息网格；按真实钟点变光。
 * 逻辑不变：位置由后端算，前端按同一条折线插值。
 */
(() => {
  'use strict';
  const tr = (key, vars) => window.LysmorI18n.t(key, vars);

  const canvas = document.getElementById('house');
  const stage = document.getElementById('stage');
  const ctx = canvas.getContext('2d');

  const TILT = Math.PI / 4;          // 45°
  const COS = Math.cos(TILT);        // 0.7071
  const TAN = Math.tan(TILT);        // 1
  const ROT = -Math.PI / 4;          // 方位角也转 45°，等距视角

  let plan = null;
  let state = null;
  let skew = 0;
  let scale = 1, offX = 0, offY = 0;
  let focus = null;
  let windowKey = '';

  const avatar = new Image();
  avatar.src = '/static/avatar.png';
  let avatarReady = false;
  avatar.onload = () => { avatarReady = true; };

  const bg = new Image();

  const hourParam = Number(new URLSearchParams(location.search).get('hour'));
  const HOUR_LOCK = Number.isFinite(hourParam) && hourParam >= 0 && hourParam <= 24
    ? hourParam : null;

  // ------------------------------------------------------------ 科幻材质
  const MAT = {
    wallTop: '#18212c',
    wallBottom: '#0b1119',
    herFloor: ['#182634', '#101a26'],
    dadFloor: ['#16222f', '#0f1924'],
    livingFloor: ['#1a2a3a', '#111d29'],
    kitchenFloor: ['#141c26', '#0d141c'],
    toiletFloor: ['#151e29', '#0e161f'],
    balconyFloor: ['#0f1a1e', '#0a1216'],
    cyan: '#67e8f9',
    blue: '#38bdf8',
    violet: '#a78bfa',
    amber: '#fbbf24',
    ceramic: '#c6d3dd',
    sideTop: '#101a26',
    sideBottom: '#04070b',
    platform: '#0a1118',
  };

  // 每类家具在 45° 下的"高度"（米），决定侧面拉出多少
  const HEIGHT = {
    bed: 0.8,
    sofa: 0.65,
    desk: 0.6,
    monitor: 0.42,
    chair: 0.72,
    shelf: 1.4,
    wardrobe: 1.4,
    fridge: 1.2,
    cabinet: 0.9,
    counter: 0.75,
    table: 0.55,
    coffee: 0.42,
    tv: 0.35,
    toilet: 0.6,
    vanity: 0.7,
    tub: 0.6,
    rack: 1.2,
    towel: 0.04,
    sink: 0.06,
    stove: 0.05,
    rug: 0.02,
    lamp: 0.02,
    plant: 0.05,
    rail: 0.02,
  };

  function rnd(seed) {
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => {
      s = (s * 16807) % 2147483647;
      return (s - 1) / 2147483646;
    };
  }

  const dist2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function now() { return Date.now() / 1000 + skew; }

  function hourOf(t) {
    const d = new Date(t * 1000);
    return d.getHours() + d.getMinutes() / 60;
  }

  function modeName(h) {
    if (h < 5) return tr("panels.late_night");
    if (h < 7) return tr("panels.early_morning");
    if (h < 11) return tr("panels.morning");
    if (h < 14) return tr("panels.midday");
    if (h < 17) return tr("panels.afternoon");
    if (h < 20) return tr("panels.evening");
    return tr("panels.night");
  }

  function routePos(route, t0, speed, t) {
    if (!route || !route.length) return [0, 0];
    if (route.length === 1) return route[0].slice();
    let remain = Math.max(0, (t - t0) * speed);
    let cur = route[0];
    for (let i = 1; i < route.length; i++) {
      const nxt = route[i];
      const seg = dist2(cur, nxt);
      if (seg <= remain) { remain -= seg; cur = nxt; continue; }
      if (seg < 1e-9) { cur = nxt; continue; }
      const k = remain / seg;
      return [cur[0] + (nxt[0] - cur[0]) * k, cur[1] + (nxt[1] - cur[1]) * k];
    }
    return cur.slice();
  }

  // 平面坐标 → 屏幕坐标（正交 45°）
  function project(x, y) {
    const cx = plan ? plan.size[0] / 2 : 0;
    const cy = plan ? plan.size[1] / 2 : 0;
    const dx = x - cx, dy = y - cy;
    const rx = dx * Math.cos(ROT) - dy * Math.sin(ROT);
    const ry = dx * Math.sin(ROT) + dy * Math.cos(ROT);
    return [offX + (cx + rx) * scale, offY + (cy + ry) * COS * scale];
  }

  // ------------------------------------------------------------ 光
  function lightFor(t) {
    const d = new Date(t * 1000);
    const h = HOUR_LOCK != null ? HOUR_LOCK : d.getHours() + d.getMinutes() / 60;
    const asleep = !!(state && state.her.asleep);
    let amb, sun = null, lamp = 0, moon = 0, mul = null;
    if (h < 5 || h >= 22) {
      amb = { c: '8,16,36', a: 0.08 };
      mul = 'rgb(142,166,210)';
      lamp = 1; moon = 0.26;
    } else if (h < 7) {
      amb = { c: '40,60,100', a: 0.16 };
      mul = 'rgb(140,158,198)';
      sun = { c: '255,170,120', a: 0.24, len: 2.3, skew: 0.46 };
      lamp = 0.5;
    } else if (h < 10) {
      amb = { c: '225,240,255', a: 0.06 };
      sun = { c: '210,235,255', a: 0.24, len: 1.6, skew: 0.30 };
    } else if (h < 15) {
      amb = { c: '240,248,255', a: 0.045 };
      sun = { c: '235,246,255', a: 0.22, len: 1.0, skew: 0.10 };
    } else if (h < 18) {
      amb = { c: '200,220,255', a: 0.07 };
      sun = { c: '235,232,255', a: 0.22, len: 1.5, skew: -0.22 };
    } else if (h < 20) {
      amb = { c: '48,40,64', a: 0.18 };
      mul = 'rgb(170,150,180)';
      sun = { c: '255,140,110', a: 0.26, len: 2.2, skew: -0.42 };
      lamp = 0.95;
    } else {
      amb = { c: '8,16,36', a: 0.08 };
      mul = 'rgb(146,170,214)';
      lamp = 1; moon = 0.24;
    }
    if (asleep) { amb = { c: '6,12,28', a: 0.22 }; mul = 'rgb(96,118,168)'; sun = null; lamp = 0.55; }
    return { key: [Math.round(h * 6), asleep ? 1 : 0].join(':'), h, amb, sun, lamp, moon, mul };
  }

  // ------------------------------------------------------------ 基础
  function roundRect(c, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    c.beginPath();
    c.moveTo(x + rr, y);
    c.arcTo(x + w, y, x + w, y + h, rr);
    c.arcTo(x + w, y + h, x, y + h, rr);
    c.arcTo(x, y + h, x, y, rr);
    c.arcTo(x, y, x + w, y, rr);
    c.closePath();
  }

  function fillRound(c, x, y, w, h, r, fill, stroke, lw) {
    roundRect(c, x, y, w, h, r);
    if (fill) { c.fillStyle = fill; c.fill(); }
    if (stroke) { c.strokeStyle = stroke; c.lineWidth = lw || 0.015; c.stroke(); }
  }

  /** 家具体块：先画侧面，再把顶面上移 h（45° 下 h 米 = h 个平面单位） */
  function block(c, f, drawTop) {
    const r = f.r;
    const h = HEIGHT[f.t] || 0;
    if (Array.isArray(r) && r.length === 4 && h > 0.03) {
      const [x, y, w, hh] = r;
      // 落地投影
      c.save();
      c.fillStyle = 'rgba(0,0,0,.45)';
      c.shadowColor = 'rgba(0,0,0,.5)';
      c.shadowBlur = 10;
      roundRect(c, x + 0.06, y + 0.1, w, hh, 0.04);
      c.fill();
      c.restore();
      // 侧面
      const g = c.createLinearGradient(0, y, 0, y + hh);
      g.addColorStop(0, MAT.sideTop);
      g.addColorStop(1, MAT.sideBottom);
      c.save();
      c.fillStyle = g;
      roundRect(c, x, y, w, hh, 0.035);
      c.fill();
      c.strokeStyle = 'rgba(103,232,249,.16)';
      c.lineWidth = 0.008;
      c.shadowColor = MAT.cyan;
      c.shadowBlur = 5;
      c.beginPath();
      c.moveTo(x + 0.02, y + hh - 0.012);
      c.lineTo(x + w - 0.02, y + hh - 0.012);
      c.stroke();
      c.restore();
      // 顶面
      c.save();
      c.translate(-h * Math.sin(ROT) * TAN, -h * Math.cos(ROT) * TAN);
      c.shadowColor = 'rgba(0,0,0,.6)';
      c.shadowBlur = 8;
      c.shadowOffsetX = 1;
      c.shadowOffsetY = 4;
      drawTop();
      // 顶面外沿冷光，强调"面"
      c.shadowBlur = 0;
      c.strokeStyle = 'rgba(103,232,249,.30)';
      c.lineWidth = 0.014;
      roundRect(c, x, y, w, hh, 0.035);
      c.stroke();
      c.restore();
    } else {
      c.save();
      if (r) {
        c.shadowColor = 'rgba(0,0,0,.55)';
        c.shadowBlur = 7;
        c.shadowOffsetY = 3;
      }
      drawTop();
      c.restore();
    }
  }

  function glowEdge(c, x1, y1, x2, y2, color = MAT.cyan, width = 0.02, alpha = 0.55) {
    c.save();
    c.strokeStyle = color;
    c.globalAlpha = alpha;
    c.lineWidth = width;
    c.shadowColor = color;
    c.shadowBlur = 10;
    c.beginPath();
    c.moveTo(x1, y1);
    c.lineTo(x2, y2);
    c.stroke();
    c.restore();
  }

  // ------------------------------------------------------------ 地面
  function panelFloor(c, rect, tones, seed) {
    const [x, y, w, h] = rect;
    const g = c.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, tones[0]);
    g.addColorStop(1, tones[1]);
    c.fillStyle = g;
    c.fillRect(x, y, w, h);

    const random = rnd(seed);
    c.strokeStyle = 'rgba(90,130,170,.18)';
    c.lineWidth = 0.016;
    for (let px = x; px <= x + w; px += 0.62) {
      c.beginPath(); c.moveTo(px, y); c.lineTo(px, y + h); c.stroke();
    }
    for (let py = y; py <= y + h; py += 0.62) {
      c.beginPath(); c.moveTo(x, py); c.lineTo(x + w, py); c.stroke();
    }
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.10)';
    c.lineWidth = 0.022;
    c.shadowColor = MAT.cyan;
    c.shadowBlur = 6;
    for (let px = x + 1.86; px < x + w; px += 2.48) {
      c.beginPath(); c.moveTo(px, y); c.lineTo(px, y + h); c.stroke();
    }
    for (let py = y + 1.86; py < y + h; py += 2.48) {
      c.beginPath(); c.moveTo(x, py); c.lineTo(x + w, py); c.stroke();
    }
    c.restore();
    for (let i = 0; i < 10; i++) {
      const px = x + random() * w;
      const py = y + random() * h;
      const lg = c.createLinearGradient(px, py, px + 0.8, py);
      lg.addColorStop(0, 'rgba(160,210,255,.05)');
      lg.addColorStop(1, 'rgba(160,210,255,0)');
      c.fillStyle = lg;
      c.fillRect(px, py, 0.8, 0.22);
    }
  }

  function grateFloor(c, rect, tones) {
    const [x, y, w, h] = rect;
    const g = c.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, tones[0]);
    g.addColorStop(1, tones[1]);
    c.fillStyle = g;
    c.fillRect(x, y, w, h);
    c.strokeStyle = 'rgba(90,130,170,.16)';
    c.lineWidth = 0.014;
    for (let px = x; px <= x + w; px += 0.46) {
      c.beginPath(); c.moveTo(px, y); c.lineTo(px, y + h); c.stroke();
    }
    for (let py = y; py <= y + h; py += 0.46) {
      c.beginPath(); c.moveTo(x, py); c.lineTo(x + w, py); c.stroke();
    }
  }

  function balconyFloor(c, rect) {
    const [x, y, w, h] = rect;
    const g = c.createLinearGradient(x, y, x, y + h);
    g.addColorStop(0, MAT.balconyFloor[0]);
    g.addColorStop(1, MAT.balconyFloor[1]);
    c.fillStyle = g;
    c.fillRect(x, y, w, h);
    c.strokeStyle = 'rgba(80,120,150,.22)';
    c.lineWidth = 0.016;
    for (let px = x; px < x + w; px += 0.38) {
      c.beginPath(); c.moveTo(px, y); c.lineTo(px, y + h); c.stroke();
    }
  }

  function floorFor(c, room) {
    const [x, y, w, h] = room.rect;
    if (room.id === 'her_room') panelFloor(c, room.rect, MAT.herFloor, 11);
    else if (room.id === 'dad_room') panelFloor(c, room.rect, MAT.dadFloor, 23);
    else if (room.id === 'living') panelFloor(c, room.rect, MAT.livingFloor, 37);
    else if (room.id === 'kitchen') grateFloor(c, room.rect, MAT.kitchenFloor);
    else if (room.id === 'toilet') grateFloor(c, room.rect, MAT.toiletFloor);
    else if (room.id === 'balcony') balconyFloor(c, room.rect);

    c.save();
    roundRect(c, x, y, w, h, 0.02);
    c.clip();
    c.strokeStyle = 'rgba(2,4,8,.55)';
    c.lineWidth = 0.22;
    roundRect(c, x, y, w, h, 0.02);
    c.stroke();
    c.restore();
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.22)';
    c.lineWidth = 0.03;
    c.shadowColor = MAT.cyan;
    c.shadowBlur = 8;
    roundRect(c, x + 0.03, y + 0.03, w - 0.06, h - 0.06, 0.02);
    c.stroke();
    c.restore();

    // 四角卡扣
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.55)';
    c.lineWidth = 0.035;
    const b = 0.24;
    for (const [cx, cy, sx, sy] of [
      [x + 0.07, y + 0.07, 1, 1],
      [x + w - 0.07, y + 0.07, -1, 1],
      [x + 0.07, y + h - 0.07, 1, -1],
      [x + w - 0.07, y + h - 0.07, -1, -1],
    ]) {
      c.beginPath();
      c.moveTo(cx + sx * b, cy);
      c.lineTo(cx, cy);
      c.lineTo(cx, cy + sy * b);
      c.stroke();
    }
    c.restore();
  }

  // ------------------------------------------------------------ 家具（顶面）
  function drawBed(c, r, tone) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.07, '#1c2a3a', 'rgba(103,232,249,.30)', 0.02);
    fillRound(c, x + 0.05, y + 0.05, w - 0.1, h - 0.1, 0.06, '#2a3a4c');
    const g = c.createLinearGradient(x, y + h * 0.26, x, y + h);
    g.addColorStop(0, '#3a4d63');
    g.addColorStop(1, '#22303f');
    fillRound(c, x + 0.07, y + h * 0.26, w - 0.14, h * 0.7, 0.05, g);
    glowEdge(c, x + 0.1, y + h * 0.27, x + w - 0.1, y + h * 0.27, MAT.cyan, 0.014, 0.35);
    fillRound(c, x + 0.13, y + 0.1, w * 0.32, 0.22, 0.07, '#2c3a4a', 'rgba(150,200,240,.25)', 0.008);
    fillRound(c, x + w * 0.55, y + 0.1, w * 0.32, 0.22, 0.07, '#263343', 'rgba(150,200,240,.25)', 0.008);
    glowEdge(c, x + 0.08, y + 0.05, x + w - 0.08, y + 0.05, tone ? MAT.cyan : MAT.blue, 0.02, 0.55);
    c.fillStyle = tone ? 'rgba(40,120,140,.35)' : 'rgba(40,80,110,.35)';
    roundRect(c, x + 0.06, y + h - 0.48, w - 0.12, 0.3, 0.04);
    c.fill();
    glowEdge(c, x + 0.06, y + h - 0.48, x + w - 0.06, y + h - 0.48, MAT.cyan, 0.012, 0.25);
  }

  function drawSofa(c, r, face) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.06, '#243444', 'rgba(103,232,249,.22)', 0.014);
    const backW = 0.15;
    if (face === 'left') {
      fillRound(c, x + w - backW, y + 0.05, backW - 0.02, h - 0.1, 0.05, '#2c4054');
      fillRound(c, x + 0.06, y + 0.08, w - backW - 0.12, (h - 0.2) / 2, 0.06, '#2c4054');
      fillRound(c, x + 0.06, y + h / 2 + 0.02, w - backW - 0.12, (h - 0.2) / 2, 0.06, '#2c4054');
      glowEdge(c, x + 0.06, y + h / 2, x + w - backW - 0.06, y + h / 2, MAT.cyan, 0.012, 0.3);
    }
  }

  function drawRug(c, f) {
    const r = f.r;
    if (r) {
      const [x, y, w, h] = r;
      fillRound(c, x, y, w, h, 0.12, 'rgba(28,44,60,.55)', 'rgba(103,232,249,.18)', 0.015);
      c.strokeStyle = 'rgba(103,232,249,.10)';
      c.lineWidth = 0.02;
      roundRect(c, x + 0.12, y + 0.12, w - 0.24, h - 0.24, 0.1);
      c.stroke();
    } else {
      const { x, y } = f;
      const rx = f.rx || 0.6, ry = f.ry || 0.45;
      c.save();
      c.beginPath();
      c.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
      c.fillStyle = 'rgba(28,44,60,.5)';
      c.fill();
      c.strokeStyle = 'rgba(103,232,249,.16)';
      c.lineWidth = 0.015;
      c.stroke();
      c.restore();
    }
  }

  function drawDesk(c, r) {
    const [x, y, w, h] = r;
    const g = c.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, '#2c3c4e');
    g.addColorStop(1, '#1b2836');
    fillRound(c, x, y, w, h, 0.02, g, 'rgba(103,232,249,.22)', 0.012);
    c.strokeStyle = 'rgba(160,210,245,.10)';
    c.lineWidth = 0.008;
    c.beginPath();
    c.moveTo(x + 0.04, y + h - 0.06);
    c.lineTo(x + w - 0.04, y + h - 0.06);
    c.stroke();
  }

  function drawMonitor(c, r, on) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.015, '#060a0f', 'rgba(103,232,249,.35)', 0.008);
    if (on) {
      c.save();
      c.fillStyle = 'rgba(103,232,249,.55)';
      c.shadowColor = MAT.cyan;
      c.shadowBlur = 14;
      c.fillRect(x + 0.03, y + 0.02, w - 0.06, Math.max(0.03, h - 0.04));
      c.restore();
    }
  }

  function drawChair(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.07, '#151e28', 'rgba(103,232,249,.18)', 0.01);
    fillRound(c, x + 0.06, y + 0.05, w - 0.12, h - 0.12, 0.05, '#2b3c4d');
  }

  function drawShelf(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.02, '#1e2a38', 'rgba(103,232,249,.22)', 0.012);
    const vertical = h > w;
    const span = vertical ? h : w;
    const lines = Math.max(2, Math.floor(span / 0.32));
    c.strokeStyle = 'rgba(4,8,12,.7)';
    c.lineWidth = 0.012;
    for (let i = 1; i < lines; i++) {
      const p = i / lines;
      c.beginPath();
      if (vertical) { c.moveTo(x + 0.03, y + h * p); c.lineTo(x + w - 0.03, y + h * p); }
      else { c.moveTo(x + w * p, y + 0.03); c.lineTo(x + w * p, y + h - 0.03); }
      c.stroke();
    }
    const colors = ['#2f6f7a', '#4a5f8a', '#6b4a7a', '#8a6a3a', '#35607a'];
    for (let i = 0; i < 9; i++) {
      const p = (i + 0.5) / 9;
      c.fillStyle = colors[i % colors.length];
      c.globalAlpha = 0.9;
      if (vertical) c.fillRect(x + 0.05, y + 0.06 + p * (h - 0.16), w - 0.1, 0.02);
      else c.fillRect(x + 0.06 + p * (w - 0.16), y + 0.05, 0.02, h - 0.1);
    }
    c.globalAlpha = 1;
    glowEdge(c, x + 0.02, y + 0.02, x + w - 0.02, y + 0.02, MAT.cyan, 0.012, 0.3);
  }

  function drawWardrobe(c, r) {
    const [x, y, w, h] = r;
    const g = c.createLinearGradient(x, y, x + w, y);
    g.addColorStop(0, '#18222e');
    g.addColorStop(1, '#24313f');
    fillRound(c, x, y, w, h, 0.02, g, 'rgba(103,232,249,.18)', 0.012);
    c.strokeStyle = 'rgba(103,232,249,.14)';
    c.lineWidth = 0.01;
    c.beginPath(); c.moveTo(x + w / 2, y + 0.04); c.lineTo(x + w / 2, y + h - 0.04); c.stroke();
  }

  function drawLamp(c, f) {
    const r = f.r || 0.14;
    c.save();
    const g = c.createRadialGradient(f.x, f.y, 0, f.x, f.y, r * 3.4);
    g.addColorStop(0, 'rgba(103,232,249,.55)');
    g.addColorStop(1, 'rgba(103,232,249,0)');
    c.fillStyle = g;
    c.beginPath(); c.arc(f.x, f.y, r * 3.4, 0, Math.PI * 2); c.fill();
    c.fillStyle = '#dff8ff';
    c.beginPath(); c.arc(f.x, f.y, r * 0.55, 0, Math.PI * 2); c.fill();
    c.strokeStyle = MAT.cyan;
    c.lineWidth = 0.012;
    c.beginPath(); c.arc(f.x, f.y, r, 0, Math.PI * 2); c.stroke();
    c.restore();
  }

  function drawPlant(c, f) {
    const r = f.r || 0.2;
    c.save();
    c.fillStyle = '#16302c';
    c.beginPath(); c.arc(f.x, f.y, r * 0.55, 0, Math.PI * 2); c.fill();
    const leaf = ['#2e6b5e', '#3a8a72', '#245a50'];
    for (let i = 0; i < 7; i++) {
      const a = (i / 7) * Math.PI * 2 + 0.5;
      c.fillStyle = leaf[i % leaf.length];
      c.beginPath();
      c.arc(f.x + Math.cos(a) * r * 0.55, f.y + Math.sin(a) * r * 0.55, r * 0.42, 0, Math.PI * 2);
      c.fill();
    }
    c.restore();
  }

  function drawCoffee(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.05, 'rgba(20,40,56,.75)', 'rgba(103,232,249,.30)', 0.012);
    fillRound(c, x + 0.07, y + 0.07, w - 0.14, h - 0.14, 0.04, 'rgba(8,20,30,.7)');
  }

  function drawTable(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.05, 'rgba(18,34,48,.85)', 'rgba(103,232,249,.28)', 0.014);
    c.strokeStyle = 'rgba(160,210,245,.10)';
    c.lineWidth = 0.012;
    roundRect(c, x + 0.09, y + 0.09, w - 0.18, h - 0.18, 0.04);
    c.stroke();
  }

  function drawTv(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.02, '#0d141c', 'rgba(103,232,249,.25)', 0.012);
    c.save();
    c.fillStyle = 'rgba(56,189,248,.35)';
    c.shadowColor = MAT.blue;
    c.shadowBlur = 12;
    c.fillRect(x + 0.08, y + 0.1, 0.05, h - 0.2);
    c.restore();
  }

  function drawCabinet(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.02, '#22303f', 'rgba(103,232,249,.18)', 0.012);
    c.strokeStyle = 'rgba(103,232,249,.10)';
    c.lineWidth = 0.008;
    const n = Math.max(1, Math.round(Math.max(w, h) / 0.42));
    for (let i = 1; i < n; i++) {
      const p = i / n;
      c.beginPath();
      if (w >= h) { c.moveTo(x + w * p, y + 0.04); c.lineTo(x + w * p, y + h - 0.04); }
      else { c.moveTo(x + 0.04, y + h * p); c.lineTo(x + w - 0.04, y + h * p); }
      c.stroke();
    }
  }

  function drawCounter(c, r) {
    const [x, y, w, h] = r;
    const g = c.createLinearGradient(x, y, x + w, y);
    g.addColorStop(0, '#2b3642');
    g.addColorStop(1, '#1a242f');
    fillRound(c, x, y, w, h, 0.02, g, 'rgba(103,232,249,.20)', 0.012);
    c.strokeStyle = 'rgba(160,210,245,.08)';
    c.lineWidth = 0.008;
    for (let i = 1; i < 4; i++) {
      const p = i / 4;
      c.beginPath(); c.moveTo(x + 0.05, y + h * p); c.lineTo(x + w - 0.05, y + h * p); c.stroke();
    }
  }

  function drawSink(c, f) {
    c.save();
    c.fillStyle = '#0c141c';
    c.beginPath(); c.ellipse(f.x, f.y, (f.rx || 0.2) + 0.04, (f.ry || 0.15) + 0.04, 0, 0, Math.PI * 2); c.fill();
    c.fillStyle = '#9fc4d8';
    c.beginPath(); c.ellipse(f.x, f.y, f.rx || 0.2, f.ry || 0.15, 0, 0, Math.PI * 2); c.fill();
    c.fillStyle = '#4b6b7c';
    c.beginPath(); c.ellipse(f.x, f.y, (f.rx || 0.2) * 0.7, (f.ry || 0.15) * 0.7, 0, 0, Math.PI * 2); c.fill();
    c.restore();
  }

  function drawStove(c, f) {
    c.save();
    const rr = 0.16;
    c.fillStyle = '#070d13';
    c.beginPath(); c.arc(f.x, f.y, rr + 0.05, 0, Math.PI * 2); c.fill();
    for (let i = 0; i < 4; i++) {
      const a = (i / 4) * Math.PI * 2;
      const px = f.x + Math.cos(a) * rr;
      const py = f.y + Math.sin(a) * rr;
      c.strokeStyle = 'rgba(103,232,249,.65)';
      c.lineWidth = 0.012;
      c.shadowColor = MAT.cyan;
      c.shadowBlur = 8;
      c.beginPath(); c.arc(px, py, 0.045, 0, Math.PI * 2); c.stroke();
      c.shadowBlur = 0;
    }
    c.restore();
  }

  function drawFridge(c, r) {
    const [x, y, w, h] = r;
    const g = c.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, '#3a4654');
    g.addColorStop(1, '#222d39');
    fillRound(c, x, y, w, h, 0.03, g, 'rgba(103,232,249,.20)', 0.012);
    c.strokeStyle = 'rgba(103,232,249,.18)';
    c.lineWidth = 0.01;
    c.beginPath(); c.moveTo(x + 0.04, y + h * 0.42); c.lineTo(x + w - 0.04, y + h * 0.42); c.stroke();
  }

  function drawToilet(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h * 0.3, 0.03, MAT.ceramic);
    c.fillStyle = '#e2ecf2';
    c.beginPath();
    c.ellipse(x + w / 2, y + h * 0.64, w * 0.44, h * 0.3, 0, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#9fb6c4';
    c.beginPath();
    c.ellipse(x + w / 2, y + h * 0.62, w * 0.28, h * 0.18, 0, 0, Math.PI * 2);
    c.fill();
    glowEdge(c, x + 0.05, y + h * 0.3, x + w - 0.05, y + h * 0.3, MAT.cyan, 0.01, 0.3);
  }

  function drawVanity(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.03, '#1a2532', 'rgba(103,232,249,.18)', 0.012);
    c.fillStyle = 'rgba(190,230,250,.10)';
    c.fillRect(x + 0.04, y + 0.04, w - 0.08, 0.04);
  }

  function drawShower(c, r) {
    const [x, y, w, h] = r;
    c.save();
    c.fillStyle = 'rgba(80,180,220,.08)';
    c.fillRect(x, y, w, h);
    c.setLineDash([0.08, 0.06]);
    c.strokeStyle = 'rgba(103,232,249,.45)';
    c.lineWidth = 0.02;
    c.shadowColor = MAT.cyan;
    c.shadowBlur = 8;
    c.strokeRect(x, y, w, h);
    c.setLineDash([]);
    c.fillStyle = 'rgba(200,240,255,.4)';
    for (let i = 0; i < 3; i++) {
      c.beginPath();
      c.arc(x + w * (0.25 + i * 0.25), y + h * 0.5, 0.018, 0, Math.PI * 2);
      c.fill();
    }
    c.restore();
  }

  function drawTub(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.14, '#c6d3dd', 'rgba(103,232,249,.25)', 0.014);
    fillRound(c, x + 0.08, y + 0.08, w - 0.16, h - 0.16, 0.1, '#8ea4b4');
  }

  function drawTowel(c, r) {
    const [x, y, w, h] = r;
    fillRound(c, x, y, w, h, 0.02, '#3a4a58', null);
  }

  function drawRail(c, a, b) {
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.40)';
    c.lineWidth = 0.04;
    c.shadowColor = MAT.cyan;
    c.shadowBlur = 8;
    c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke();
    c.shadowBlur = 0;
    c.lineWidth = 0.016;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const n = Math.max(2, Math.floor(len / 0.45));
    for (let i = 0; i <= n; i++) {
      const k = i / n;
      const px = a[0] + (b[0] - a[0]) * k;
      const py = a[1] + (b[1] - a[1]) * k;
      c.beginPath(); c.moveTo(px, py - 0.08); c.lineTo(px, py + 0.08); c.stroke();
    }
    c.restore();
  }

  function drawRack(c, r) {
    const [x, y, w, h] = r;
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.30)';
    c.lineWidth = 0.014;
    c.strokeRect(x, y, w, h);
    c.beginPath(); c.moveTo(x, y + h / 2); c.lineTo(x + w, y + h / 2); c.stroke();
    for (let i = 1; i < 4; i++) {
      const px = x + (w * i) / 4;
      c.beginPath(); c.moveTo(px, y); c.lineTo(px, y + h); c.stroke();
    }
    c.restore();
  }

  function drawItem(c, f) {
    switch (f.t) {
      case 'bed': drawBed(c, f.r, f.note === '她的床'); break;
      case 'sofa': drawSofa(c, f.r, f.face); break;
      case 'desk': drawDesk(c, f.r); break;
      case 'monitor': drawMonitor(c, f.r, state && state.her.room === 'her_room'); break;
      case 'chair': drawChair(c, f.r); break;
      case 'shelf': drawShelf(c, f.r); break;
      case 'wardrobe': drawWardrobe(c, f.r); break;
      case 'lamp': drawLamp(c, f); break;
      case 'plant': drawPlant(c, f); break;
      case 'coffee': drawCoffee(c, f.r); break;
      case 'table': drawTable(c, f.r); break;
      case 'tv': drawTv(c, f.r); break;
      case 'cabinet': drawCabinet(c, f.r); break;
      case 'counter': drawCounter(c, f.r); break;
      case 'sink': drawSink(c, f); break;
      case 'stove': drawStove(c, f); break;
      case 'fridge': drawFridge(c, f.r); break;
      case 'toilet': drawToilet(c, f.r); break;
      case 'vanity': drawVanity(c, f.r); break;
      case 'shower': drawShower(c, f.r); break;
      case 'tub': drawTub(c, f.r); break;
      case 'towel': drawTowel(c, f.r); break;
      case 'rail': drawRail(c, f.a, f.b); break;
      case 'rack': drawRack(c, f.r); break;
      default: break;
    }
  }

  function drawFurniture(c) {
    // 先地毯（平的），再按"南边"从远到近画体块，近的压住远的
    for (const f of plan.furniture) if (f.t === 'rug') drawRug(c, f);
    const items = plan.furniture
      .filter(f => f.t !== 'rug')
      .slice()
      .sort((a, b) => {
        const ay = Array.isArray(a.r) ? a.r[1] + a.r[3] : (a.y || 0);
        const by = Array.isArray(b.r) ? b.r[1] + b.r[3] : (b.y || 0);
        return ay - by;
      });
    for (const f of items) {
      if (Array.isArray(f.r) && f.r.length === 4) {
        block(c, f, () => drawItem(c, f));
      } else {
        drawItem(c, f);
      }
    }
  }

  // ------------------------------------------------------------ 窗与门
  function drawWindows(c) {
    for (const win of plan.windows) {
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      const horiz = Math.abs(ay - by) < 0.01;
      c.save();
      c.strokeStyle = 'rgba(103,232,249,.22)';
      c.lineWidth = 0.14;
      c.beginPath(); c.moveTo(ax, ay); c.lineTo(bx, by); c.stroke();
      c.strokeStyle = '#05080c';
      c.lineWidth = 0.045;
      c.beginPath(); c.moveTo(ax, ay); c.lineTo(bx, by); c.stroke();
      c.strokeStyle = 'rgba(103,232,249,.35)';
      c.lineWidth = 0.018;
      c.shadowColor = MAT.cyan;
      c.shadowBlur = 6;
      const n = Math.max(1, Math.floor(Math.hypot(bx - ax, by - ay) / 0.9));
      for (let i = 1; i < n; i++) {
        const k = i / n;
        const px = ax + (bx - ax) * k;
        const py = ay + (by - ay) * k;
        c.beginPath();
        if (horiz) { c.moveTo(px, py - 0.06); c.lineTo(px, py + 0.06); }
        else { c.moveTo(px - 0.06, py); c.lineTo(px + 0.06, py); }
        c.stroke();
      }
      c.restore();
    }
  }

  function drawDoor(c, d) {
    const t = 0.25;
    const gap = 'rgba(4,8,12,.96)';
    c.save();
    if (d.sliding) {
      const [x, y, w] = [d.x, d.y, d.w];
      c.fillStyle = gap;
      c.fillRect(x, y, w, t);
      c.strokeStyle = 'rgba(103,232,249,.35)';
      c.lineWidth = 0.02;
      c.shadowColor = MAT.cyan;
      c.shadowBlur = 6;
      for (let i = 1; i < 4; i++) {
        const px = x + (w * i) / 4;
        c.beginPath(); c.moveTo(px, y + 0.03); c.lineTo(px, y + t - 0.03); c.stroke();
      }
      c.restore();
      return;
    }
    if (d.dir === 'v') {
      c.fillStyle = gap;
      c.fillRect(d.x, d.y, t, d.w);
      c.strokeStyle = 'rgba(103,232,249,.40)';
      c.lineWidth = 0.03;
      c.beginPath();
      c.moveTo(d.x + t / 2, d.y);
      c.lineTo(d.x + t / 2, d.y + d.w);
      c.stroke();
    } else {
      c.fillStyle = gap;
      c.fillRect(d.x, d.y, d.w, t);
      c.strokeStyle = 'rgba(103,232,249,.40)';
      c.lineWidth = 0.03;
      c.beginPath();
      c.moveTo(d.x, d.y + t / 2);
      c.lineTo(d.x + d.w, d.y + t / 2);
      c.stroke();
    }
    c.restore();
  }

  // ------------------------------------------------------------ 光照
  function drawSun(c, sun) {
    if (!sun) return;
    for (const win of plan.windows) {
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      const horiz = Math.abs(ay - by) < 0.01;
      let dx = 0, dy = 0;
      if (horiz) dy = ay < 4 ? 1 : -1;
      else dx = ax > 6 ? -1 : 1;
      const L = sun.len;
      const skew = sun.skew * L;
      const px = (ax + bx) / 2, py = (ay + by) / 2;
      const g = c.createLinearGradient(px, py, px + dx * L + skew, py + dy * L);
      g.addColorStop(0, `rgba(${sun.c},${sun.a})`);
      g.addColorStop(0.55, `rgba(${sun.c},${sun.a * 0.35})`);
      g.addColorStop(1, `rgba(${sun.c},0)`);
      c.save();
      c.globalCompositeOperation = 'lighter';
      c.fillStyle = g;
      c.beginPath();
      c.moveTo(ax, ay);
      c.lineTo(bx, by);
      c.lineTo(bx + dx * L + skew, by + dy * L);
      c.lineTo(ax + dx * L + skew, ay + dy * L);
      c.closePath();
      c.fill();
      c.restore();
    }
  }

  function drawLamps(c, strength) {
    if (strength <= 0.02) return;
    for (const f of plan.furniture) {
      if (f.t !== 'lamp') continue;
      const g = c.createRadialGradient(f.x, f.y, 0, f.x, f.y, 1.3);
      g.addColorStop(0, `rgba(120,220,255,${0.28 * strength})`);
      g.addColorStop(0.55, `rgba(80,190,240,${0.10 * strength})`);
      g.addColorStop(1, 'rgba(80,190,240,0)');
      c.save();
      c.globalCompositeOperation = 'lighter';
      c.fillStyle = g;
      c.beginPath(); c.arc(f.x, f.y, 1.3, 0, Math.PI * 2); c.fill();
      c.restore();
    }
  }

  function drawMoon(c, strength) {
    if (!strength) return;
    for (const win of plan.windows) {
      if (win.kind !== 'city') continue;
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      const horiz = Math.abs(ay - by) < 0.01;
      const dx = horiz ? 0 : (ax > 6 ? -1 : 1);
      const dy = horiz ? (ay < 4 ? 1 : -1) : 0;
      const L = 1.5;
      const g = c.createLinearGradient(ax, ay, ax + dx * L, ay + dy * L);
      g.addColorStop(0, `rgba(110,180,255,${strength})`);
      g.addColorStop(1, 'rgba(110,180,255,0)');
      c.save();
      c.globalCompositeOperation = 'lighter';
      c.fillStyle = g;
      c.beginPath();
      c.moveTo(ax, ay);
      c.lineTo(bx, by);
      c.lineTo(bx + dx * L, by + dy * L);
      c.lineTo(ax + dx * L, ay + dy * L);
      c.closePath();
      c.fill();
      c.restore();
    }
  }

  // ------------------------------------------------------------ 缓存与绘制
  const cache = document.createElement('canvas');
  const cacheCtx = cache.getContext('2d');
  let cacheKey = '';

  function renderPlan(light) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (cache.width !== canvas.width || cache.height !== canvas.height) {
      cache.width = canvas.width;
      cache.height = canvas.height;
    }
    const c = cacheCtx;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, cache.width, cache.height);
    const [W, H] = plan.size;
    const [sx, sy, sw, sh] = plan.slab;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.translate(offX, offY);
    c.scale(scale, scale * COS);   // 地面在屏幕上压扁，45°
    c.translate(W / 2, H / 2);
    c.rotate(ROT);
    c.translate(-W / 2, -H / 2);

    // 底座侧面（平台厚度）
    c.save();
    roundRect(c, sx, sy + 0.22, sw, sh, 0.18);
    c.fillStyle = '#04080c';
    c.fill();
    c.strokeStyle = 'rgba(103,232,249,.18)';
    c.lineWidth = 0.02;
    c.stroke();
    c.restore();

    // 平台顶面
    c.save();
    c.shadowColor = 'rgba(0,0,0,.85)';
    c.shadowBlur = 30;
    c.shadowOffsetY = 12;
    roundRect(c, sx, sy, sw, sh, 0.18);
    const wallG = c.createLinearGradient(0, 0, 0, H);
    wallG.addColorStop(0, MAT.wallTop);
    wallG.addColorStop(1, MAT.wallBottom);
    c.fillStyle = wallG;
    c.fill();
    c.restore();
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.45)';
    c.lineWidth = 0.045;
    c.shadowColor = MAT.cyan;
    c.shadowBlur = 12;
    roundRect(c, sx + 0.03, sy + 0.03, sw - 0.06, sh - 0.06, 0.16);
    c.stroke();
    c.restore();

    for (const room of plan.rooms) floorFor(c, room);
    drawFurniture(c);
    drawWindows(c);
    for (const d of plan.doors) drawDoor(c, d);

    if (light.mul) {
      c.save();
      c.globalCompositeOperation = 'multiply';
      c.fillStyle = light.mul;
      c.fillRect(sx, sy, sw, sh);
      c.restore();
    }
    c.save();
    c.fillStyle = `rgba(${light.amb.c},${light.amb.a})`;
    c.fillRect(sx, sy, sw, sh);
    c.restore();
    drawSun(c, light.sun);
    drawLamps(c, light.lamp);
    drawMoon(c, light.moon);
    if (light.lamp > 0.3) {
      const topG = c.createLinearGradient(sx, sy, sx, sy + sh);
      topG.addColorStop(0, `rgba(120,180,235,${0.06 * light.lamp})`);
      topG.addColorStop(1, 'rgba(120,180,235,0)');
      c.save();
      c.globalCompositeOperation = 'lighter';
      c.fillStyle = topG;
      c.fillRect(sx, sy, sw, sh);
      c.restore();
    }

    // 全息网格
    c.save();
    c.strokeStyle = 'rgba(103,232,249,.045)';
    c.lineWidth = 0.01;
    for (let px = sx; px <= sx + sw; px += 0.6) {
      c.beginPath(); c.moveTo(px, sy); c.lineTo(px, sy + sh); c.stroke();
    }
    for (let py = sy; py <= sy + sh; py += 0.6) {
      c.beginPath(); c.moveTo(sx, py); c.lineTo(sx + sw, py); c.stroke();
    }
    c.restore();

    const vg = c.createRadialGradient(W * 0.5, H * 0.45, Math.min(W, H) * 0.32,
      W * 0.5, H * 0.5, Math.max(W, H) * 0.78);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,.38)');
    c.fillStyle = vg;
    c.fillRect(sx, sy, sw, sh);
  }

  function resize() {
    if (!plan) return;
    const rect = stage.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    const pad = rect.width < 640 ? 10 : 22;
    const [W, H] = plan.size;
    const ac = Math.abs(Math.cos(ROT)), as = Math.abs(Math.sin(ROT));
    const bw = W * ac + H * as;
    const bh = (W * as + H * ac) * COS;
    scale = Math.min((rect.width - pad * 2) / bw, (rect.height - pad * 2) / bh);
    offX = rect.width / 2 - (W / 2) * scale;
    offY = rect.height / 2 - (H / 2) * COS * scale;
    cacheKey = '';
  }

  // ------------------------------------------------------------ TA
  function moodColor() {
    if (!state) return MAT.cyan;
    const m = state.mood;
    if (state.her.asleep) return '#8fa8d8';
    if (m.anger > 0.45) return '#ff7b7b';
    if (m.toilet) return MAT.amber;
    if (m.sad > 0.5) return '#9aa8d8';
    if (m.valence > 0.25) return '#ffd479';
    return MAT.cyan;
  }

  function drawLabels() {
    for (const room of plan.rooms) {
      if (room.hideLabel) continue;
      const [x, y] = room.rect;
      const lx = room.labelPos ? room.labelPos[0] : x + 0.16;
      const ly = room.labelPos ? room.labelPos[1] : y + 0.38;
      const [px, py] = project(lx, ly);
      const active = focus && focus.id === room.id && focus.until > now();
      const fs = (active ? 0.2 : 0.17) * scale;
      ctx.font = `${fs}px Consolas,"Microsoft YaHei",monospace`;
      const text = '[' + room.name + ']';
      const tw = ctx.measureText(text).width;
      fillRound(ctx, px - 6, py - fs - 4, tw + 12, fs + 8, 4,
        'rgba(4,10,16,.72)', 'rgba(103,232,249,.22)', 1);
      ctx.fillStyle = active ? 'rgba(190,245,255,1)' : 'rgba(150,215,235,.85)';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText(text, px, py);
    }
    if (plan.zones) {
      ctx.fillStyle = 'rgba(140,200,225,.32)';
      for (const z of plan.zones) {
        const [px, py] = project(z.x, z.y);
        ctx.font = `${0.15 * scale}px Consolas,monospace`;
        ctx.fillText('[ ' + z.text + ' ]', px, py);
      }
    }
  }

  function drawBubble(px, py, text, accent) {
    ctx.save();
    const fs = 0.2 * scale;
    ctx.font = `${fs}px "Microsoft YaHei", sans-serif`;
    const w = ctx.measureText(text).width + 18;
    const h = fs + 12;
    const bx = px - w / 2;
    const by = py - h - 16;
    fillRound(ctx, bx, by, w, h, 6, 'rgba(4,10,16,.9)', accent, 1);
    ctx.fillStyle = '#dff8ff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, px, by + h / 2 + 1);
    ctx.beginPath();
    ctx.moveTo(px - 5, by + h);
    ctx.lineTo(px + 5, by + h);
    ctx.lineTo(px, by + h + 8);
    ctx.closePath();
    ctx.fillStyle = 'rgba(4,10,16,.9)';
    ctx.fill();
    ctx.restore();
  }

  function drawHer(t) {
    if (!state) return;
    const her = state.her;
    const [x, y] = routePos(her.route, her.route_at, her.speed, t);
    const [px, py] = project(x, y);
    const col = moodColor();
    const R = 0.31 * scale;
    const bob = Math.sin(t * 2.4) * 0.012 * scale;

    // 脚下光斑（椭圆，压扁）
    ctx.save();
    const lamp = ctx.createRadialGradient(px, py + 6, 2, px, py + 6, R * 3);
    lamp.addColorStop(0, 'rgba(103,232,249,.14)');
    lamp.addColorStop(1, 'rgba(103,232,249,0)');
    ctx.fillStyle = lamp;
    ctx.beginPath();
    ctx.ellipse(px, py + 6, R * 3, R * 2.2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // 影子
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,.5)';
    ctx.beginPath();
    ctx.ellipse(px, py + 10, R * 0.95, R * 0.34, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // 外环
    ctx.save();
    const grad = ctx.createRadialGradient(px, py, R * 0.3, px, py, R * 2.3);
    grad.addColorStop(0, 'rgba(103,232,249,.18)');
    grad.addColorStop(1, 'rgba(103,232,249,0)');
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.arc(px, py, R * 2.3, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = col;
    ctx.lineWidth = 2.4;
    ctx.shadowColor = col;
    ctx.shadowBlur = 18;
    ctx.beginPath(); ctx.arc(px, py + bob, R * 1.06, 0, Math.PI * 2); ctx.stroke();
    ctx.restore();

    // 头像
    ctx.save();
    ctx.beginPath();
    ctx.arc(px, py + bob, R, 0, Math.PI * 2);
    ctx.clip();
    const s = R * 2;
    if (avatarReady) {
      ctx.drawImage(avatar, px - R, py + bob - R, s, s);
    } else {
      ctx.fillStyle = '#0a141e';
      ctx.fillRect(px - R, py + bob - R, s, s);
      ctx.fillStyle = 'rgba(103,232,249,.5)';
      ctx.beginPath();
      ctx.ellipse(px, py + bob, R * 0.58, R * 0.32, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // 名牌
    ctx.save();
    const fs = 0.17 * scale;
    ctx.font = `${fs}px Consolas,"Microsoft YaHei",monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const label = 'TA';
    const nw = ctx.measureText(label).width + 14;
    const nh = fs + 10;
    const ny = py + R + 8;
    const nearBottom = ny + nh > canvas.height / (Math.min(2, window.devicePixelRatio || 1)) - 10;
    const nx = nearBottom ? px + R * 1.6 : px;
    const nyy = nearBottom ? py - R - nh - 4 : ny;
    fillRound(ctx, nx - nw / 2, nyy, nw, nh, 5,
      'rgba(4,10,16,.8)', 'rgba(103,232,249,.35)', 1);
    ctx.fillStyle = 'rgba(190,245,255,.95)';
    ctx.fillText(label, nx, nyy + 4);
    ctx.restore();

    if (her.activity) drawBubble(px, py - R, her.activity, 'rgba(103,232,249,.30)');

    if (her.asleep) {
      ctx.save();
      const zf = 0.2 * scale;
      ctx.font = `${zf}px "Microsoft YaHei", sans-serif`;
      ctx.fillStyle = 'rgba(190,235,255,.9)';
      for (let i = 0; i < 3; i++) {
        const k = (t * 0.5 + i * 0.33) % 1;
        ctx.globalAlpha = (1 - k) * 0.85;
        ctx.fillText('z', px + R * 1.5 + k * R * 0.6, py - R - k * R * 1.1);
      }
      ctx.restore();
    }
  }

  // ------------------------------------------------------------ 主绘制
  function draw() {
    if (!plan) return;
    const rect = stage.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(rect.width * dpr) ||
        canvas.height !== Math.round(rect.height * dpr)) {
      resize();
    }
    const t = now();
    const light = lightFor(t);
    if (light.key !== cacheKey) {
      renderPlan(light);
      cacheKey = light.key;
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (cache.width) ctx.drawImage(cache, 0, 0);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawLabels();

    if (focus && focus.until > t) {
      const room = plan.rooms.find(r => r.id === focus.id);
      if (room) {
        const [W, H] = plan.size;
        ctx.save();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.translate(offX, offY);
        ctx.scale(scale, scale * COS);
        ctx.translate(W / 2, H / 2);
        ctx.rotate(ROT);
        ctx.translate(-W / 2, -H / 2);
        ctx.strokeStyle = 'rgba(103,232,249,.9)';
        ctx.lineWidth = 0.05;
        ctx.shadowColor = MAT.cyan;
        ctx.shadowBlur = 16;
        roundRect(ctx, room.rect[0], room.rect[1], room.rect[2], room.rect[3], 0.04);
        ctx.stroke();
        ctx.restore();
      }
    }

    drawHer(t);
  }

  function loop() {
    draw();
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ 面板
  const $ = id => document.getElementById(id);

  function setBar(id, value, digits = 0) {
    const v = Math.max(0, Math.min(1, value || 0));
    const bar = $('b-' + id);
    const num = $('v-' + id);
    if (bar) bar.style.width = (v * 100).toFixed(1) + '%';
    if (num) num.textContent = digits ? v.toFixed(digits) : Math.round(v * 100) + '%';
  }

  function updatePanel() {
    if (!state) return;
    const m = state.mood;
    $('where').textContent = state.her.room_name || '——';
    $('activity').textContent = state.her.activity || '——';
    $('emotion').textContent = m.emotion || tr("panels.calm");

    const moodValue = Math.max(0, Math.min(1, (m.valence + 1) / 2));
    setBar('hunger', m.hunger);
    setBar('thirst', m.thirst);
    setBar('bowel', m.bowel);
    setBar('bladder', m.bladder);
    setBar('energy', m.energy);
    setBar('mood', moodValue);

    const dadStatus = $('user-status');
    const dadHint = $('user-hint');
    if (state.env.video) {
      dadStatus.textContent = tr("panels.video_active");
      dadHint.textContent = tr("panels.company");
    } else if (state.env.dad_talking) {
      dadStatus.textContent = tr("panels.just_talked");
      dadHint.textContent = '';
    } else {
      const mins = Math.round(state.env.silence_min);
      dadStatus.textContent = mins < 1 ? tr("panels.just_talked") : tr("panels.silence_minutes", {minutes: mins});
      dadHint.textContent = state.env.unanswered > 0 ? tr("panels.awaiting_reply") : '';
    }

    const ev = $('events');
    const items = (state.events || []).slice(-3).reverse();
    ev.innerHTML = items.length
      ? items.map(e => `<li>${new Date(e.at * 1000).toLocaleTimeString(window.LysmorI18n.language(), { hour: '2-digit', minute: '2-digit' })} ${e.text}</li>`).join('')
      : '<li>——</li>';

    if (state.window) {
      if (state.window !== windowKey) {
        windowKey = state.window;
        bg.src = `/bg/${windowKey}.jpg`;
      }
      const names = { dawn: tr("panels.dawn"), morning: tr("panels.early_morning"), noon: tr("panels.noon"), afternoon: tr("panels.afternoon"), evening: tr("panels.evening"), night: tr("panels.late_night") };
      $('window-cap').textContent = tr("panels.outside_window_time", {time: names[windowKey] || ''});
    }
    if (bg.complete && bg.naturalWidth) $('window').src = bg.src;

    $('mode').textContent = modeName(hourOf(state.now));
  }

  window.addEventListener("lysmor:languagechange", () => { if (state) updatePanel(); });

  function tickClock() {
    const t = now();
    const d = new Date(t * 1000);
    $('clock').textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    $('mode').textContent = modeName(hourOf(t));
  }

  async function poll() {
    try {
      const resp = await fetch('/api/house', { cache: 'no-store' });
      const data = await resp.json();
      state = data;
      skew = data.now - Date.now() / 1000;
      updatePanel();
    } catch (err) { /* 保持上一帧 */ }
  }

  function onPick(ev) {
    if (!plan) return;
    const rect = canvas.getBoundingClientRect();
    const sx = (ev.clientX - rect.left - offX) / scale;
    const sy = (ev.clientY - rect.top - offY) / (scale * COS);
    const cx = plan.size[0] / 2, cy = plan.size[1] / 2;
    const dx = sx - cx, dy = sy - cy;
    const px = cx + dx * Math.cos(-ROT) - dy * Math.sin(-ROT);
    const py = cy + dx * Math.sin(-ROT) + dy * Math.cos(-ROT);
    for (const room of plan.rooms) {
      const [x, y, w, h] = room.rect;
      if (px >= x && px <= x + w && py >= y && py <= y + h) {
        focus = { id: room.id, until: now() + 3.5 };
        return;
      }
    }
  }

  async function init() {
    try {
      plan = await fetch('/plan.json', { cache: 'no-store' }).then(r => r.json());
    } catch (err) {
      document.querySelector('.hint').textContent = tr("panels.plan_failed");
      return;
    }
    resize();
    window.addEventListener('resize', resize);
    if (window.ResizeObserver) new ResizeObserver(resize).observe(stage);
    canvas.addEventListener('click', onPick);
    await poll();
    setInterval(poll, 2000);
    setInterval(tickClock, 1000);
    tickClock();
    loop();
  }

  init();
})();
