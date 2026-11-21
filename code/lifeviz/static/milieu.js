/* 体内环境：睡眠压力 / 体温 / 免疫 / 疼痛 四条动态曲线。 */
(() => {
  const canvas = document.getElementById('milieu-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const SERIES = [
    { key: 'adenosine', label: '睡眠压力', color: '#818cf8', norm: v => v },
    { key: 'core_temp', label: '体温', color: '#fb923c', norm: v => (v - 36.0) / 3.0 },
    { key: 'cytokines', label: '免疫反应', color: '#4ade80', norm: v => v },
    { key: 'pain', label: '疼痛', color: '#fb7185', norm: v => v },
    { key: 'estrogen', label: '雌激素', color: '#f9a8d4', norm: v => v },
    { key: 'progesterone', label: '孕激素', color: '#c4b5fd', norm: v => v },
    // 2026-11-09 淋巴系统：回流 / 组织液 / 触痛
    { key: 'lymph_flow', label: '淋巴回流', color: '#38bdf8', norm: v => v },
    { key: 'lymph_edema', label: '组织液', color: '#a78bfa', norm: v => v },
    { key: 'lymph_tenderness', label: '淋巴触痛', color: '#f472b6', norm: v => v },
  ];
  const MAX = 60;
  const hist = {};
  SERIES.forEach(s => { hist[s.key] = []; });

  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let lastPush = 0;

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    W = Math.max(240, box.width - 30);
    H = canvas.dataset.h ? Number(canvas.dataset.h) : 170;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function push(now) {
    const s = window.__endoState;
    if (!s) return;
    if (now - lastPush < 2500) return;
    lastPush = now;
    SERIES.forEach(def => {
      const raw = Number(s[def.key]);
      if (!Number.isFinite(raw)) return;
      const v = Math.max(0, Math.min(1, def.norm(raw)));
      const arr = hist[def.key];
      if (!arr.length) for (let i = 0; i < MAX; i++) arr.push(v);
      arr.push(v);
      if (arr.length > MAX) arr.shift();
    });
  }

  function drawSeries(points, x, y, w, h, color) {
    ctx.strokeStyle = 'rgba(110,170,255,.08)';
    ctx.lineWidth = 1;
    [0, 0.5, 1].forEach(f => {
      ctx.beginPath();
      ctx.moveTo(x, y + h * f);
      ctx.lineTo(x + w, y + h * f);
      ctx.stroke();
    });
    if (points.length < 2) return;
    ctx.beginPath();
    points.forEach((v, i) => {
      const px = x + (w * i) / (MAX - 1);
      const py = y + h - v * h;
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.shadowBlur = 6;
    ctx.shadowColor = color;
    ctx.stroke();
    ctx.shadowBlur = 0;
    const lastV = points[points.length - 1];
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x + w, y + h - lastV * h, 2.6, 0, Math.PI * 2);
    ctx.fill();
  }

  let lastDraw = 0;
  function draw(now) {
    requestAnimationFrame(draw);
    if (now - lastDraw < 250) return;
    lastDraw = now;
    paint(now);
  }

  function paint(now) {
    push(now);
    if (!ctx) return;
    const s = window.__endoState || {};
    ctx.clearRect(0, 0, W, H);

    const rowH = H / SERIES.length;
    SERIES.forEach((def, i) => {
      const y = i * rowH + 16;
      const h = rowH - 26;
      drawSeries(hist[def.key], 0, y, W, h, def.color);
      const raw = Number(s[def.key]);
      const shown = Number.isFinite(raw)
        ? (def.key === 'core_temp' ? raw.toFixed(1) + '°' : Math.round(def.norm(raw) * 100))
        : '—';
      ctx.fillStyle = 'rgba(190,215,240,.70)';
      ctx.font = '10px "Microsoft YaHei","PingFang SC",sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${def.label} ${shown}`, 1, i * rowH + 12);
    });
  }

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(draw);
  // rAF 被节流 / 切后台回来时，也要保证不是空白
  setInterval(() => paint(performance.now() + 1000), 1200);
})();
