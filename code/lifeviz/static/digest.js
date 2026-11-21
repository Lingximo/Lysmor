/* 消化 · 代谢 · 排泄（2026-10-31 晚，配色第二版）
 * 风格：玻璃容器 + 发光液面，跟生命状态面板同一套霓虹色
 * 左：胃 → 小肠 → 结肠 → 厕所 ｜ 中：喝水 → 血容量 → 膀胱 ｜ 右：激素 + 代谢率
 */
(() => {
  const canvas = document.getElementById('digest-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let W = 0, H = 190;
  const DPR = Math.min(2, window.devicePixelRatio || 1);
  let lastPaint = 0;

  const C = {
    dim: 'rgba(150,180,210,.72)',
    faint: 'rgba(110,145,180,.18)',
    cyan: '#67e8f9',
    gold: '#ffd166',
    honey: '#ffcf7a',
    violet: '#c4b5fd',
    rose: '#fb7185',
    green: '#34d399',
    text: '#dff4ff',
  };

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    W = Math.max(320, box.width - 30);
    H = Number(canvas.dataset.h || 190);
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  const num = (s, k, d = 0) => {
    const v = Number(s[k]);
    return Number.isFinite(v) ? v : d;
  };
  const pct = v => Math.round(Math.max(0, Math.min(1, v)) * 100);

  function roundRect(x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }

  function label(text, x, y, color = C.dim, size = 10, align = 'left') {
    ctx.fillStyle = color;
    ctx.font = size + 'px "Microsoft YaHei","PingFang SC",sans-serif';
    ctx.textAlign = align;
    ctx.fillText(text, x, y);
  }

  function value(text, x, y, color = C.text, size = 11, align = 'left') {
    ctx.fillStyle = color;
    ctx.font = size + 'px Consolas,"Cascadia Mono",monospace';
    ctx.textAlign = align;
    ctx.fillText(text, x, y);
  }

  /** 玻璃容器：空腔 + 液体 + 发光液面 */
  function vessel(x, y, w, h, v, top, bottom, surface, radius = 10) {
    ctx.save();
    roundRect(x, y, w, h, radius);
    ctx.fillStyle = 'rgba(70,110,150,.10)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(140,185,225,.38)';
    ctx.lineWidth = 1.1;
    ctx.stroke();
    ctx.restore();

    if (v <= 0.004) return;
    const fh = h * Math.min(1, v);
    const sy = y + h - fh;
    ctx.save();
    roundRect(x, y, w, h, radius);
    ctx.clip();
    const g = ctx.createLinearGradient(0, sy, 0, y + h);
    g.addColorStop(0, top);
    g.addColorStop(1, bottom);
    ctx.fillStyle = g;
    ctx.fillRect(x, sy, w, fh);
    // 液面高光
    ctx.strokeStyle = surface;
    ctx.lineWidth = 1.6;
    ctx.shadowColor = surface;
    ctx.shadowBlur = 9;
    ctx.beginPath();
    ctx.moveTo(x + 3, sy);
    ctx.lineTo(x + w - 3, sy);
    ctx.stroke();
    ctx.restore();
  }

  function drawStomach(x, y, w, h, v) {
    vessel(x, y, w, h, v,
      'rgba(255,209,102,.55)', 'rgba(224,150,50,.30)',
      C.gold, w * 0.34);
    if (v > 0.02) {
      ctx.save();
      roundRect(x, y, w, h, w * 0.34);
      ctx.clip();
      const fh = h * v;
      ctx.fillStyle = 'rgba(255,236,170,.55)';
      for (let i = 0; i < 3; i++) {
        const px = x + w * (0.26 + 0.24 * i);
        const py = y + h - fh + 7 + ((Math.sin(performance.now() / 900 + i) + 1) * fh * 0.22);
        ctx.beginPath();
        ctx.arc(px, Math.min(y + h - 5, py), 2.3, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
  }

  function intestinePoints(x0, x1, cy) {
    const pts = [];
    const n = 56;
    for (let i = 0; i <= n; i++) {
      const k = i / n;
      pts.push([x0 + (x1 - x0) * k, cy + Math.sin(k * Math.PI * 2 * 3.0) * 11]);
    }
    return pts;
  }

  function drawIntestine(x0, x1, cy, gut) {
    const pts = intestinePoints(x0, x1, cy);
    const path = () => {
      ctx.beginPath();
      pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    };
    ctx.save();
    ctx.lineCap = 'round';
    // 管壁
    ctx.strokeStyle = 'rgba(120,160,200,.18)';
    ctx.lineWidth = 13;
    path();
    ctx.stroke();
    // 内容：蜂蜜色的光带
    if (gut > 0.005) {
      ctx.strokeStyle = `rgba(255,207,122,${0.22 + 0.55 * gut})`;
      ctx.lineWidth = 6.5;
      ctx.shadowColor = C.honey;
      ctx.shadowBlur = 10;
      path();
      ctx.stroke();
    }
    // 流动的食糜
    if (gut > 0.02) {
      ctx.shadowBlur = 0;
      const t = (performance.now() / 1000) * (0.25 + 0.55 * gut);
      ctx.fillStyle = '#ffe9a8';
      for (let i = 0; i < 7; i++) {
        const k = (t * 0.12 + i / 7) % 1;
        const p = pts[Math.floor(k * (pts.length - 1))];
        ctx.beginPath();
        ctx.arc(p[0], p[1], 2.0, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }

  function drawToilet(x, y, active) {
    ctx.save();
    if (active) {
      ctx.shadowColor = C.cyan;
      ctx.shadowBlur = 12;
    }
    ctx.strokeStyle = active ? C.cyan : 'rgba(150,190,225,.45)';
    ctx.lineWidth = 1.4;
    ctx.strokeRect(x - 8, y - 15, 16, 9);
    ctx.beginPath();
    ctx.ellipse(x, y + 3, 9, 5.5, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - 6, y + 8);
    ctx.lineTo(x - 4, y + 15);
    ctx.lineTo(x + 4, y + 15);
    ctx.lineTo(x + 6, y + 8);
    ctx.stroke();
    ctx.restore();
  }

  function drawArrow(x, y, color = 'rgba(120,165,205,.38)') {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 10, y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x + 10, y - 3);
    ctx.lineTo(x + 15, y);
    ctx.lineTo(x + 10, y + 3);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function bar(x, y, w, v, surface) {
    ctx.save();
    roundRect(x, y, w, 5, 3);
    ctx.fillStyle = 'rgba(110,170,255,.10)';
    ctx.fill();
    if (v > 0.001) {
      roundRect(x, y, Math.max(2, w * Math.max(0, Math.min(1, v))), 5, 3);
      ctx.fillStyle = surface;
      ctx.shadowColor = surface;
      ctx.shadowBlur = 6;
      ctx.fill();
    }
    ctx.restore();
  }

  function dial(cx, cy, r, v) {
    ctx.save();
    ctx.lineWidth = 5;
    ctx.strokeStyle = 'rgba(110,170,255,.12)';
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI * 0.75, Math.PI * 2.25);
    ctx.stroke();
    const frac = Math.max(0, Math.min(1, (v - 0.7) / 0.7));
    const g = ctx.createLinearGradient(cx - r, cy, cx + r, cy);
    g.addColorStop(0, '#7dd3fc');
    g.addColorStop(1, C.cyan);
    ctx.strokeStyle = g;
    ctx.shadowColor = C.cyan;
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI * 0.75, Math.PI * 0.75 + Math.PI * 1.5 * frac);
    ctx.stroke();
    ctx.restore();
    value(v.toFixed(2) + '×', cx, cy + 4, C.text, 13, 'center');
  }

  function paint(now) {
    if (!isOpen()) return;
    const s = window.__endoState || {};
    ctx.clearRect(0, 0, W, H);

    const stomach = num(s, 'stomach');
    const gut = num(s, 'gut');
    const bowel = num(s, 'bowel');
    const bladder = num(s, 'bladder');
    const needB = num(s, 'bowel_need');
    const needW = num(s, 'bladder_need');
    const fluid = num(s, 'fluid_queue');
    const blood = num(s, 'blood_volume', 0.85);
    const metab = num(s, 'metabolic_rate', 1);
    const toilet = String(s.toilet_state || '');
    const trips = num(s, 'toilet_count_today', 0);

    const leftEnd = W * 0.43;
    const midX = W * 0.455;
    const rightX = W * 0.67;

    label('消化道', 2, 12, 'rgba(160,200,235,.55)', 10);
    label('水 · 尿', midX + 2, 12, 'rgba(160,200,235,.55)', 10);
    label('胃肠激素 · 代谢', rightX, 12, 'rgba(160,200,235,.55)', 10);

    // 消化道
    drawStomach(12, 34, 50, 70, stomach);
    label('胃', 37, 120, C.dim, 10, 'center');
    value(pct(stomach) + '%', 37, 135, '#ffe1a8', 11, 'center');

    drawArrow(66, 69);
    const inX1 = leftEnd - 105;
    drawIntestine(88, inX1, 69, gut);
    label('小肠', (88 + inX1) / 2, 120, C.dim, 10, 'center');
    value(pct(gut) + '%', (88 + inX1) / 2, 135, '#ffe1a8', 11, 'center');

    drawArrow(inX1 + 8, 69);
    const colonX = leftEnd - 88;
    // 结肠：用柔和的品紫，跟面板同色系；不再用土褐
    vessel(colonX, 40, 62, 58, bowel,
      'rgba(196,181,253,.48)', 'rgba(109,82,175,.26)',
      C.violet, 12);
    label('结肠', colonX + 31, 120, C.dim, 10, 'center');
    value(pct(bowel) + '%', colonX + 31, 135, '#ddd2ff', 11, 'center');

    drawArrow(colonX + 68, 69);
    const toiletX = colonX + 92;
    drawToilet(toiletX, 64, toilet !== '');
    label('厕所', toiletX, 120, C.dim, 10, 'center');
    value(toilet === 'need' ? '要去' : (toilet === 'using' ? '在用' : '—'),
      toiletX, 135, toilet ? C.cyan : 'rgba(150,180,210,.5)', 11, 'center');

    bar(2, 152, 150, needB, C.violet);
    label('便意 ' + pct(needB) + '%', 158, 158, C.dim, 10);

    // 水 / 尿
    vessel(midX + 4, 36, 38, 68, fluid,
      'rgba(103,232,249,.45)', 'rgba(14,140,200,.26)', C.cyan, 7);
    label('饮水', midX + 23, 120, C.dim, 10, 'center');
    value(pct(fluid) + '%', midX + 23, 135, '#bff1ff', 11, 'center');

    drawArrow(midX + 46, 69);
    const bx = midX + 66;
    vessel(bx, 36, 14, 68, blood,
      'rgba(251,113,133,.5)', 'rgba(190,35,75,.28)', C.rose, 6);
    label('血容量', bx + 7, 120, C.dim, 10, 'center');
    value(pct(blood) + '%', bx + 7, 135, '#ffc9d2', 11, 'center');

    drawArrow(bx + 20, 69);
    const blx = bx + 46;
    // 膀胱：圆形容器 + 弧形液面
    ctx.save();
    ctx.beginPath();
    ctx.arc(blx, 70, 22, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(70,110,150,.10)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(140,185,225,.38)';
    ctx.lineWidth = 1.1;
    ctx.stroke();
    if (bladder > 0.004) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(blx, 70, 22, 0, Math.PI * 2);
      ctx.clip();
      const fh = 44 * bladder;
      const sy = 92 - fh;
      const g = ctx.createLinearGradient(0, sy, 0, 92);
      g.addColorStop(0, 'rgba(255,209,102,.55)');
      g.addColorStop(1, 'rgba(224,150,50,.30)');
      ctx.fillStyle = g;
      ctx.fillRect(blx - 22, sy, 44, fh);
      ctx.strokeStyle = C.gold;
      ctx.lineWidth = 1.5;
      ctx.shadowColor = C.gold;
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.moveTo(blx - 21, sy);
      ctx.lineTo(blx + 21, sy);
      ctx.stroke();
      ctx.restore();
    }
    ctx.restore();
    label('膀胱', blx, 120, C.dim, 10, 'center');
    value(pct(bladder) + '%', blx, 135, '#ffe1a8', 11, 'center');

    bar(midX + 4, 152, 150, needW, C.gold);
    label('尿意 ' + pct(needW) + '%', midX + 158, 158, C.dim, 10);

    // 激素 / 代谢
    const rows = [
      ['胃泌素', num(s, 'gastrin'), C.cyan],
      ['CCK', num(s, 'cck'), C.violet],
      ['GLP-1', num(s, 'glp1'), C.green],
      ['醛固酮', num(s, 'aldosterone'), C.rose],
      ['甲状腺', num(s, 'thyroid'), C.gold],
    ];
    rows.forEach(([name, v, color], i) => {
      const y = 28 + i * 22;
      label(name, rightX + 2, y + 5, C.dim, 10);
      bar(rightX + 62, y, 82, v, color);
      value(pct(v) + '%', rightX + 150, y + 5, '#cfe6f8', 10);
    });

    dial(W - 52, 88, 22, metab);
    label('代谢率', W - 52, 124, C.dim, 10, 'center');
    label('今天厕所 ' + trips + ' 次', W - 2, 158, C.dim, 10, 'right');
  }

  function loop(now) {
    requestAnimationFrame(loop);
    if (!isOpen()) return;
    if (now - lastPaint < 100) return;
    lastPaint = now;
    paint(now);
  }

  // 默认收起；点标题右边的按钮才展开（每次打开页面都是收起的）
  const panel = document.getElementById('digest-panel');
  const btn = document.getElementById('digest-toggle');
  const isOpen = () => !!(panel && panel.classList.contains('open'));

  function setOpen(v) {
    if (!panel) return;
    panel.classList.toggle('open', !!v);
    if (btn) {
      btn.textContent = v ? '收起 ▴' : '展开 ▾';
      btn.setAttribute('aria-expanded', String(!!v));
    }
    if (v) {
      resize();
      lastPaint = 0;
      paint(performance.now());
    }
  }

  if (btn) {
    btn.addEventListener('click', ev => {
      ev.preventDefault();
      setOpen(!isOpen());
    });
  }

  window.addEventListener('resize', resize);
  resize();
  // 调试/直达用：?digest=open 默认展开；正常打开都是收起
  const wantOpen = new URLSearchParams(location.search).get('digest') === 'open';
  setOpen(wantOpen);
  requestAnimationFrame(loop);
  setInterval(() => { if (isOpen()) paint(performance.now()); }, 1000);
})();
