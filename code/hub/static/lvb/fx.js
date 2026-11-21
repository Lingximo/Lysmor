/* 科幻 HUD 背景层：粒子 + 网格 + 扫描 + 头像外环。
   纯 canvas，不依赖任何库，尊重 reduced-motion。 */
(() => {
  const canvas = document.getElementById('fx');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let particles = [];
  let t0 = performance.now();

  function resize() {
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const n = Math.min(90, Math.round((W * H) / 20000));
    particles = Array.from({ length: n }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      z: Math.random() * 0.8 + 0.2,
      vx: (Math.random() - 0.5) * 0.06,
      vy: -(Math.random() * 0.12 + 0.02),
      p: Math.random() * Math.PI * 2,
    }));
  }

  function grid(t) {
    ctx.save();
    ctx.strokeStyle = 'rgba(80, 170, 220, 0.055)';
    ctx.lineWidth = 1;
    const gap = 64;
    const offset = (t * 6) % gap;
    for (let x = -gap + offset; x < W + gap; x += gap) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.stroke();
    }
    for (let y = -gap + offset; y < H + gap; y += gap) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  function scan(t) {
    const period = 7.5;
    const p = ((t % period) / period);
    const y = p * H;
    const g = ctx.createLinearGradient(0, y - 90, 0, y + 10);
    g.addColorStop(0, 'rgba(103,232,249,0)');
    g.addColorStop(0.75, 'rgba(103,232,249,0.055)');
    g.addColorStop(1, 'rgba(160,250,255,0.14)');
    ctx.fillStyle = g;
    ctx.fillRect(0, y - 90, W, 100);
  }

  function hudRing() {
    // 围绕 Live2D 区域的转动刻度环
    const wrap = document.querySelector('.avatar-wrap');
    if (!wrap) return;
    const r = wrap.getBoundingClientRect();
    if (r.width < 40) return;
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height * 0.52;
    const base = Math.min(r.width, r.height) * 0.42;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((performance.now() / 1000) * 0.25);
    ctx.strokeStyle = 'rgba(103,232,249,0.20)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 48; i++) {
      const a = (i / 48) * Math.PI * 2;
      const long = i % 6 === 0;
      const r1 = base;
      const r2 = base + (long ? 12 : 5);
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1);
      ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(167,139,250,0.14)';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(0, 0, base - 12, 0, Math.PI * 1.25);
    ctx.stroke();
    ctx.restore();
  }

  let lastDraw = 0;
  function draw() {
    const now = performance.now();
    if (now - lastDraw < 33) { requestAnimationFrame(draw); return; }
    lastDraw = now;
    const t = (now - t0) / 1000;
    ctx.clearRect(0, 0, W, H);
    grid(t * 0.6);

    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy * p.z;
      if (p.y < -4) { p.y = H + 4; p.x = Math.random() * W; }
      if (p.x < -4) p.x = W + 4;
      if (p.x > W + 4) p.x = -4;
      const a = (0.12 + 0.22 * Math.sin(t * 1.6 + p.p)) * p.z;
      ctx.fillStyle = `rgba(150,220,255,${a.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.z * 1.4, 0, Math.PI * 2);
      ctx.fill();
    }

    scan(t);
    hudRing();
    if (!reduce) requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
  resize();
  draw();
})();
