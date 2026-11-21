/* TA表情导演 (moodface)
 *
 * 作用：轮询生命状态服务，按情绪层级把 Live2D 表情切换过去。
 * 页面只要做一件事：把 core 交给它 —— window.__companionRegisterCore(core)
 *
 * 只动 PARAM_EXP2..PARAM_EXP8，不碰：
 *   PARAM_EXP1  口型切换（怕影响说话）
 *   Paramcol_1/2/3  尾巴、耳朵、水印（这些是模型开关，不能被来回清）
 */
(() => {
  const EXPR_PARAMS = {
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
  };
  const CLEAR_KEYS = ['PARAM_EXP2', 'PARAM_EXP3', 'PARAM_EXP4', 'PARAM_EXP5',
    'PARAM_EXP6', 'PARAM_EXP7', 'PARAM_EXP8'];

  // 各情绪下的"备选小表情"：状态没变时也偶尔换个脸，别一直挂着同一张
  const VIVID_POOLS = {
    happy: ['exp05_brackets', 'exp04_blush', 'exp08_omouth', 'exp02_three_mouth'],
    calm: ['', 'exp05_brackets', 'exp04_blush', 'exp08_omouth', 'exp08_chestnut', 'exp05_oo', 'exp02_three_mouth'],
    low: ['exp08_worry', 'exp08_chestnut', 'exp05_oo', ''],
    sad: ['exp06_xx', 'exp08_worry', ''],
    sleepy: ['exp05_oo', '', 'exp08_omouth'],
  };
  const VIVID_ENABLED = new URLSearchParams(location.search).get('vivid') !== '0';

  function poolFor(s) {
    // 困的时候只给"困"的小表情，别在夜里突然笑成花
    if (s && typeof s.energy === 'number' && s.energy <= 0.45) {
      return VIVID_POOLS.sleepy;
    }
    const level = (s && s.emotion_level) || '平静';
    if (level === '幸福峰值' || level === '开心') return VIVID_POOLS.happy;
    if (level === '低落') return VIVID_POOLS.low;
    if (level === '想哭低谷') return VIVID_POOLS.sad;
    return VIVID_POOLS.calm;
  }

  let flashTimer = null;

  // 短暂闪一个表情（说完一句话的语义反应），之后自动回到当前状态
  window.__companionFlashExpression = (name, ms) => {
    if (!name || window.__companionLockExpression) return;
    const back = want;
    paint(name);
    want = name;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      want = back;
      paint(back);
    }, ms || 1600);
  };

  // 情绪强度：只有真的起伏大了才允许换脸，平时保持平静
  function intensityOf(s) {
    if (!s) return 0;
    const v = Math.abs(s.valence || 0);
    const happy = s.happiness || 0;
    const sad = s.sadness || 0;
    const tired = Math.max(0, 0.55 - (s.energy || 0.6)) / 0.55;
    return Math.max(v, happy * 0.95, sad);
  }
  const VIVID_MIN_INTENSITY = 0.34;


  let holdTimer = null;

  // 听命令：保持某个表情 N 秒（这段时间不被情绪/活泼模式覆盖），然后自动回到真实情绪
  window.__companionShowExpression = (name, ms) => {
    clearTimeout(holdTimer);
    window.__companionLockExpression = true;
    paint(name || '');
    want = name || '';
    holdTimer = setTimeout(() => {
      window.__companionLockExpression = false;
      current = null;      // 强制下一轮按真实情绪重新上色（不然会卡在命令表情上）
      tick();
    }, ms || 8000);
  };

  function maybeVivid() {
    if (!VIVID_ENABLED) return;
    if (window.__companionLockExpression) return;
    if (document.hidden) return;
    if (window.__companionSpeaking) return;   // 说话时不换，免得跟口型打架
    const s = window.__companionMood || {};
    // 2026-11-10：情绪已经有专属脸了，别让随机小表情把它盖掉（平静才活泼）
    const lv = String(s.emotion_level || "平静");
    if (lv !== "平静" && lv !== "") return;
    if (intensityOf(s) < VIVID_MIN_INTENSITY) return;   // 情绪不够强烈就老实待着
    const pool = poolFor(s);
    const pick = pool[Math.floor(Math.random() * pool.length)];
    if (pick === want) return;
    window.__companionFlashExpression(pick, 1400 + Math.random() * 1600);
  }

  function scheduleVivid() {
    setTimeout(() => {
      maybeVivid();
      scheduleVivid();
    }, 7000 + Math.random() * 9000);
  }

  let core = null;
  let current = '';
  let want = '';

  function paint(name) {
    if (!core) return;
    for (const key of CLEAR_KEYS) {
      try { core.setParameterValueById(key, 0); } catch (e) {}
    }
    const params = EXPR_PARAMS[name];
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        try { core.setParameterValueById(key, value); } catch (e) {}
      }
    }
  }

  // 参数会被每帧的模型更新盖掉，所以定期补一次
  setInterval(() => paint(want), 600);

  window.__companionRegisterCore = (c) => {
    core = c;
    paint(want);
  };
  window.__companionSetExpression = (name) => {
    want = name || '';
    paint(want);
    return want;
  };
  window.__companionExpression = () => want;

  const CANDIDATES = location.port === '8005'
    ? ['/api/state']
    : ['/api/mood', `http://${location.hostname || '127.0.0.1'}:8005/api/state`];
  let apiIndex = 0;

  // 视频通话页要看"实时"，2 秒一次；其他页面 5 秒够用
  const IN_CALL = ['8003', '8004'].includes(location.port);
  const POLL_MS = IN_CALL ? 2000 : 5000;

  async function tick() {
    if (window.__companionLockExpression) return;  // 手动切表情时不被自动覆盖
    try {
      const res = await fetch(CANDIDATES[apiIndex], { cache: 'no-store' });
      if (!res.ok) throw new Error(res.status);
      const s = await res.json();
      if (typeof s.expression !== 'string') throw new Error('no expression field');
      window.__companionMood = s;
      if (s.expression !== current) {
        // 2026-11-10：阈值调低后容易在两档之间来回跳，加 2.5 秒防抖
        if (window.__lastFaceAt && Date.now() - window.__lastFaceAt < 2500 && current) return;
        window.__lastFaceAt = Date.now();
        current = s.expression;
        want = current;
        paint(want);
        console.log('[moodface]', want || 'neutral', '·', s.expression_reason || '');
      }
    } catch (e) {
      // 换下一个地址试（手机走 8003 的 /api/mood 代理，PC 直连 8005）
      apiIndex = (apiIndex + 1) % CANDIDATES.length;
    }
  }

  // 让她说完一句话就立刻换表情，不用等下一次轮询
  window.__companionRefreshMood = tick;

  setTimeout(tick, 1200);
  setInterval(tick, POLL_MS);
  if (VIVID_ENABLED) scheduleVivid();
  console.log('[moodface] ready · ' + POLL_MS + 'ms' + (VIVID_ENABLED ? ' · 活泼模式' : ''));
})();
