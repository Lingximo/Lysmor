/* 生命体征脉冲：近 3 分钟的曲线 + 死亡威胁提示。
   数据来自 app.js 写进 window.__endoState 的那份 /api/state。 */
(() => {
  const tr = (key, vars) => window.LysmorI18n.t(key, vars);
  const SERIES = [
    { key: 'cortisol', get label() { return tr("panels.cortisol"); }, color: '#fb7185' },
    { key: 'dopamine', get label() { return tr("panels.dopamine"); }, color: '#fbbf24' },
    { key: 'oxytocin', get label() { return tr("panels.oxytocin"); }, color: '#67e8f9' },
    { key: 'melatonin', get label() { return tr("panels.melatonin"); }, color: '#818cf8' },
    { key: 'hunger', get label() { return tr("panels.hunger"); }, color: '#f472b6' },
    { key: 'thirst', get label() { return tr("panels.thirst"); }, color: '#38bdf8' },
  ];
  const MAX = 60;            // 3 秒一次轮询 → 约 3 分钟
  const hist = {};
  SERIES.forEach(s => { hist[s.key] = []; });

  const canvas = document.getElementById('pulse-canvas');
  const ctx = canvas ? canvas.getContext('2d') : null;
  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let lastPush = 0;

  function resize() {
    if (!canvas) return;
    const box = canvas.parentElement.getBoundingClientRect();
    W = Math.max(200, box.width - 26);
    H = canvas.dataset.h ? Number(canvas.dataset.h) : 150;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function sample(now) {
    const s = window.__endoState;
    if (!s) return;
    if (now - lastPush < 2500) return;
    lastPush = now;
    SERIES.forEach(def => {
      const v = Number(s[def.key]);
      if (!Number.isFinite(v)) return;
      const arr = hist[def.key];
      const clamped = Math.max(0, Math.min(1, v));
      // 第一次采样：先用当前值铺满基线，曲线才有"整屏"的样子，再从右边长出来
      if (!arr.length) for (let i = 0; i < MAX; i++) arr.push(clamped);
      arr.push(clamped);
      if (arr.length > MAX) arr.shift();
    });
  }

  function drawSeries(points, x, y, w, h, color) {
    // 基线 + 中线
    ctx.strokeStyle = 'rgba(110,170,255,.09)';
    ctx.lineWidth = 1;
    [0, 0.5, 1].forEach(f => {
      ctx.beginPath();
      ctx.moveTo(x, y + h * f);
      ctx.lineTo(x + w, y + h * f);
      ctx.stroke();
    });
    if (points.length < 2) {
      // 还不够两个点：只画一个亮点，别画假线
      if (points.length === 1) {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x + w, y + h - points[0] * h, 2.6, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }
    // 从右往左生长：最新的点永远在最右边
    const offset = MAX - points.length;
    ctx.beginPath();
    points.forEach((v, i) => {
      const px = x + (w * (i + offset)) / (MAX - 1);
      const py = y + h - v * h;
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.lineJoin = 'round';
    ctx.shadowBlur = 6;
    ctx.shadowColor = color;
    ctx.stroke();
    ctx.shadowBlur = 0;

    if (points.length >= 2) {
      const g = ctx.createLinearGradient(0, y, 0, y + h);
      g.addColorStop(0, color + '33');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.beginPath();
      points.forEach((v, i) => {
        const px = x + (w * (i + offset)) / (MAX - 1);
        const py = y + h - v * h;
        i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      });
      ctx.lineTo(x + w, y + h);
      ctx.lineTo(x + (w * offset) / (MAX - 1), y + h);
      ctx.closePath();
      ctx.fillStyle = g;
      ctx.fill();
    }

    const lastV = points[points.length - 1];
    const px = x + w;
    const py = y + h - lastV * h;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(px, py, 2.8, 0, Math.PI * 2);
    ctx.fill();
    // 末端微光
    ctx.beginPath();
    ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,.06)';
    ctx.fill();
  }

  let lastDraw = 0;
  function draw() {
    requestAnimationFrame(draw);
    const now = performance.now();
    if (now - lastDraw < 250) return;
    lastDraw = now;
    sample(now);
    if (!ctx) return;

    const s = window.__endoState || {};
    const mortality = Number(s.mortality || 0);
    document.body.classList.toggle('critical', mortality > 0.5);

    const banner = document.getElementById('mortality-banner');
    if (banner) {
      if (mortality > 0.25) {
        banner.style.display = 'block';
        banner.textContent = mortality > 0.6
          ? tr("panels.funds_critical")
          : tr("panels.funds_low");
      } else {
        banner.style.display = 'none';
      }
    }

    ctx.clearRect(0, 0, W, H);
    const rowH = H / SERIES.length;
    SERIES.forEach((def, i) => {
      const y = i * rowH + 14;              // 留出标签的位置
      const h = rowH - 22;
      drawSeries(hist[def.key], 0, y, W, h, def.color);
      const arr = hist[def.key];
      const cur = arr.length ? arr[arr.length - 1] : 0;
      ctx.fillStyle = 'rgba(190,215,240,.62)';
      ctx.font = '9.5px "Microsoft YaHei","PingFang SC",sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${def.label} ${Math.round(cur * 100)}`, 1, i * rowH + 10);
    });
  }

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(draw);
})();
