/* 怒气动态演示：
   主火舌高度 = 怒气（anger），底部余烬 = 记仇（resentment），
   记仇高了会结霜——就是"冷战"的样子。 */
(() => {
  const canvas = document.getElementById('anger-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let anger = 0, resent = 0;
  let targetA = 0, targetR = 0;
  let sparks = [];
  let last = performance.now();

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    W = Math.max(240, box.width - 30);
    H = canvas.dataset.h ? Number(canvas.dataset.h) : 140;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function tongue(cx, baseY, h, w, top, bottom, alpha, t, seed) {
    if (h < 2) return;
    const sway = Math.sin(t * 2.6 + seed) * w * 0.16;
    ctx.beginPath();
    ctx.moveTo(cx - w / 2, baseY);
    ctx.bezierCurveTo(cx - w / 2, baseY - h * 0.45, cx - w * 0.22 + sway, baseY - h * 0.78, cx + sway, baseY - h);
    ctx.bezierCurveTo(cx + w * 0.22 + sway, baseY - h * 0.78, cx + w / 2, baseY - h * 0.45, cx + w / 2, baseY);
    ctx.closePath();
    const g = ctx.createLinearGradient(0, baseY - h, 0, baseY);
    g.addColorStop(0, top);
    g.addColorStop(1, bottom);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = g;
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function spawnSpark(cx, baseY, spread) {
    sparks.push({
      x: cx + (Math.random() - 0.5) * spread,
      y: baseY - Math.random() * 6,
      vx: (Math.random() - 0.5) * 0.5,
      vy: -(0.5 + Math.random() * 1.5),
      life: 1,
      decay: 0.006 + Math.random() * 0.012,
      r: 1 + Math.random() * 2,
    });
  }

  function draw(now) {
    requestAnimationFrame(draw);
    const dt = Math.min(50, now - last);
    last = now;
    const t = now / 1000;

    const s = window.__endoState || {};
    const a = Number(s.anger), r = Number(s.resentment);
    if (Number.isFinite(a)) targetA = Math.max(0, Math.min(1, a));
    if (Number.isFinite(r)) targetR = Math.max(0, Math.min(1, r));
    anger += (targetA - anger) * 0.10;
    resent += (targetR - resent) * 0.05;

    const cold = resent > 0.45;
    const status = document.getElementById('anger-status');
    if (status) {
      status.textContent = cold ? '冷战 · 还记着'
        : (anger > 0.65 ? '正在生气' : (anger > 0.30 ? '有点火' : '平静'));
      status.classList.toggle('hot', anger > 0.30 && !cold);
      status.classList.toggle('cold', cold);
    }
    document.body.classList.toggle('angry', anger > 0.35 && !cold);
    const aNum = document.getElementById('anger-num');
    if (aNum) aNum.textContent = Math.round(anger * 100);
    const rNum = document.getElementById('resent-num');
    if (rNum) rNum.textContent = Math.round(resent * 100);

    ctx.clearRect(0, 0, W, H);
    const baseY = H - 12;
    const cx = W / 2;

    // 底部余烬（记仇）：不是一个大红饼，是一堆还亮着的炭
    const bedR = W * 0.16 + W * 0.05 * resent;
    const eg = ctx.createRadialGradient(cx, baseY, 2, cx, baseY, bedR);
    eg.addColorStop(0, `rgba(251,113,133,${0.08 + 0.22 * resent})`);
    eg.addColorStop(1, 'rgba(251,113,133,0)');
    ctx.fillStyle = eg;
    ctx.beginPath();
    ctx.ellipse(cx, baseY, bedR, 6 + 9 * resent, 0, 0, Math.PI * 2);
    ctx.fill();
    const coals = Math.round(3 + 9 * resent);
    for (let i = 0; i < coals; i++) {
      const px = cx + Math.sin(i * 2.3) * bedR * 0.75;
      const py = baseY - 1 - (i % 3) * 1.6;
      const glow = 0.25 + 0.55 * resent * (0.6 + 0.4 * Math.sin(t * 2 + i));
      ctx.fillStyle = `rgba(251,146,60,${glow.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(px, py, 1.4 + (i % 3) * 0.7, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.strokeStyle = 'rgba(103,232,249,.12)';
    ctx.beginPath();
    ctx.moveTo(0, baseY);
    ctx.lineTo(W, baseY);
    ctx.stroke();

    // 主火舌：三层，越高越旺
    const maxH = H - 26;
    const h = 8 + maxH * anger;
    const flick = 0.94 + 0.06 * Math.sin(t * 9) + 0.03 * Math.sin(t * 21 + 1);
    const w0 = 46 + 70 * anger;
    tongue(cx, baseY, h * flick * 1.00, w0, 'rgba(239,68,68,.85)', 'rgba(120,20,30,.10)', 0.55, t, 0);
    tongue(cx, baseY, h * flick * 0.78, w0 * 0.72, 'rgba(251,146,60,.95)', 'rgba(160,40,20,.10)', 0.65, t, 1.7);
    tongue(cx, baseY, h * flick * 0.50, w0 * 0.42, 'rgba(253,224,120,.98)', 'rgba(251,146,60,.10)', 0.75, t, 3.1);
    tongue(cx - w0 * 0.62, baseY, h * 0.55 * flick, w0 * 0.42, 'rgba(251,146,60,.8)', 'rgba(120,20,30,0)', 0.40, t, 4.4);
    tongue(cx + w0 * 0.62, baseY, h * 0.48 * flick, w0 * 0.42, 'rgba(251,146,60,.8)', 'rgba(120,20,30,0)', 0.40, t, 5.9);

    // 火星
    if (!reduce) {
      if (Math.random() < 0.10 + anger * 1.2) spawnSpark(cx, baseY, w0 * 1.3);
      for (let i = sparks.length - 1; i >= 0; i--) {
        const p = sparks[i];
        p.x += p.vx; p.y += p.vy * (dt / 16); p.life -= p.decay * (dt / 16);
        if (p.life <= 0 || p.y < 0) { sparks.splice(i, 1); continue; }
        ctx.globalAlpha = Math.max(0, p.life) * (0.3 + 0.6 * anger);
        ctx.fillStyle = 'rgba(253,186,116,1)';
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    // 冷战结霜
    if (resent > 0.30) {
      const frost = Math.min(1, (resent - 0.30) / 0.5);
      const fg = ctx.createLinearGradient(0, 0, 0, H);
      fg.addColorStop(0, `rgba(147,197,253,${0.12 * frost})`);
      fg.addColorStop(0.65, 'rgba(147,197,253,0)');
      ctx.fillStyle = fg;
      ctx.fillRect(0, 0, W, H * 0.65);
      ctx.strokeStyle = `rgba(191,219,254,${0.55 * frost})`;
      ctx.lineWidth = 1.2;
      for (let i = 0; i < 10; i++) {
        const x = (W / 11) * (i + 1);
        const len = 12 + 18 * frost;
        ctx.beginPath();
        ctx.moveTo(x, 0); ctx.lineTo(x + 6, len);
        ctx.moveTo(x, 0); ctx.lineTo(x - 6, len * 0.75);
        ctx.moveTo(x, len * 0.45); ctx.lineTo(x + 9, len * 0.55);
        ctx.stroke();
      }
      // 两侧结冰
      const side = ctx.createLinearGradient(0, 0, W, 0);
      side.addColorStop(0, `rgba(147,197,253,${0.16 * frost})`);
      side.addColorStop(0.25, 'rgba(147,197,253,0)');
      side.addColorStop(0.75, 'rgba(147,197,253,0)');
      side.addColorStop(1, `rgba(147,197,253,${0.16 * frost})`);
      ctx.fillStyle = side;
      ctx.fillRect(0, 0, W, H);
    }
  }

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(draw);
})();
