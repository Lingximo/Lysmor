/* 生理周期：30 天圆盘 + 当前指针 + 经期脉动点。 */
(() => {
  const tr = (key, vars) => window.LysmorI18n.t(key, vars);
  const canvas = document.getElementById('cycle-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const PHASES = [
    { from: 1, to: 5, color: '#fb7185', get name() { return tr("panels.menstrual"); } },
    { from: 6, to: 12, color: '#4ade80', get name() { return tr("panels.follicular"); } },
    { from: 13, to: 15, color: '#a78bfa', get name() { return tr("panels.ovulation"); } },
    { from: 16, to: 23, color: '#fbbf24', get name() { return tr("panels.luteal"); } },
    { from: 24, to: 30, color: '#94a3b8', get name() { return tr("panels.premenstrual"); } },
  ];
  let DAYS = 30;

  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let angle = -Math.PI / 2;     // 当前指针
  let targetAngle = -Math.PI / 2;
  let day = 1;

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    const size = Math.max(180, Math.min(250, box.width - 40));
    W = H = size;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function angleOf(d) {
    return -Math.PI / 2 + ((d - 1) / DAYS) * Math.PI * 2;
  }

  function phaseOf(d) {
    const list = PHASES.map((p, i) => (i === PHASES.length - 1 ? { ...p, to: DAYS } : p));
    return list.find(p => d >= p.from && d <= p.to) || list[0];
  }

  function draw(now) {
    requestAnimationFrame(draw);
    const s = window.__endoState || {};
    const len = Number(s.cycle_len);
    if (Number.isFinite(len) && len >= 21) DAYS = len;
    const d = Number(s.cycle_day);
    if (Number.isFinite(d) && d >= 1) {
      if (d !== day) {
        day = d;
        targetAngle = angleOf(d);
      }
    }
    angle += (targetAngle - angle) * 0.08;

    const cx = W / 2, cy = H / 2;
    const R = W * 0.36;
    const t = now / 1000;

    ctx.clearRect(0, 0, W, H);

    // 底环
    ctx.strokeStyle = 'rgba(110,170,255,.10)';
    ctx.lineWidth = 10;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.stroke();

    // 各阶段弧
    PHASES.forEach((p, idx) => {
      const to = idx === PHASES.length - 1 ? DAYS : p.to;
      const a0 = angleOf(p.from);
      const a1 = angleOf(to + 1);
      const active = day >= p.from && day <= (idx === PHASES.length - 1 ? DAYS : p.to);
      ctx.strokeStyle = p.color;
      ctx.globalAlpha = active ? 0.95 : 0.35;
      ctx.lineWidth = active ? 11 : 8;
      ctx.lineCap = 'butt';
      ctx.beginPath();
      ctx.arc(cx, cy, R, a0, a1);
      ctx.stroke();
      ctx.globalAlpha = 1;
    });

    // 经期脉动点
    const menstruating = day >= 1 && day <= 5;
    if (menstruating) {
      const dayIdx = Math.floor(((angle + Math.PI / 2) / (Math.PI * 2)) * DAYS) % DAYS;
      for (let i = 1; i <= 5; i++) {
        const a = angleOf(i) + (Math.PI / DAYS);
        const pulse = 0.5 + 0.5 * Math.sin(t * 3 + i);
        ctx.fillStyle = `rgba(251,113,133,${0.35 + 0.5 * pulse})`;
        ctx.beginPath();
        ctx.arc(cx + Math.cos(a) * R, cy + Math.sin(a) * R, 3 + pulse * 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // 刻度
    ctx.strokeStyle = 'rgba(103,232,249,.22)';
    ctx.lineWidth = 1;
    for (let i = 0; i < DAYS; i++) {
      const a = angleOf(i + 1);
      const r1 = R - 9, r2 = R - 5;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
      ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
      ctx.stroke();
    }

    // 指针
    const px = cx + Math.cos(angle) * (R + 12);
    const py = cy + Math.sin(angle) * (R + 12);
    ctx.strokeStyle = '#e0f7ff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * (R - 14), cy + Math.sin(angle) * (R - 14));
    ctx.lineTo(px, py);
    ctx.stroke();
    ctx.shadowBlur = 12;
    ctx.shadowColor = '#67e8f9';
    ctx.fillStyle = '#a5f3fc';
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // 中心文字
    const ph = phaseOf(day);
    ctx.textAlign = 'center';
    ctx.fillStyle = ph.color;
    ctx.font = '600 20px "Microsoft YaHei","PingFang SC",sans-serif';
    ctx.fillText(ph.name, cx, cy - 2);
    ctx.fillStyle = 'rgba(200,225,255,.75)';
    ctx.font = '11px "Consolas","Microsoft YaHei",monospace';
    ctx.fillText(`D${day} / ${DAYS}`, cx, cy + 18);

    // 底部两项激素
    const est = Number(s.estrogen), prog = Number(s.progesterone);
    if (Number.isFinite(est)) {
      ctx.fillStyle = 'rgba(249,168,212,.85)';
      ctx.font = '10px "Microsoft YaHei",sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${tr("panels.estrogen")} ${Math.round(est * 100)}`, 6, H - 16);
    }
    if (Number.isFinite(prog)) {
      ctx.fillStyle = 'rgba(196,181,253,.85)';
      ctx.font = '10px "Microsoft YaHei",sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(`${tr("panels.progesterone")} ${Math.round(prog * 100)}`, W - 6, H - 16);
    }
    if (menstruating) {
      ctx.textAlign = 'center';
      ctx.fillStyle = 'rgba(251,113,133,.9)';
      ctx.font = '10px "Microsoft YaHei",sans-serif';
      ctx.fillText(tr("panels.menstrual_weak"), cx, H - 16);
    }

    if (reduce) cancelAnimationFrame(0);
  }

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(draw);
})();
