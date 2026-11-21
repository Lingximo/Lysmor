/* 内稳态循环 v2（2026-11-01）
 *
 * 仿「星图」的观感：自己算 3D 透视，环是一个倾斜的轨道平面，
 * 节点按远近缩放/变暗，中心是发光的核，周围有星尘。
 *
 * 交互：悬停高亮 + 说明；点击固定；拖动旋转（松手带惯性）；点中心清除。
 */
(() => {
  const canvas = document.getElementById('homeo-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const metricsEl = document.getElementById('homeo-metrics');
  const noteEl = document.getElementById('homeo-note');
  if (!metricsEl || !noteEl) return;

  const NODES = [
    { key: 'memory', label: '记忆', color: '#67e8f9', tip: '记忆活跃度：情绪越鲜明，这部分越亮' },
    { key: 'sleep', label: '睡眠', color: '#a78bfa', tip: '睡眠压力：腺苷累积，越困越想睡' },
    { key: 'scar', label: '创伤', color: '#fb7185', tip: '濒死/深刻创伤：第一次1.0，随时间和舒适淡到0.7，再提及/类似经历最高回到0.8' },
    { key: 'hormone', label: '激素', color: '#fbbf24', tip: '激素压强：皮质醇、去甲肾上腺素、催产素' },
    { key: 'obsess', label: '执念', color: '#f472b6', tip: '执念压力：心里绕不过去的那件事' },
    { key: 'dream', label: '梦境', color: '#34d399', tip: '梦境：醒着是余味，睡着是正在累积的做梦压力' },
  ];

  const CAMERA = 560;
  const TILT = 0.62;
  const PERSPECTIVE_MIN = 0.55;

  let W = 0, H = 0, DPR = Math.min(2, window.devicePixelRatio || 1);
  let rot = 0.4, tiltSpin = 0, rotVel = 0;
  let hoverKey = null, pinKey = null, dragging = false, lastX = 0, lastY = 0;
  let dust = [];

  const clamp01 = v => Math.max(0, Math.min(1, Number(v) || 0));

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    W = Math.max(200, box.width || 320);
    H = Math.max(180, box.height || 240);
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    if (!dust.length) {
      for (let i = 0; i < 46; i++) {
        dust.push({
          a: Math.random() * Math.PI * 2,
          r: 0.55 + Math.random() * 0.85,
          y: (Math.random() - 0.5) * 0.55,
          s: 0.4 + Math.random() * 1.1,
          sp: 0.15 + Math.random() * 0.5,
        });
      }
    }
  }

  function inten(s) {
    if (!s) return {};
    const heat = clamp01(s.positive_heat);
    const val = Math.abs(Number(s.valence) || 0);
    return {
      memory: clamp01(0.30 + 0.5 * heat + 0.3 * val),
      sleep: clamp01(s.adenosine) * 0.85 + (s.asleep ? 0.15 : 0),
      scar: clamp01(s.scar),
      hormone: clamp01(0.5 * (Number(s.cortisol) || 0)
        + 0.3 * (Number(s.noradrenaline) || 0)
        + 0.2 * (Number(s.oxytocin) || 0)),
      obsess: clamp01(s.obsession_pressure),
      dream: clamp01(Math.max(Number(s.dream_residue) || 0,
        s.asleep ? Number(s.dream_build) || 0 : 0)),
    };
  }

  function project(x, y, z) {
    const s = Math.max(PERSPECTIVE_MIN, CAMERA / (CAMERA + z));
    return { x: W / 2 + x * s, y: H / 2 + y * s + 6, s };
  }

  function orbitPoint(angle, radius, yOff) {
    const x = Math.cos(angle) * radius;
    const z0 = Math.sin(angle) * radius;
    const y0 = yOff || 0;
    const ct = Math.cos(TILT + tiltSpin), st = Math.sin(TILT + tiltSpin);
    return { x, y: y0 * ct - z0 * st, z: y0 * st + z0 * ct };
  }

  function nodePos(n, R, t) {
    const a = n.base + rot;
    const wob = Math.sin(t * 0.7 + n.phase) * 0.06;
    return orbitPoint(a, R * (1 + wob), 0);
  }

  NODES.forEach((n, i) => {
    n.base = -Math.PI / 2 + i * Math.PI / 3;
    n.phase = i * 1.7;
  });

  function draw(t) {
    const s = window.__endoState;
    const iv = inten(s);
    const tension = clamp01(s && s.homeostasis);
    const R = Math.min(W * 0.38, H * 0.46, 168);

    ctx.clearRect(0, 0, W, H);

    dust.forEach(d => {
      const a = d.a + t * 0.02 * d.sp;
      const p = orbitPoint(a, R * d.r * 1.35, d.y * R * 0.9);
      const q = project(p.x, p.y, p.z);
      ctx.beginPath();
      ctx.arc(q.x, q.y, d.s * q.s * 0.9, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(160,205,255,' + (0.05 + 0.18 * q.s).toFixed(3) + ')';
      ctx.fill();
    });

    [1.0, 0.72].forEach((scale, idx) => {
      ctx.beginPath();
      let started = false;
      for (let i = 0; i <= 96; i++) {
        const a = (i / 96) * Math.PI * 2;
        const p = orbitPoint(a, R * scale, 0);
        const q = project(p.x, p.y, p.z);
        if (!started) { ctx.moveTo(q.x, q.y); started = true; } else { ctx.lineTo(q.x, q.y); }
      }
      ctx.closePath();
      ctx.strokeStyle = idx === 0
        ? 'rgba(120,180,255,' + (0.10 + 0.20 * tension).toFixed(3) + ')'
        : 'rgba(120,180,255,0.055)';
      ctx.lineWidth = idx === 0 ? 1.1 : 0.7;
      ctx.stroke();
    });

    const coreA = project(0, 0, 0);
    const coreR = (14 + 8 * tension) * coreA.s;
    const hue = tension > 0.7 ? '251,113,133' : tension > 0.45 ? '251,191,36' : '103,232,249';
    const pulse = 0.5 + 0.5 * Math.sin(t * (1.1 + tension * 3));

    const halo = ctx.createRadialGradient(coreA.x, coreA.y, 0, coreA.x, coreA.y, coreR * 4);
    halo.addColorStop(0, 'rgba(' + hue + ',' + (0.30 + 0.28 * tension).toFixed(2) + ')');
    halo.addColorStop(0.45, 'rgba(' + hue + ',0.08)');
    halo.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(coreA.x, coreA.y, coreR * 4, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.arc(coreA.x, coreA.y, coreR, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(' + hue + ',' + (0.55 + 0.35 * pulse).toFixed(2) + ')';
    ctx.fill();

    const items = NODES.map(n => {
      const p = nodePos(n, R, t);
      const q = project(p.x, p.y, p.z);
      return { n, q, z: p.z, v: clamp01(iv[n.key]) };
    }).sort((a, b) => b.z - a.z);

    items.forEach(({ n, q, v }) => {
      const active = hoverKey === n.key || pinKey === n.key;
      const depth = (q.s - PERSPECTIVE_MIN) / (1 - PERSPECTIVE_MIN);

      ctx.beginPath();
      ctx.moveTo(coreA.x, coreA.y);
      ctx.lineTo(q.x, q.y);
      ctx.strokeStyle = n.color;
      ctx.globalAlpha = (active ? 0.75 : 0.06 + 0.30 * v) * (0.45 + 0.55 * depth);
      ctx.lineWidth = active ? 1.8 : 0.7 + 1.3 * v;
      ctx.stroke();
      ctx.globalAlpha = 1;

      const rr = (2.2 + 5.5 * v) * q.s * (active ? 1.9 : 1);
      const g = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, rr * 4.2);
      g.addColorStop(0, n.color);
      g.addColorStop(0.35, n.color + '88');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.globalAlpha = (active ? 0.95 : 0.35 + 0.5 * v) * (0.5 + 0.5 * depth);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(q.x, q.y, rr * 4.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.beginPath();
      ctx.arc(q.x, q.y, rr, 0, Math.PI * 2);
      ctx.fillStyle = active ? '#ffffff' : n.color;
      ctx.globalAlpha = active ? 1 : 0.65 + 0.3 * v;
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.font = (active ? '600 12px ' : '11px ') + '"Microsoft YaHei",sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = active ? '#ffffff' : 'rgba(222,238,255,' + (0.45 + 0.45 * depth).toFixed(2) + ')';
      const lx = q.x + (q.x - coreA.x) * 0.20;
      const ly = q.y + (q.y - coreA.y) * 0.20;
      ctx.fillText(n.label, lx, ly);
    });

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '600 13px "Microsoft YaHei",sans-serif';
    ctx.fillStyle = 'rgba(240,250,255,.92)';
    ctx.fillText(Math.round(tension * 100) + '%', coreA.x, coreA.y + coreR + 16);
  }

  function hitTest(mx, my) {
    const s = window.__endoState;
    const R = Math.min(W * 0.38, H * 0.46, 168);
    const t = performance.now() / 1000;
    const coreA = project(0, 0, 0);
    const coreR = (14 + 8 * clamp01(s && s.homeostasis)) * coreA.s;
    if (Math.hypot(mx - coreA.x, my - coreA.y) < coreR + 10) return '__center__';
    for (const n of NODES) {
      const p = nodePos(n, R, t);
      const q = project(p.x, p.y, p.z);
      if (Math.hypot(mx - q.x, my - q.y) < 16) return n.key;
    }
    return null;
  }

  function renderMetrics() {
    const v = inten(window.__endoState);
    const html = NODES.map(n => {
      const val = clamp01(v[n.key]);
      return '<div class="homeo-metric" data-key="' + n.key + '">'
        + '<span class="k">' + n.label + '</span>'
        + '<span class="v">' + Math.round(val * 100) + '%</span>'
        + '<span class="track"><span class="fill" style="width:' + (val * 100).toFixed(1)
        + '%;background:' + n.color + '"></span></span>'
        + '</div>';
    }).join('');
    if (metricsEl.dataset.sig !== html) {
      metricsEl.innerHTML = html;
      metricsEl.dataset.sig = html;
    }
  }

  function renderNote() {
    const s = window.__endoState || {};
    const key = pinKey || hoverKey;
    if (key && key !== '__center__') {
      const n = NODES.find(x => x.key === key);
      const v = clamp01(inten(s)[key]);
      noteEl.innerHTML = '<b>' + n.label + '</b> ' + Math.round(v * 100) + '% · ' + n.tip;
      return;
    }
    if (key === '__center__') {
      noteEl.innerHTML = '<b>内稳态张力</b> = 0.30×执念 + 0.25×皮质醇 + 0.20×腺苷 + 0.25×创伤 + 0.10×怒气';
      return;
    }
    const obs = (s.obsessions && s.obsessions.length) ? String(s.obsessions[0].text || '') : '';
    const dream = String(s.dream || '');
    if (obs || dream) {
      const bits = [];
      if (obs) bits.push('执念：' + obs.slice(0, 20));
      if (dream) bits.push('上梦：' + dream.slice(0, 22));
      noteEl.innerHTML = bits.join('　·　');
      return;
    }
    noteEl.textContent = '悬停节点看说明，点击固定；拖动可旋转';
  }

  function pos(e) {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  canvas.addEventListener('mousemove', e => {
    const p = pos(e);
    if (dragging) {
      const dx = p.x - lastX;
      const dy = p.y - lastY;
      rot += dx * 0.009;
      tiltSpin = Math.max(-0.45, Math.min(0.45, tiltSpin + dy * 0.003));
      rotVel = dx * 0.009;
      lastX = p.x;
      lastY = p.y;
      return;
    }
    const hit = hitTest(p.x, p.y);
    if (hit !== hoverKey) {
      hoverKey = hit;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
      renderNote();
    }
  });

  canvas.addEventListener('mousedown', e => {
    const p = pos(e);
    if (hitTest(p.x, p.y)) return;
    dragging = true;
    lastX = p.x;
    lastY = p.y;
    canvas.classList.add('dragging');
  });

  window.addEventListener('mouseup', () => {
    dragging = false;
    canvas.classList.remove('dragging');
  });

  canvas.addEventListener('click', e => {
    const hit = hitTest(pos(e).x, pos(e).y);
    if (hit === '__center__') { pinKey = null; hoverKey = null; renderNote(); return; }
    pinKey = (hit === pinKey) ? null : hit;
    renderNote();
  });

  canvas.addEventListener('mouseleave', () => {
    hoverKey = null;
    renderNote();
  });

  metricsEl.addEventListener('click', e => {
    const m = e.target.closest('.homeo-metric');
    if (!m) return;
    pinKey = (pinKey === m.dataset.key) ? null : m.dataset.key;
    renderNote();
  });
  metricsEl.addEventListener('mouseover', e => {
    const m = e.target.closest('.homeo-metric');
    if (!m) return;
    hoverKey = m.dataset.key;
    renderNote();
  });
  metricsEl.addEventListener('mouseleave', () => {
    hoverKey = null;
    renderNote();
  });

  function loop(now) {
    const t = now / 1000;
    if (!dragging) {
      rot += 0.0011 + rotVel;
      rotVel *= 0.95;
      tiltSpin *= 0.995;
    }
    draw(t);
    renderMetrics();
    renderNote();
    requestAnimationFrame(loop);
  }

  resize();
  if (window.ResizeObserver) {
    new ResizeObserver(resize).observe(canvas.parentElement);
  } else {
    window.addEventListener('resize', resize);
  }
  requestAnimationFrame(loop);
})();
