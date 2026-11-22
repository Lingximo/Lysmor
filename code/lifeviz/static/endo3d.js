/* 神经-体液 3D 场景 v2（无依赖，Canvas 2D + 透视投影）
 *
 * 层次（从内到外）：
 *   1. 内核：突触核（黄，随多巴胺发光）
 *   2. 突触壳层：稀疏粒子云（紫/黄/青，随血清素/多巴胺/内啡肽）
 *   3. 中轴：下丘脑 → 垂体 → 肾上腺（红，光点沿轴下落）
 *   4. 双螺旋：交感（橙，向上绕）/ 副交感（青，向下绕）
 *   5. 轨道环：三条倾斜光环（蓝），像电子轨道，提供立体纵深
 *   6. 环境：星野 + 地面网格 + 夜间褪黑素微尘 + 低血糖红色脉冲
 *
 * 交互：自动旋转；拖动可手转；滚轮缩放；松手 2.5 秒恢复自转
 * 数据：window.__endoState
 */
(() => {
  const tr = (key, vars) => window.LysmorI18n.t(key, vars);
  const canvas = document.getElementById('endo-flow');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const cam = { rotY: 0.6, rotX: -0.16, dist: 420, zoom: 1.0, cx: 0, cy: 0, auto: true, idleAt: 0 };
  const DPR = Math.min(2, window.devicePixelRatio || 1);
  let W = 1, H = 1, last = 0, dragging = false, lastPointer = null, paint = 0;

  // 突触壳：稀疏，避免挡住中轴
  const shell = [];
  const SHELL_N = 54;
  for (let i = 0; i < SHELL_N; i++) {
    const t = Math.acos(1 - 2 * (i + 0.5) / SHELL_N);
    const phi = Math.PI * (1 + Math.sqrt(5)) * i;
    shell.push({
      x: Math.cos(phi) * Math.sin(t),
      y: Math.cos(t),
      z: Math.sin(phi) * Math.sin(t),
      seed: Math.random() * Math.PI * 2,
    });
  }

  function resize() {
    const r = canvas.getBoundingClientRect();
    W = r.width || 600;
    H = r.height || 300;
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    cam.cx = W / 2;
    cam.cy = H / 2;
  }

  function rotate(p) {
    const cy = Math.cos(cam.rotY), sy = Math.sin(cam.rotY);
    let x = p.x * cy - p.z * sy;
    let z = p.x * sy + p.z * cy;
    const cx = Math.cos(cam.rotX), sx = Math.sin(cam.rotX);
    const y = p.y * cx - z * sx;
    z = p.y * sx + z * cx;
    return { x, y, z };
  }

  function project(p) {
    const r = rotate(p);
    const z = r.z + cam.dist;
    const k = (460 * cam.zoom) / Math.max(40, z);
    return { sx: cam.cx + r.x * k, sy: cam.cy - r.y * k, k, z };
  }

  function polyline(lines, pts, color, alpha, width) {
    const screen = pts.map((p) => project(p));
    let minZ = Infinity;
    for (const q of screen) minZ = Math.min(minZ, q.z);
    lines.push({ pts: screen, color, alpha, width: width || 1, z: minZ });
  }

  function push(list, p, r, color, alpha, blur) {
    const q = project(p);
    if (q.sx < -100 || q.sx > W + 100 || q.sy < -100 || q.sy > H + 100) return;
    const near = Math.max(0.55, Math.min(1.15, 320 / q.z));
    list.push({
      sx: q.sx, sy: q.sy, z: q.z,
      r: Math.max(0.35, Math.min(7, r * q.k * 0.95 * near)),
      color,
      alpha: Math.max(0, Math.min(1, alpha * near)),
      blur: Math.min(14, (blur || 0) * near * 0.6),
    });
  }

  function draw(t) {
    const s = window.__endoState || {};
    const crh = num(s.crh, 0.1), acth = num(s.acth, 0.1), cor = num(s.cortisol, 0.2);
    const adr = num(s.adrenaline, 0.05), ach = num(s.acetylcholine, 0.45);
    const dop = num(s.dopamine, 0.5), sero = num(s.serotonin, 0.6);
    const endo = num(s.endorphin, 0.45), mel = num(s.melatonin, 0), glu = num(s.glucose, 0.6);
    const na = num(s.noradrenaline, 0.45);
    const spin = t / 1000;

    ctx.clearRect(0, 0, W, H);
    paintBackground(t, mel);

    const list = [];
    const lines = [];

    // ---------- 地面网格（纵深参考）----------
    for (let ring = 1; ring <= 3; ring++) {
      const R = 86 + ring * 52;
      for (let i = 0; i < 56; i++) {
        const a = (i / 56) * Math.PI * 2;
        push(list, { x: Math.cos(a) * R, y: -150, z: Math.sin(a) * R }, 0.5,
          'rgba(56,189,248,.16)', 0.45, 0);
      }
    }

    // ---------- 中轴：三个节点 ----------
    const axis = [
      { y: 118, v: crh, get label() { return tr("panels.hypothalamus"); } },
      { y: 0, v: acth, get label() { return tr("panels.pituitary"); } },
      { y: -118, v: cor, get label() { return tr("panels.adrenal"); } },
    ];
    polyline(lines, [{ x: 0, y: 128, z: 0 }, { x: 0, y: -128, z: 0 }],
      'rgba(248,113,113,.85)', 0.55, 1.4);
    const axisScreen = [];
    axis.forEach((n, i) => {
      const breath = 1 + 0.16 * Math.sin(spin * (2.0 + cor * 5) + i);
      push(list, { x: 0, y: n.y, z: 0 }, (5 + n.v * 8) * breath,
        'rgba(251,113,133,.95)', 0.5 + n.v * 0.5, 12 + n.v * 14);
      push(list, { x: 0, y: n.y, z: 0 }, (8 + n.v * 10) * breath,
        'rgba(251,113,133,.30)', 0.20, 24);
      axisScreen.push({ p: project({ x: 0, y: n.y, z: 0 }), label: n.label });
    });

    // 沿轴下落的光点
    const fall = 0.4 + crh * 1.2 + acth * 0.7;
    for (let i = 0; i < 22; i++) {
      const ph = ((spin * fall * 0.30 + i / 22) % 1);
      const y = 132 - ph * 264;
      const wob = Math.sin(ph * 16 + i) * 6;
      push(list, { x: wob, y, z: Math.cos(ph * 12 + i) * 6 }, 1.3 + cor * 1.1,
        `rgba(251,113,133,${0.18 + cor * 0.5})`, 0.35 + cor * 0.5, 7);
    }

    // ---------- 双螺旋（比壳层更外，保证不被遮住）----------
    const helix = [
      { color: '251,146,60', level: Math.max(adr, na * 0.6), dir: 1, turns: 2.6, R: 96 },
      { color: '52,211,153', level: ach, dir: -1, turns: 2.0, R: 112 },
    ];
    helix.forEach((h) => {
      const coil = [];
      for (let i = 0; i <= 140; i++) {
        const p = (i / 140 + spin * 0.015 * h.dir) % 1;
        const a = p * Math.PI * 2 * h.turns;
        coil.push({ x: Math.cos(a) * h.R, y: 128 - p * 256, z: Math.sin(a) * h.R });
      }
      polyline(lines, coil, `rgba(${h.color},.55)`, 0.28 + h.level * 0.30, 1);
      const n = 26;
      for (let i = 0; i < n; i++) {
        const ph = ((spin * (0.05 + h.level * 0.26) * h.dir + i / n) % 1 + 1) % 1;
        const a = ph * Math.PI * 2 * h.turns;
        push(list, { x: Math.cos(a) * h.R, y: 128 - ph * 256, z: Math.sin(a) * h.R },
          1.3 + h.level * 2.0, `rgba(${h.color},${0.22 + h.level * 0.68})`,
          0.45 + h.level * 0.55, 9);
      }
    });

    // ---------- 轨道环（三条倾斜光环）----------
    const rings = [
      { tilt: 0.9, R: 132, speed: 0.5, color: '56,189,248' },
      { tilt: -0.7, R: 156, speed: -0.35, color: '167,139,250' },
      { tilt: 0.25, R: 178, speed: 0.22, color: '103,232,249' },
    ];
    rings.forEach((ring, ri) => {
      const loop = [];
      for (let i = 0; i <= 96; i++) {
        const a = (i / 96) * Math.PI * 2 + spin * 0.06 * ring.speed;
        loop.push({
          x: Math.cos(a) * ring.R,
          y: Math.sin(a + ring.tilt) * 26 + (ri - 1) * 26,
          z: Math.sin(a) * ring.R,
        });
      }
      polyline(lines, loop, `rgba(${ring.color},.45)`, 0.16 + ri * 0.03, 1);
      // 环上流动的亮点
      for (let i = 0; i < 4; i++) {
        const a = spin * (0.5 + ring.speed) + (i / 4) * Math.PI * 2;
        const x = Math.cos(a) * ring.R;
        const z = Math.sin(a) * ring.R;
        const y = Math.sin(a + ring.tilt) * 26 + (ri - 1) * 26;
        push(list, { x, y, z }, 1.8, `rgba(${ring.color},.85)`, 0.75, 12);
      }
    });

    // ---------- 突触核 + 稀疏壳层 ----------
    const shellR = 26 + (dop + sero) * 10;
    const pulse = 1 + 0.05 * Math.sin(spin * (2 + dop * 4));
    shell.forEach((sp, i) => {
      const wob = 1 + 0.05 * Math.sin(spin * 1.5 + sp.seed);
      const r = shellR * pulse * wob;
      const color = i % 3 === 0 ? '167,139,250' : (i % 3 === 1 ? '251,191,36' : '103,232,249');
      const lv = i % 3 === 0 ? sero : (i % 3 === 1 ? dop : endo);
      push(list, { x: sp.x * r, y: sp.y * r * 0.95, z: sp.z * r },
        0.8 + lv * 1.6, `rgba(${color},${0.14 + lv * 0.42})`, 0.35 + lv * 0.45, 6);
    });
    push(list, { x: 0, y: 0, z: 0 }, 8 + dop * 7, 'rgba(251,191,36,.85)', 0.5, 26);
    push(list, { x: 0, y: 0, z: 0 }, 15 + dop * 9, 'rgba(251,191,36,.22)', 0.20, 38);

    if (Math.random() < dop * 0.09) {
      const a = Math.random() * Math.PI * 2, b = Math.random() * Math.PI;
      const r = shellR * 1.25;
      push(list, { x: Math.cos(a) * Math.sin(b) * r, y: Math.cos(b) * r, z: Math.sin(a) * Math.sin(b) * r },
        2.2, 'rgba(253,230,138,.95)', 0.85, 16);
    }

    // ---------- 夜间褪黑素 ----------
    if (mel > 0.15) {
      for (let i = 0; i < 34; i++) {
        const ph = ((spin * (0.04 + mel * 0.10) + i / 34) % 1);
        const y = 160 - ph * 320;
        const a = i * 2.39996;
        const R = 70 + (i % 6) * 22;
        push(list, { x: Math.cos(a + spin * 0.08) * R, y, z: Math.sin(a + spin * 0.08) * R },
          1.0, `rgba(129,140,248,${0.12 + mel * 0.40})`, 0.3 + mel * 0.5, 7);
      }
    }

    // ---------- 先画结构线（远），再画粒子 ----------
    lines.sort((a, b) => b.z - a.z);
    for (const ln of lines) {
      ctx.save();
      ctx.globalAlpha = ln.alpha;
      ctx.strokeStyle = ln.color;
      ctx.lineWidth = ln.width;
      ctx.beginPath();
      ln.pts.forEach((q, i) => (i ? ctx.lineTo(q.sx, q.sy) : ctx.moveTo(q.sx, q.sy)));
      ctx.stroke();
      ctx.restore();
    }

    // ---------- 深度排序绘制 ----------
    list.sort((a, b) => b.z - a.z);
    for (const d of list) {
      if (d.alpha <= 0.01 || d.r <= 0.05) continue;
      ctx.save();
      if (d.blur > 0.5) { ctx.shadowColor = d.color; ctx.shadowBlur = d.blur; }
      ctx.globalAlpha = d.alpha;
      ctx.fillStyle = d.color;
      ctx.beginPath();
      ctx.arc(d.sx, d.sy, d.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // ---------- 节点标签（带引导线）----------
    ctx.save();
    ctx.font = '10px "Microsoft YaHei", sans-serif';
    axisScreen.forEach((it) => {
      const { sx, sy } = it.p;
      ctx.strokeStyle = 'rgba(148,163,184,.28)';
      ctx.beginPath(); ctx.moveTo(sx - 14, sy); ctx.lineTo(sx - 34, sy); ctx.stroke();
      ctx.fillStyle = 'rgba(226,232,240,.78)';
      ctx.textAlign = 'right';
      ctx.fillText(it.label, sx - 38, sy + 3);
    });
    ctx.restore();

    if (glu < 0.38) {
      const p2 = 0.5 + 0.5 * Math.sin(t / 240);
      const g = ctx.createLinearGradient(0, H - 30, 0, H);
      g.addColorStop(0, 'rgba(248,113,113,0)');
      g.addColorStop(1, `rgba(248,113,113,${0.10 + p2 * 0.22})`);
      ctx.fillStyle = g;
      ctx.fillRect(0, H - 30, W, 30);
    }
  }

  function paintBackground(t, mel) {
    const g = ctx.createRadialGradient(W * 0.5, H * 0.48, 30, W * 0.5, H * 0.48, Math.max(W, H) * 0.8);
    g.addColorStop(0, 'rgba(10,22,38,.92)');
    g.addColorStop(1, 'rgba(3,6,12,.97)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    for (let i = 0; i < 70; i++) {
      const x = (i * 97.13 + t * 0.004) % W;
      const y = (i * 53.7) % H;
      const a = 0.05 + 0.10 * Math.abs(Math.sin(i + t / 2400));
      ctx.fillStyle = `rgba(186,230,253,${a})`;
      ctx.fillRect(x, y, 1.2, 1.2);
    }
    if (mel > 0.15) {
      const ng = ctx.createLinearGradient(0, 0, 0, H);
      ng.addColorStop(0, `rgba(49,46,129,${0.12 * mel})`);
      ng.addColorStop(1, `rgba(30,27,75,${0.20 * mel})`);
      ctx.fillStyle = ng;
      ctx.fillRect(0, 0, W, H);
    }
  }

  function num(v, d) {
    const n = Number(v);
    return Number.isFinite(n) ? n : d;
  }

  function loop(t) {
    const dt = Math.min(0.05, (t - (last || t)) / 1000);
    last = t;
    if (cam.auto && performance.now() - cam.idleAt > 2500) cam.rotY += dt * 0.30;

    // ~30fps
    if (t - paint >= 32) {
      paint = t;
      draw(t);
    }
    requestAnimationFrame(loop);
  }

  canvas.style.cursor = 'grab';
  canvas.addEventListener('pointerdown', (e) => {
    dragging = true;
    cam.auto = false;
    lastPointer = { x: e.clientX, y: e.clientY };
    canvas.setPointerCapture?.(e.pointerId);
    canvas.style.cursor = 'grabbing';
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!dragging || !lastPointer) return;
    cam.rotY += (e.clientX - lastPointer.x) * 0.008;
    cam.rotX = Math.max(-1.1, Math.min(1.1, cam.rotX + (e.clientY - lastPointer.y) * 0.006));
    lastPointer = { x: e.clientX, y: e.clientY };
  });
  const stop = () => {
    dragging = false;
    lastPointer = null;
    cam.idleAt = performance.now();
    cam.auto = true;
    canvas.style.cursor = 'grab';
  };
  canvas.addEventListener('pointerup', stop);
  canvas.addEventListener('pointerleave', () => { if (dragging) stop(); });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    cam.zoom = Math.max(0.55, Math.min(2.0, cam.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
  }, { passive: false });

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(loop);
})();
