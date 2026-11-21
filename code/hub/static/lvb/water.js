/* 水循环动态演示：一只会呼吸的水罐。
   水位 = 1 - 口渴；渴的时候水面下降、冒气泡、滴答漏水；刚喝过水会有一圈涟漪。 */
(() => {
  const canvas = document.getElementById('water-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let level = 0.75;        // 平滑后的水位
  let target = 0.75;
  let lastThirst = null;
  let ripple = 0;          // 0~1，喝水时的涟漪强度
  let t0 = performance.now();

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    const w = Math.max(64, Math.min(82, box.width * 0.18));
    const h = 112;
    W = w; H = h;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function droplet(x, y, r, alpha) {
    ctx.beginPath();
    ctx.fillStyle = `rgba(125,211,252,${alpha})`;
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function draw() {
    requestAnimationFrame(draw);
    const now = performance.now();
    const t = (now - t0) / 1000;

    const s = window.__endoState || {};
    const thirst = Number(s.thirst);
    if (Number.isFinite(thirst)) {
      const before = lastThirst;
      lastThirst = thirst;
      target = 1 - Math.max(0, Math.min(1, thirst));
      if (before !== null && thirst < before - 0.12) ripple = 1;   // 刚喝过
    }
    level += (target - level) * 0.06;
    ripple *= 0.965;

    if (W === 0) resize();
    ctx.clearRect(0, 0, W, H);

    const pad = 8;
    const x0 = pad, x1 = W - pad;
    const top = 10, bottom = H - 14;
    const w = x1 - x0, h = bottom - top;

    // 罐体边框
    ctx.strokeStyle = 'rgba(103,232,249,.35)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x0, top);
    ctx.lineTo(x0, bottom);
    ctx.lineTo(x1, bottom);
    ctx.lineTo(x1, top);
    ctx.stroke();
    // 刻度
    ctx.strokeStyle = 'rgba(103,232,249,.16)';
    for (let i = 1; i < 4; i++) {
      const y = top + (h * i) / 4;
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x0 + 6, y);
      ctx.moveTo(x1 - 6, y);
      ctx.lineTo(x1, y);
      ctx.stroke();
    }

    // 水
    const surface = bottom - h * Math.max(0.02, Math.min(1, level));
    const col = level < 0.25 ? [37, 99, 235] : (level < 0.5 ? [59, 130, 246] : [56, 189, 248]);
    const g = ctx.createLinearGradient(0, surface, 0, bottom);
    g.addColorStop(0, `rgba(${col[0]},${col[1]},${col[2]},.55)`);
    g.addColorStop(1, `rgba(${col[0]},${col[1]},${col[2]},.20)`);
    ctx.beginPath();
    ctx.moveTo(x0 + 1, surface);
    const points = 24;
    for (let i = 0; i <= points; i++) {
      const px = x0 + ((w - 2) * i) / points;
      const wave = Math.sin(i * 0.55 + t * 1.8) * 2.2 + Math.sin(i * 0.23 - t * 1.1) * 1.4;
      const rip = ripple > 0.02 ? Math.sin(i * 0.9 + t * 6) * 4 * ripple : 0;
      ctx.lineTo(px, surface + wave + rip);
    }
    ctx.lineTo(x1 - 1, bottom - 1);
    ctx.lineTo(x0 + 1, bottom - 1);
    ctx.closePath();
    ctx.fillStyle = g;
    ctx.fill();
    // 水面高光
    ctx.strokeStyle = `rgba(186,230,253,${0.35 + 0.25 * ripple})`;
    ctx.lineWidth = 1;
    ctx.stroke();

    // 气泡：越渴冒得越多（缺水时体内"想喝水"）
    const bubbleRate = 0.3 + (1 - level) * 1.2;
    for (let i = 0; i < 6; i++) {
      const seed = (i * 37 + Math.floor(t * bubbleRate * 10) * 13) % 100;
      const bx = x0 + 8 + (seed / 100) * (w - 16);
      const by = bottom - ((t * (18 + i * 4) * bubbleRate + i * 23) % (bottom - surface));
      if (by > surface + 2) droplet(bx, by, 1.1 + (i % 3) * 0.5, 0.10 + 0.14 * (1 - level));
    }

    // 漏水/要水：渴的时候右上角滴两滴
    if (level < 0.45 && !reduce) {
      const drip = (t * 1.4) % 1;
      droplet(x1 - 6, top + 2 + drip * 16, 1.6, 0.55 * (1 - drip));
      const drip2 = (t * 1.4 + 0.5) % 1;
      droplet(x1 - 2, top + 2 + drip2 * 20, 1.2, 0.4 * (1 - drip2));
    }
  }

  window.addEventListener('resize', resize);
  resize();
  draw();
})();
