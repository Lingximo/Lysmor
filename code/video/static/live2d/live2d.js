// 面板流 panel_stream.py 按标题里的"和TA视频"找窗口，所以标题必须保留这几个字
if (new URLSearchParams(location.search).get('panel') === '1') document.title = '和TA视频 · TAPicoPanel';
(() => {
  const canvas = document.getElementById('live2d');
  if (!canvas || !window.PIXI || !PIXI.live2d) return;
  const compact = new URLSearchParams(location.search).get('compact') === '1';

  const app = new PIXI.Application({
    view: canvas,
    transparent: true,
    resizeTo: window,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    preserveDrawingBuffer: new URLSearchParams(location.search).get("panel") === "1",
  });

  let model = null;
  let holder = null;
  let fitScale = 1;
  let modelBounds = null;   // 角色真实可见包围盒（模型局部像素）

  // ---------------- 视线来源仲裁（2026-11-01） ----------------
  // 规则（你定死的三条）：
  //   摄像头关          → 只听鼠标，和以前一模一样
  //   摄像头开 + 有脸    → 锁人脸
  //   摄像头开 + 脸丢 2 秒 → 自动交还鼠标
  // 换来源时用 280ms 过渡，不硬切，免得看着像抽了一下。
  const FACE_HOLD_MS = 2000;
  const SWITCH_MS = 280;

  let gazeMode = 'mouse';      // 'mouse' | 'face'（由 app.js 开关摄像头时切）
  let mouseX = 0, mouseY = 0, mouseAt = 0;
  let faceX = 0, faceY = 0, faceAt = 0;
  let shownX = 0, shownY = 0;
  let sourceNow = 'none';
  let switchUntil = 0;

  window.setGazeMode = (m) => {
    const next = m === 'face' ? 'face' : 'mouse';
    if (next === gazeMode) return;
    gazeMode = next;
    if (next === 'mouse') faceAt = 0;      // 摄像头一关，人脸坐标立刻作废
    switchUntil = performance.now() + SWITCH_MS;
  };
  window.getGazeMode = () => gazeMode;

  // 2026-11-09：开摄像头时先把视线收回原位，再开始跟脸。
  // 不清的话，她第一眼会从"刚才鼠标所在的方向"开始转，看起来像在瞟鼠标。
  window.resetGaze = () => {
    mouseX = 0; mouseY = 0; mouseAt = 0;
    faceX = 0; faceY = 0; faceAt = 0;
    shownX = 0; shownY = 0;
    switchUntil = 0;
    sourceNow = 'none';
    try { window.__gazeDbg = null; } catch (e) {}
  };

  window.setGaze = (x, y, src) => {
    const nx = Math.max(-1, Math.min(1, Number(x) || 0));
    const ny = Math.max(-1, Math.min(1, Number(y) || 0));
    const now = performance.now();
    if (src === 'face') {
      if (gazeMode !== 'face') return;     // 摄像头没开时，人脸的坐标一律不收
      faceX = nx;
      faceY = ny;
      faceAt = now;
    } else {
      mouseX = nx;
      mouseY = ny;
      mouseAt = now;
    }
  };

  // ---------------- 视线参数映射（2026-11-01 晚，修"低头要滑很多"） ----------------
  // 固定乘系数的老问题：每个模型"能抬头多少 / 能低头多少"是不一样的，
  // 而且这个模型的低头幅度天生比抬头小，所以鼠标要滑很远才看得出低头。
  // 现在两件事：
  //   1. 读模型自己的 min/max/default，按"离静止位还有多少余量"来映射，
  //      不再盲目乘一个数（读不到就退回旧的固定幅度）
  //   2. 向下单独给一个倍率 downBoost，让她低头跟抬头一样好触发
  const GAZE_TUNE = {
    downBoost: 1.2,    // ← 向下轻微加强（觉得还不够就调到 1.4）
    eyeMax: 0.95,      // 眼球最多能偏多少（模型范围就是 ±1）
    // 【2026-11-01 晚实测】这个模型的 ParamAngleX / ParamAngleY 真实范围是 ±30°，
    // 以前只用 9 / 7，等于只用了三分之一，所以"怎么滑都不低头"。
    angleMaxX: 16,
    angleMaxY: 24,
    bodyMaxX: 2.5,     // 身体角度由物理接管，设了也会被覆盖，留着只为兜底
    // 【关键】鼠标停住多久才自动回正。原来是 450ms——
    // 你滑下去看她的功夫她已经回正了，所以永远看不出低头。
    // 现在 6 秒：跟着鼠标停在哪儿就看哪儿，真的不动了才慢慢回正。
    mouseIdleMs: 6000,
  };

  function readRange(core, id) {
    try {
      const idx = core.getParameterIndex(id);
      if (typeof idx !== 'number' || idx < 0) return null;
      const min = core.getParameterMinimumValue(idx);
      const max = core.getParameterMaximumValue(idx);
      const def = core.getParameterDefaultValue(idx);
      if (![min, max, def].every(Number.isFinite)) return null;
      if (max - def < 1e-6 && def - min < 1e-6) return null;
      return { min, max, def };
    } catch (e) {
      return null;   // 不同 live2d 库版本方法名可能不一样，读不到就走兜底
    }
  }

  /** v 在 [-1,1]；按模型余量映射，并限制不超过 cap */
  function mapParam(v, r, cap) {
    if (!r) return v * cap;
    const span = v >= 0 ? (r.max - r.def) : (r.def - r.min);
    return r.def + v * Math.min(span, cap);
  }

  const RANGES = {};

  const EXPR_PARAMS = {
    exp01_mouth: { PARAM_EXP1: 1 },
    exp02_three_mouth: { PARAM_EXP2: 1 },
    exp02_grit: { PARAM_EXP2: -1 },
    exp03_dark: { PARAM_EXP3: 1 },
    exp04_blush: { PARAM_EXP4: 1 },
    exp05_oo: { PARAM_EXP5: 1 },
    exp05_brackets: { PARAM_EXP5: -1 },
    exp06_xx: { PARAM_EXP6: 1 },
    exp07_drool: { PARAM_EXP7: 1 },
    exp08_omouth: { PARAM_EXP8: 1 },
    exp08_worry: { PARAM_EXP7: -1 },
    exp08_chestnut: { PARAM_EXP8: -1 },
    exp11_tail_hide: { Paramcol_1: 2 },
    exp12_ear_hide: { Paramcol_2: 1 },
    exp13_watermark_hide: { Paramcol_3: 1 },
  };

  window.setExpression = async (name) => {
    try {
      const core = model?.internalModel?.coreModel;
      if (!core) return false;
      for (const key of ['PARAM_EXP1', 'PARAM_EXP2', 'PARAM_EXP3', 'PARAM_EXP4',
        'PARAM_EXP5', 'PARAM_EXP6', 'PARAM_EXP7', 'PARAM_EXP8',
        'Paramcol_1', 'Paramcol_2', 'Paramcol_3']) {
        try { core.setParameterValueById(key, 0); } catch (e) {}
      }
      const params = EXPR_PARAMS[name];
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          try { core.setParameterValueById(key, value); } catch (e) {}
        }
      }
      return true;
    } catch (e) {
      console.warn('expression failed', name, e);
      return false;
    }
  };

  // ---------------- 构图参数（2026-11-16） ----------------
  // 背景：模型画布四周有透明留白，按"整幅塞进屏幕"算出来的她偏小、还飘在中间。
  // 现在默认放大一点、并且坐到画面底边（像视频通话里坐在镜头前），
  // 面板模式（panel=1，给 PICO 浮窗截图的）保持原样。
  const LAYOUT_QP = new URLSearchParams(location.search);
  const LAYOUT_PANEL = LAYOUT_QP.get('panel') === '1';
  const numOr = (v, d) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : d;
  };
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const LAYOUT = {
    // zoom=1：角色可见高度刚好等于屏幕高；>1 放大 → 下半身出画面（视频通话构图）
    zoom: numOr(LAYOUT_QP.get('l2dz'), LAYOUT_PANEL ? 1.0 : 1.85),
    ax: clamp01(numOr(LAYOUT_QP.get('l2dx'), LAYOUT_PANEL ? 0.5 : 0.56)),
    ay: clamp01(numOr(LAYOUT_QP.get('l2dy'), LAYOUT_PANEL ? 0.5 : 1.0)),
    top: clamp01(numOr(LAYOUT_QP.get('l2dtop'), 0.05)),   // 头顶留白（占屏高比例）
  };

  // 扫一遍 WebGL 画布的 alpha：画布上只有角色，透明区域 alpha=0，
  // 所以算出来的就是角色真实的可见范围（模型画布四周的留白不算）。
  function measureModelBounds() {
    if (modelBounds) return;   // 只量一次
    try {
      // 先临时回到"全身塞满、居中"的已知状态，这样画布上能看全她，
      // 量出来的才是完整包围盒（否则在放大裁切后的画面上量，只能量到可见那截）。
      const w0 = app.renderer.width / app.renderer.resolution;
      const h0 = app.renderer.height / app.renderer.resolution;
      const s0 = Math.min(w0 / model.width, h0 / model.height) * 0.96;
      holder.scale.set(s0);
      holder.x = (w0 - model.width * s0) / 2;
      holder.y = (h0 - model.height * s0) / 2;
      app.renderer.render(app.stage);          // 保证画布内容是最新的一帧
      const view = app.view;
      const c = document.createElement('canvas');
      c.width = view.width;
      c.height = view.height;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.drawImage(view, 0, 0);
      const img = ctx.getImageData(0, 0, c.width, c.height);
      const d = img.data;
      const w = c.width, h = c.height;
      let x0 = w, y0 = h, x1 = -1, y1 = -1;
      for (let y = 0; y < h; y++) {
        const row = y * w;
        for (let x = 0; x < w; x++) {
          if (d[(row + x) * 4 + 3] > 8) {
            if (x < x0) x0 = x;
            if (x > x1) x1 = x;
            if (y < y0) y0 = y;
            if (y > y1) y1 = y;
          }
        }
      }
      if (x1 > x0 && y1 > y0) {
        const res = app.renderer.resolution || 1;
        // 画布上的坐标 = 模型本地坐标 * fitScale + holder 偏移；
        // 这里反算回模型本地坐标（fit() 用的是本地坐标）
        const sc = s0 || 1;
        const ox = holder.x || 0, oy = holder.y || 0;
        const lx0 = (x0 / res - ox) / sc, ly0 = (y0 / res - oy) / sc;
        const lx1 = (x1 / res - ox) / sc, ly1 = (y1 / res - oy) / sc;
        modelBounds = { x0: lx0, y0: ly0, x1: lx1, y1: ly1,
                        w: lx1 - lx0, h: ly1 - ly0 };
        fit();   // 量完立刻按真实范围重排
        console.log('[live2d] 角色可见范围', JSON.stringify(modelBounds),
                    'canvas', model.width, model.height);
      }
    } catch (e) {
      console.warn('measureModelBounds failed', e);
    }
  }

  function fit() {
    if (!model || !holder) return;
    const w = app.renderer.width / app.renderer.resolution;
    const h = app.renderer.height / app.renderer.resolution;
    const useBounds = !LAYOUT_PANEL && modelBounds && modelBounds.h > 10 && modelBounds.w > 10;
    const bw = useBounds ? modelBounds.w : model.width;
    const bh = useBounds ? modelBounds.h : model.height;
    // 视频通话构图：zoom=1 全身满屏高，>1 放大（下半身出画）
    let s = (h / bh) * LAYOUT.zoom;
    // 横向最多放到占满画面（不裁左右）
    if (bw * s > w * 1.0) s = w / bw;
    fitScale = s;
    holder.scale.set(fitScale);
    if (useBounds) {
      // 横向按 ax 摆；纵向按"头顶留 top"来定（这样放大是从脚下切，不会切掉头）
      holder.x = (w - bw * s) * LAYOUT.ax - modelBounds.x0 * s;
      holder.y = h * LAYOUT.top - modelBounds.y0 * s;
    } else {
      const dw = model.width * fitScale;
      const dh = model.height * fitScale;
      holder.x = (w - dw) * LAYOUT.ax;
      holder.y = (h - dh) * LAYOUT.ay;
    }
    updateHeadAnchor();   // 布局变了，视线原点跟着重算
  }

  // ---------------- 视线的基准点 = 她的头（2026-11-01 晚） ----------------
  // 以前用屏幕中心当原点，可她是上半身构图、头在画面偏上，
  // 于是鼠标必须滑到中线以下才开始低头 —— 你的原话：
  // "当鼠标在她的头下方时就应该要低头了"。
  // 现在按模型实际布局算出她脸的位置当原点：鼠标一低于这条线，gy 立刻为正。
  let headX = innerWidth / 2;
  let headY = innerHeight * 0.45;
  // 脸在模型包围盒里的纵向位置（0=顶）。偏了就调这个：
  //   地址后面加 ?headr=0.15 （数值越小 = 认为脸越靠上 = 更早就低头）
  const HEAD_ANCHOR_RATIO = (() => {
    const v = parseFloat(new URLSearchParams(location.search).get('headr'));
    return Number.isFinite(v) && v > 0.02 && v < 0.6 ? v : 0.18;
  })();

  function updateHeadAnchor() {
    if (!model || !holder) return;
    try {
      if (modelBounds && !LAYOUT_PANEL) {
        headX = holder.x + (modelBounds.x0 + modelBounds.w * 0.5) * fitScale;
        headY = holder.y + (modelBounds.y0 + modelBounds.h * HEAD_ANCHOR_RATIO) * fitScale;
      } else {
        headX = holder.x + model.width * fitScale * 0.5;
        headY = holder.y + model.height * fitScale * HEAD_ANCHOR_RATIO;
      }
    } catch (e) {
      headX = innerWidth / 2;
      headY = innerHeight * 0.45;
    }
    window.__companionHeadAnchor = { x: headX, y: headY };
  }

  /** 屏幕坐标 → 视线坐标（以她的头为原点，上下按到屏幕边缘各自拉满） */
  window.__companionGazeFromPoint = (cx, cy) => {
    const gx = (cx - headX) / (innerWidth * 0.55);
    const dy = cy - headY;
    const upSpan = Math.max(90, headY);                  // 头到顶边的距离
    const downSpan = Math.max(90, innerHeight - headY);  // 头到底边的距离
    const gy = dy >= 0 ? dy / downSpan : dy / upSpan;
    return { x: gx, y: gy };
  };

  window.addEventListener('mousemove', e => {
    const g = window.__companionGazeFromPoint(e.clientX, e.clientY);
    window.setGaze(g.x, g.y, 'mouse');
  });

  (async () => {
    try {
      model = await PIXI.live2d.Live2DModel.from('/static/live2d/companion_full/model3.json', {
        // 2026-11-09: disable pixi auto mouse-follow, it overrides our gaze logic
    // (owner found: mouse position became her 'forward' direction)
    autoInteract: false,
      });
      holder = new PIXI.Container();
      holder.addChild(model);
      app.stage.addChild(holder);

      setTimeout(() => { measureModelBounds(); fit(); }, 60);   // 等一帧再量
      fit();
      window.addEventListener('resize', fit);
      window.__live2dReady = true;
      document.getElementById('avatar-picker')?.style.setProperty('display', 'none');
      const initialExpr = new URLSearchParams(location.search).get('expr');
      if (initialExpr) {
        setTimeout(() => window.setExpression(initialExpr), 1200);
      } else {
        setTimeout(() => window.setExpression('exp13_watermark_hide'), 1500);
      }
      if (new URLSearchParams(location.search).get('panel') === '1') {
        setInterval(() => {
          try {
            app.view.toBlob((blob) => {
              if (blob) fetch('/panel/frame', { method: 'POST', body: blob }).catch(() => {});
            }, 'image/png');
          } catch (e) {}
        }, 90);
      }
      window.dumpLive2DArch = () => {
        try {
          const core = model.internalModel.coreModel;
          const count = core.getDrawableCount();
          const orders = core.getDrawableRenderOrders ? core.getDrawableRenderOrders() : null;
          const counts = core.getDrawableMaskCounts ? core.getDrawableMaskCounts() : null;
          const masks = core.getDrawableMasks ? core.getDrawableMasks() : null;
          const arr = [];
          for (let i = 0; i < count; i++) {
            arr.push({
              i,
              id: core.getDrawableId(i),
              order: orders ? orders[i] : core.getDrawableRenderOrder(i),
              maskCount: counts ? counts[i] : 0,
              masks: masks && masks[i] ? Array.from(masks[i]) : [],
              part: core.getDrawableParentPartIndex ? core.getDrawableParentPartIndex(i) : -1,
            });
          }
          const payload = { count, drawables: arr };
          fetch('/api/live2d_arch', { method: 'POST', body: JSON.stringify(payload) })
            .catch(() => {});
        } catch (e) {
          fetch('/api/live2d_arch', { method: 'POST', body: JSON.stringify({ error: String(e) }) })
            .catch(() => {});
        }
      };
      setTimeout(() => window.dumpLive2DArch(), 2500);
      const core = model.internalModel?.coreModel;
      // 一次性把要用到的参数范围读出来（模型加载后就不会变了）
      RANGES.eyeX = readRange(core, 'ParamEyeBallX');
      RANGES.eyeY = readRange(core, 'ParamEyeBallY');
      RANGES.angleX = readRange(core, 'ParamAngleX');
      RANGES.angleY = readRange(core, 'ParamAngleY');
      RANGES.bodyX = readRange(core, 'ParamBodyAngleX');
      try {
        console.log('[live2d] 视线参数范围', JSON.stringify(RANGES));
      } catch (e) {}
      window.__companionGazeRanges = RANGES;   // 调试用：控制台敲 __companionGazeRanges 就能看
      window.__companionCore = core;           // 调试用：读参数真实取值
      // 一次性取一份"她现在到底被设成什么"，供自测/排查
      window.__companionGazeDebug = () => {
        const g = (id) => {
          try { return core?.getParameterValueById?.(id); } catch (e) { return null; }
        };
        return {
          head: window.__companionHeadAnchor,
          gaze: { x: window.__gazeX, y: window.__gazeY },
          mode: window.getGazeMode?.(),
          ranges: RANGES,
          params: {
            eyeX: g('ParamEyeBallX'), eyeY: g('ParamEyeBallY'),
            angleX: g('ParamAngleX'), angleY: g('ParamAngleY'),
            bodyX: g('ParamBodyAngleX'),
          },
        };
      };
      window.__companionRegisterCore?.(core);
      app.ticker.add(() => {
        const now = performance.now();
        const t = now / 1000;
        try {
          // —— 这一次听谁的 ——
          // 2026-11-09：部署者要求"摄像头开就只跟脸，关掉才跟鼠标"。
          // 以前是"脸丢 2 秒就交还鼠标"，结果坐着不动时眼睛又去跟鼠标了。
          // 现在：face 模式下鼠标完全不参与；脸 8 秒没见才慢慢回正（不是找鼠标）。
          const faceMode = gazeMode === 'face';
          const faceStale = faceAt === 0 || (now - faceAt) > 8000;
          const source = faceMode ? 'face' : 'mouse';
          if (source !== sourceNow) {
            sourceNow = source;
            switchUntil = now + SWITCH_MS;   // 换来源：平滑过渡，不硬切
          }

          const tx = faceMode ? (faceStale ? 0 : faceX) : mouseX;
          const ty = faceMode ? (faceStale ? 0 : faceY) : mouseY;

          // 诊断：当前到底听的是谁（只读，不影响行为）
          window.__gazeDbg = {
            src: source, mode: gazeMode,
            faceAge: faceAt ? Math.round(now - faceAt) : -1,
            faceX: +faceX.toFixed(2), faceY: +faceY.toFixed(2),
            mouseX: +mouseX.toFixed(2), mouseY: +mouseY.toFixed(2),
            target: [+tx.toFixed(2), +ty.toFixed(2)],
          };

          if (now < switchUntil) {
            shownX += (tx - shownX) * 0.20;
            shownY += (ty - shownY) * 0.20;
          } else {
            shownX = tx;
            shownY = ty;
          }

          // 既没人脸、鼠标也 450ms 没动 → 慢慢回正（和以前一样）
          // 注意：必须把回正后的值写回 mouseX/mouseY，否则下一帧又被
          // "shownX = tx" 直接赋回鼠标最后的位置，于是每帧在两者之间来回跳，
          // 看着就是眼睛在抖。这是自测抓出来的真 bug。
          if (!faceMode && (now - mouseAt) > GAZE_TUNE.mouseIdleMs && now >= switchUntil) {
            shownX += (0 - shownX) * 0.24;
            shownY += (0 - shownY) * 0.24;
            mouseX = shownX;
            mouseY = shownY;
          }

          const gx = Math.max(-1, Math.min(1, shownX));
          const gy = Math.max(-1, Math.min(1, shownY));
          window.__gazeX = gx;          // 兼容旧读取方
          window.__gazeY = gy;
          window.__gazeTime = now;

          // 向下单独加强：模型低头本来就比抬头弱，同样一段鼠标位移看不出来
          const gyDown = gy > 0 ? Math.min(1, gy * GAZE_TUNE.downBoost) : gy;
          const gyParam = -gyDown;      // 参数里"正"= 向上

          core?.setParameterValueById('ParamEyeBallX', mapParam(gx, RANGES.eyeX, GAZE_TUNE.eyeMax));
          core?.setParameterValueById('ParamEyeBallY', mapParam(gyParam, RANGES.eyeY, GAZE_TUNE.eyeMax));
          core?.setParameterValueById('ParamAngleX',
            Math.sin(t * 0.7) * 2 + mapParam(gx, RANGES.angleX, GAZE_TUNE.angleMaxX));
          core?.setParameterValueById('ParamAngleY',
            Math.sin(t * 0.9 + 0.7) * 2 + mapParam(gyParam, RANGES.angleY, GAZE_TUNE.angleMaxY));
          core?.setParameterValueById('ParamBodyAngleX',
            Math.sin(t * 0.45) * 1.5 + mapParam(gx, RANGES.bodyX, GAZE_TUNE.bodyMaxX));
          core?.setParameterValueById('ParamBreath', (Math.sin(t * 1.25) + 1) * 0.5);
          core?.setParameterValueById('ParamMouthOpenY', Math.min(0.9, Number(window.__companionLevel || 0) * 2.2));
        } catch (e) {}
      });
      console.log('Live2D ready', model.width, model.height);
    } catch (e) {
      console.error('Live2D load failed', e);
    }
  })();
})();













