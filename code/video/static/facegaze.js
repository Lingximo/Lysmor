/*
 * 人脸视线跟随（2026-11-01）
 *
 * 作用：摄像头开着的时候，把"画面里人脸的位置"换算成 -1~1 的视线坐标，
 *       持续喂给 window.setGaze(x, y, 'face')。眼睛/头/身体怎么动由 live2d.js 负责。
 *
 * 三条硬要求（你提的）：
 *   1. 不许乱飘 —— 双重平滑 + 死区 + 迟滞 + 换人不跟丢
 *   2. 模式要分明 —— 摄像头关＝只跟鼠标；开＝锁人脸；脸丢 2 秒才交还鼠标
 *   3. 关摄像头立刻回鼠标 —— 由 app.js 调 setGazeMode('mouse') + 本文件 stop()
 *
 * 认脸模型（约 3.2MB）第一次用时自动下载，之后浏览器自己缓存；
 * 一条路都走不通就不出声地放弃，只当摄像头没有跟随能力，绝不影响通话。
 */
(() => {
  /** 版本锁死：0.10.14 是稳的，别用 latest */
  const V = '0.10.14';
  // 加载顺序：先看本地（如果哪天手工放进去过），再试镜像。
  // 【2026-11-01 实测】国内网络下各镜像下 1MB 的速度：
  //   npmmirror（淘宝）3002 KB/s ｜ unpkg 422 ｜ gcore 285 ｜ testingcf 206 ｜ fastly 163 ｜ cdn.jsdelivr 连不上
  // 所以把 npmmirror 放第一位，first paint 从 30 秒降到几秒。
  const NPM_MIRROR = 'https://registry.npmmirror.com/@mediapipe/tasks-vision/' + V + '/files';
  const MJS_URLS = [
    '/static/face/vision_bundle.mjs',
    NPM_MIRROR + '/vision_bundle.mjs',
    `https://fastly.jsdelivr.net/npm/@mediapipe/tasks-vision@${V}/vision_bundle.mjs`,
    `https://unpkg.com/@mediapipe/tasks-vision@${V}/vision_bundle.mjs`,
  ];
  const WASM_DIRS = [
    '/static/face/wasm',
    NPM_MIRROR + '/wasm',
    `https://fastly.jsdelivr.net/npm/@mediapipe/tasks-vision@${V}/wasm`,
    `https://unpkg.com/@mediapipe/tasks-vision@${V}/wasm`,
  ];
  const MODEL_URLS = [
    '/static/face/blaze_face_short_range.tflite',
    'https://storage.googleapis.com/mediapipe-models/face_detector/'
      + 'blaze_face_short_range/float16/1/blaze_face_short_range.tflite',
  ];

  const DETECT_MS = 66;        // 约 15fps：够顺，又不会把手机 CPU 吃满
  const SLOW_MS = 200;         // 卡了就自动降到 5fps
  const BUDGET_MS = 60;        // 单帧检测超过这个时间就算"卡"
  const DEAD_MS = 900;         // 单帧超过这个先降帧，不到 2 秒绝不放弃
  const GIVE_UP_MS = 2000;     // 真的带不动（>2 秒/帧）才停
  const MIN_FACE_RATIO = 0.10;  // 脸的高度至少要占画面 10%，太小的（背景里的人）不锁
  const REACQUIRE_PX = 0.30;    // 换脸判定：新脸离旧脸超过画面 30% 才算"换人"
  const GAIN = 1.15;            // 视线幅度：脸到画面边缘时她也看到边缘
  const DEADBAND = 0.012;       // 小于这个变化就不发，避免微抖
  const MAX_STEP = 0.22;        // 单次最大跳变，防止突然甩头

  let video = null;
  let detector = null;
  let onState = null;
  let ready = false;
  let failed = false;
  let loadingP = null;
  let running = false;
  let rafId = 0;
  let lastRun = 0;
  let statusNow = '';
  let detectMs = DETECT_MS;    // 当前检测间隔（卡了会自动变大）
  let costAvg = 0;             // 单帧检测耗时的滑动平均

  // —— 平滑：一欧元滤波（静止时几乎不动，动起来跟得上）——
  function makeOneEuro(minCutoff, beta, dCutoff) {
    let xPrev = null, dxPrev = 0, tPrev = 0;
    const alpha = (dt, cutoff) => 1 / (1 + (1 / (2 * Math.PI * cutoff)) / dt);
    return {
      reset() { xPrev = null; dxPrev = 0; tPrev = 0; },
      push(x, t) {
        if (xPrev === null) { xPrev = x; tPrev = t; return x; }
        const dt = Math.max(0.001, (t - tPrev) / 1000);
        tPrev = t;
        const dx = (x - xPrev) / dt;
        const ad = alpha(dt, dCutoff);
        dxPrev += ad * (dx - dxPrev);
        const cutoff = minCutoff + beta * Math.abs(dxPrev);
        const a = alpha(dt, cutoff);
        xPrev += a * (x - xPrev);
        return xPrev;
      },
    };
  }
  const filtX = makeOneEuro(1.1, 0.035, 1.0);
  const filtY = makeOneEuro(1.1, 0.035, 1.0);

  // 当前锁定的那张脸（归一化中心 + 高度占比）
  let locked = null;
  let confirm = 0;   // 连续认定次数
  let miss = 0;      // 连续丢失次数
  let outX = 0, outY = 0;

  function report(state) {
    if (state === statusNow) return;
    statusNow = state;
    try { if (onState) onState(state); } catch (e) { /* 回调出错不影响主流程 */ }
  }

  /**
   * 归一化的人脸中心 -> 视线坐标。
   * 注意：手机自拍预览是镜像（scaleX(-1)），所以 x 要反一次，
   * 不然你往右走她会往左看。
   */
  function toGaze(cxN, cyN, sizeRatio) {
    const damp = sizeRatio < 0.15 ? 0.78 : 1;   // 离得远就只看一眼，不夸张转头
    const gx = -(cxN - 0.5) * 2 * GAIN * damp;
    const gy = (cyN - 0.5) * 2 * GAIN * damp;
    return {
      x: Math.max(-1, Math.min(1, gx)),
      y: Math.max(-1, Math.min(1, gy)),
    };
  }

  /** 从这一帧的检测结果里挑一张该跟的脸 */
  function pick(detections, vw, vh) {
    if (!detections || !detections.length) return null;
    const cand = [];
    for (const d of detections) {
      const b = d.boundingBox;
      if (!b || !b.width || !b.height) continue;
      const score = typeof d.score === 'number' ? d.score : 1;
      if (score < 0.5) continue;
      const hRatio = b.height / vh;
      if (hRatio < MIN_FACE_RATIO) continue;
      const aspect = b.width / b.height;
      if (aspect < 0.5 || aspect > 2.0) continue;   // 太扁/太窄的多半不是正脸
      cand.push({
        cx: (b.originX + b.width / 2) / vw,
        cy: (b.originY + b.height / 2) / vh,
        h: hRatio,
        score,
        area: b.width * b.height,
      });
    }
    if (!cand.length) return null;

    // 有旧锁：优先选离它最近、大小接近的那张（防止两个人时来回跳）
    if (locked) {
      let best = null, bestDist = Infinity;
      for (const c of cand) {
        const dx = c.cx - locked.cx;
        const dy = c.cy - locked.cy;
        const dist = Math.hypot(dx, dy);
        if (dist > REACQUIRE_PX) continue;
        if (Math.min(c.h, locked.h) / Math.max(c.h, locked.h) < 0.55) continue;
        if (dist < bestDist) { bestDist = dist; best = c; }
      }
      // 找不到"同一张"就当这一帧丢了。
      // 早期版本这里还有一条"新脸明显更大就换人"，实测太容易抢锁（视线会跳），
      // 去掉：等旧脸连续 3 帧确认消失、锁清掉之后，再重新锁最大那张。
      return best;
    }

    // 还没有锁：取最大的那张
    cand.sort((a, b) => b.area - a.area);
    return cand[0];
  }

  function send(x, y, now) {
    if (Math.abs(x - outX) < DEADBAND && Math.abs(y - outY) < DEADBAND) return false;
    let dx = x - outX, dy = y - outY;
    const len = Math.hypot(dx, dy);
    if (len > MAX_STEP) { dx = dx / len * MAX_STEP; dy = dy / len * MAX_STEP; }
    outX += dx;
    outY += dy;
    try { window.setGaze(outX, outY, 'face'); } catch (e) { return false; }
    return true;
  }

  /** 给任何 Promise 加超时（网络卡住时不能永远等下去） */
  function withTimeout(promise, ms, label) {
    return Promise.race([
      promise,
      new Promise((_, rej) => setTimeout(() => rej(new Error(label + ' 超时')), ms)),
    ]);
  }

  /** 这个地址真的存在吗（HEAD 探测，6 秒超时；跨域会带 CORS，失败就当没有） */
  async function urlOk(url) {
    try {
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), 6000);
      try {
        const r = await fetch(url, { method: 'HEAD', signal: ac.signal });
        return r.ok;
      } finally {
        clearTimeout(timer);
      }
    } catch (e) {
      return false;
    }
  }

  async function loadFaceTech() {
    if (ready) return true;
    if (loadingP) return loadingP;   // 正在下就复用同一个 promise（不再永久记住失败）

    loadingP = (async () => {
      report('loading');
      let mp = null, lastErr = null;

      // 【修复 2026-11-01 晚】以前是"按顺序试"，但 FilesetResolver.forVisionTasks()
      // 拿到一个不存在的目录**不会报错**，它只是拼出 /static/face/wasm/vision_wasm_internal.js
      // 这个 404 路径一路带下去，最后 createFromOptions 才炸，表现就是
      // "摄像头开了但只跟鼠标"。现在先探测本地到底装全没有，没有就完全不碰本地路径。
      const localOk =
        (await urlOk('/static/face/vision_bundle.mjs')) &&
        (await urlOk('/static/face/wasm/vision_wasm_internal.js')) &&
        (await urlOk('/static/face/blaze_face_short_range.tflite'));

      const bundles = MJS_URLS.filter((u) => localOk || !u.startsWith('/static/'));
      const wasmDirs = WASM_DIRS.filter((u) => localOk || !u.startsWith('/static/'));
      const models = MODEL_URLS.filter((u) => localOk || !u.startsWith('/static/'));

      for (const url of bundles) {
        try { mp = await withTimeout(import(url), 25000, '模块加载'); break; }
        catch (e) { lastErr = e; }
      }
      if (!mp) throw lastErr || new Error('vision_bundle 取不到');

      let fileset = null;
      for (const dir of wasmDirs) {
        try {
          fileset = await withTimeout(
            mp.FilesetResolver.forVisionTasks(dir), 20000, 'wasm 准备');
          break;
        } catch (e) { lastErr = e; }
      }
      if (!fileset) throw lastErr || new Error('wasm 取不到');

      let modelPath = null;
      for (const p of models) {
        if (await urlOk(p)) { modelPath = p; break; }
      }
      if (!modelPath) throw new Error('模型文件取不到');

      const opts = {
        baseOptions: { modelAssetPath: modelPath, delegate: 'GPU' },
        runningMode: 'VIDEO',
        minDetectionConfidence: 0.55,
      };
      try {
        detector = await withTimeout(
          mp.FaceDetector.createFromOptions(fileset, opts), 40000, '模型初始化');
      } catch (e) {
        // 有些机器/浏览器没有可用的 GPU delegate，退回 CPU
        opts.baseOptions.delegate = 'CPU';
        detector = await withTimeout(
          mp.FaceDetector.createFromOptions(fileset, opts), 40000, '模型初始化(CPU)');
      }
      ready = true;
      report('ready');
      return true;
    })()
      .catch((e) => {
        const msg = String((e && (e.message || e.type)) || e);
        window.__companionFaceGazeError = msg;
        console.warn('[facegaze] 认脸没装上，视线继续跟鼠标：', msg);
        // 注意：不把 failed 设成永久 true —— 下次开摄像头会重新试一次
        report('failed');
        return false;
      })
      .finally(() => { loadingP = null; });

    return loadingP;
  }

  function tick(ts) {
    // 先判断再排下一帧：反过来的话 stop() 之后还会多排一帧，
    // 每帧"排一帧然后 return"，rAF 就永远停不下来了。
    if (!running || !detector || !video) { rafId = 0; return; }
    rafId = requestAnimationFrame(tick);
    if (document.hidden) return;
    // 她正在说话的时候不做检测：这时候最要紧的是让语音和画面顺，
    // 检测晚 0.2 秒没人看得出来，但主线程被占住会直接影响她说话。
    if (typeof window.__companionSpeaking === 'boolean' && window.__companionSpeaking) return;
    if (ts - lastRun < detectMs) return;
    lastRun = ts;

    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh || video.paused || video.ended) return;
    if (!video.srcObject) return;

    let face = null;
    const t0 = performance.now();
    try {
      const res = detector.detectForVideo(video, ts);
      face = pick(res && res.detections, vw, vh);
    } catch (e) {
      return;
    }
    // 自测开销：机器带不动就自动降级，别为了跟视线把她的话卡没了
    const cost = performance.now() - t0;
    costAvg = costAvg * 0.8 + cost * 0.2;
    if (costAvg > GIVE_UP_MS) {
      console.warn('[facegaze] 检测太慢（%.0fms/帧），关掉视线跟随，只跟鼠标' % costAvg);
      window.__companionFaceGazeError = '检测太慢（%.0fms/帧），已自动关闭' % costAvg;
      if (window.__paReport) window.__paReport('gaze-giveup', window.__companionFaceGazeError);
      running = false;
      rafId = 0;
      report('failed');
      return;
    }
    // 慢就一路降频，别罢工：900ms 内继续跟，只是更新得稀一点
    if (costAvg > DEAD_MS && detectMs < 500) detectMs = 500;
    else if (costAvg > BUDGET_MS && detectMs < SLOW_MS) detectMs = SLOW_MS;

    if (!face) {
      miss += 1;
      confirm = 0;
      if (miss === 3) locked = null;
      if (miss >= 3) report('searching');
      // 注意：这里什么都不发。live2d 那边会保持最后位置 2 秒再交还鼠标，
      // 所以我们不能继续喂旧坐标，否则 faceAt 一直被刷新，永远交还不回去。
      return;
    }

    miss = 0;
    confirm += 1;
    if (!locked) {
      // 首次锁定要连续认到 2 帧，避免单帧误检
      if (confirm < 2) return;
      locked = face;
      filtX.reset(); filtY.reset();
      outX = 0; outY = 0;
    } else if (confirm >= 2) {
      locked = face;
    }

    const g = toGaze(locked.cx, locked.cy, locked.h);
    const nx = filtX.push(g.x, ts);
    const ny = filtY.push(g.y, ts);
    if (send(nx, ny, ts)) report('locked');
  }

  const api = {
    /** @returns {Promise<boolean>} 认脸是否就绪（false 就只跟鼠标） */
    async start(videoEl, cb) {
      video = videoEl;
      onState = cb || null;
      statusNow = '';        // 重置，保证界面能收到这一轮的进度
      running = true;
      lastRun = 0;
      detectMs = DETECT_MS;
      costAvg = 0;
      confirm = 0;
      miss = 0;
      locked = null;
      outX = 0;
      outY = 0;
      filtX.reset();
      filtY.reset();

      const ok = await loadFaceTech();
      if (!running || !ok) { running = false; return false; }
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(tick);
      return true;
    },

    stop() {
      running = false;
      cancelAnimationFrame(rafId);
      rafId = 0;
      locked = null;
      confirm = 0;
      miss = 0;
      statusNow = '';
      onState = null;
      video = null;
    },

    /** 调试/自测用（不改任何运行时行为） */
    _debug: {
      toGaze,
      pick,
      _setLocked(v) { locked = v; },
    },
  };

  window.__companionFaceGaze = api;

  // 页面加载完、闲 2.5 秒后，先把认脸要用的 3MB 下载并缓存好。
  // 这样你点「让她看见我」的时候不用干等（第一次访问会多这点流量，之后走缓存）。
  window.addEventListener('load', () => {
    setTimeout(() => { loadFaceTech().catch(() => {}); }, 2500);
  });
})();
