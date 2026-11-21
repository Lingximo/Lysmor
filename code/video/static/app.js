// 前端诊断（2026-11-09）：把错误和关键动作用 sendBeacon 报到服务端，
// 这样即使手机/夸克看不到控制台，也能知道到底哪一步断了。
(function () {
  function report(tag, msg) {
    try {
      const body = JSON.stringify({ tag: tag, msg: String(msg || '').slice(0, 300),
                                    ua: navigator.userAgent.slice(0, 120),
                                    t: Date.now() });
      if (navigator.sendBeacon) navigator.sendBeacon('/api/jslog', body);
      else fetch('/api/jslog', { method: 'POST', body: body, keepalive: true });
    } catch (e) {}
  }
  window.__paReport = report;
  window.addEventListener('error', function (e) {
    report('error', (e && e.message) + ' @ ' + (e && e.filename) + ':' + (e && e.lineno));
  });
  window.addEventListener('unhandledrejection', function (e) {
    report('reject', (e && e.reason && (e.reason.message || e.reason)) || 'unknown');
  });
  report('boot', 'app.js loaded ' + document.readyState + ' build=2000');
})();

(() => {
  const canvas = document.getElementById('stage');
  const ctx = canvas.getContext('2d');
  const statusEl = document.getElementById('status');
  const captions = document.getElementById('captions');
  const transcript = document.getElementById('transcript');
  const mic = document.getElementById('mic');
  const micLabel = document.getElementById('mic-label');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const hint = document.getElementById('hint');

  // 旧版静态立绘（Q版/完全体/女仆/少女/冬日）和「选形象」侧栏已经撤掉：
  // 现在只用 Live2D，那几张 2D 图平时看不见、白占 5.7MB。
  // 备份在 D:\你的数据目录\video\_removed-2d-20261031\

  const BACKGROUNDS = {
    dawn: '/static/bg/dawn.jpg',
    morning: '/static/bg/morning.jpg',
    noon: '/static/bg/noon.jpg',
    afternoon: '/static/bg/afternoon.jpg',
    evening: '/static/bg/evening.jpg',
    night: '/static/bg/night.jpg',
  };
  const bgLayers = [
    document.getElementById('bg-a'),
    document.getElementById('bg-b'),
  ];
  let bgActive = 0;
  let bgKey = '';

  function periodKey(hour) {
    if (hour >= 5 && hour < 8) return 'dawn';
    if (hour >= 8 && hour < 11) return 'morning';
    if (hour >= 11 && hour < 14) return 'noon';
    if (hour >= 14 && hour < 18) return 'afternoon';
    if (hour >= 18 && hour < 22) return 'evening';
    return 'night';
  }

  function applyBackground(force = false) {
    const key = periodKey(new Date().getHours());
    if (!force && key === bgKey) return;
    const next = bgLayers[1 - bgActive];
    next.style.backgroundImage = `url("${BACKGROUNDS[key]}")`;
    next.classList.add('show');
    bgLayers[bgActive].classList.remove('show');
    bgActive = 1 - bgActive;
    bgKey = key;
  }

  Object.values(BACKGROUNDS).forEach(src => {
    const img = new Image();
    img.src = src;
  });

  let W = 0, H = 0, dpr = 1;
  let t0 = performance.now();
  let level = 0;
  let targetLevel = 0;
  let speaking = false;
  let thinking = false;
  let ws = null;
  let audioCtx = null;
  const IS_PANEL = new URLSearchParams(location.search).get('panel') === '1';
  let analyser = null;
  let currentAudio = null;
  let recognition = null;
  let listening = false;
  let finalBuffer = '';
  let interimBuffer = '';
  let micStream = null;
  let meterCtx = null;
  let meterAnalyser = null;
  let meterData = null;
  let meterLevel = 0;
  let stars = [];

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    stars = Array.from({ length: 90 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      r: Math.random() * 1.3 + .2, a: Math.random() * .4 + .08,
      p: Math.random() * Math.PI * 2
    }));
  }

  function setStatus(text, color) {
    statusEl.textContent = text;
    statusEl.style.color = color || '#7f93b8';
  }

  function bubble(text, who) {
    const div = document.createElement('div');
    div.className = 'bubble ' + who;
    div.textContent = text;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
    while (transcript.children.length > 24) transcript.removeChild(transcript.firstChild);
  }

  // 流式回复：先建一个气泡，字一段段往上贴；最后用整段文本校准一次
  let streamBubble = null;
  function resetStreamBubble() { streamBubble = null; }
  function appendDelta(text) {
    if (!text) return;
    if (!streamBubble) {
      streamBubble = document.createElement('div');
      streamBubble.className = 'bubble bot';
      transcript.appendChild(streamBubble);
    }
    streamBubble.textContent += text;
    transcript.scrollTop = transcript.scrollHeight;
    showCaption(streamBubble.textContent);
  }
  function finishReply(text) {
    if (streamBubble) {
      if (text) streamBubble.textContent = text;   // 以整段为准，防止漏字/重复
      streamBubble = null;
    } else {
      bubble(text, 'bot');                          // 老路径：没有流式，直接贴
    }
    showCaption(text);
  }

  function showCaption(text) {    captions.textContent = text;
    captions.classList.add('show');
    clearTimeout(showCaption._t);
    showCaption._t = setTimeout(() => captions.classList.remove('show'), 6000);
  }

  function getAudioCtx() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }

  // iOS 音频会话：录完音会把 type 切成 'playback'（为了让她说话走外放）。
  // 但只要会话停在 'playback'，Safari 再申请麦克风就直接 NotAllowedError ——
  // 表现就是"第一次能用，之后每次都说无权限"。所以每次开录之前必须切回来，
  // 而且要在用户那次点击的手势里切。
  let lastMicError = '';
  function sessionForCapture() {
    try {
      const s = navigator.audioSession;
      if (!s || s.type === 'play-and-record') return;
      s.type = 'play-and-record';
    } catch (e) {
      // 老版本 iOS 不认这个值：退回 auto，至少别把会话锁死在 playback
      try { navigator.audioSession.type = 'auto'; } catch (e2) {}
    }
  }
  function sessionForPlayback() {
    try {
      const s = navigator.audioSession;
      if (s && s.type !== 'playback') s.type = 'playback';
    } catch (e) {}
  }

  async function ensureMicMeter() {
    if (micStream && meterAnalyser) {
      if (meterCtx && meterCtx.state === 'suspended') meterCtx.resume();
      return true;
    }
    // 【已修】原来这里写的是 if (micStream && micAnalyser)，但 micAnalyser 从来没声明过。
    // 第一次进来 micStream 是 null，短路躲过去了；第二次进来（比如先点「测麦克风」
    // 再点「说话」）就会抛 ReferenceError: micAnalyser is not defined，
    // 表现是「点了说话没反应」。现在判断真正的 meterAnalyser。
    // 另外开新的之前先把旧的收干净，否则旧的流和 AudioContext 不会释放，
    // 录完浏览器麦克风指示灯还亮着。
    if (micStream || meterCtx) stopMicMeter();
    const bar = document.getElementById('mic-level');
    const label = document.getElementById('meter-text');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      label.textContent = '不支持检测';
      return false;
    }
    try {
      sessionForCapture();   // 关键：先把会话从 playback 切回"要录音"
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      lastMicError = '';
      meterCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = meterCtx.createMediaStreamSource(micStream);
      meterAnalyser = meterCtx.createAnalyser();
      meterAnalyser.fftSize = 512;
      src.connect(meterAnalyser);
      meterData = new Uint8Array(meterAnalyser.fftSize);
      label.textContent = '正在检测';
      meterLoop();
      return true;
    } catch (e) {
      lastMicError = e.name || '';
      // 一次重试：会话状态切换在个别 iOS 版本上是异步生效的
      if (e.name === 'NotAllowedError') {
        try {
          await new Promise(r => setTimeout(r, 180));
          sessionForCapture();
          micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true },
          });
          lastMicError = '';
          meterCtx = new (window.AudioContext || window.webkitAudioContext)();
          const src2 = meterCtx.createMediaStreamSource(micStream);
          meterAnalyser = meterCtx.createAnalyser();
          meterAnalyser.fftSize = 512;
          src2.connect(meterAnalyser);
          meterData = new Uint8Array(meterAnalyser.fftSize);
          label.textContent = '正在检测';
          meterLoop();
          return true;
        } catch (e2) {
          lastMicError = e2.name || lastMicError;
        }
      }
      label.textContent = lastMicError === 'NotAllowedError' ? '未授权' : '打不开';
      bar.style.width = '0%';
      return false;
    }
  }

  function stopMicMeter() {
    if (micStream) {
      try { micStream.getTracks().forEach(t => t.stop()); } catch {}
      micStream = null;
    }
    if (meterCtx) {
      try { meterCtx.close(); } catch {}
      meterCtx = null;
    }
    meterAnalyser = null;
    meterData = null;
    meterLevel = 0;
    restorePlaybackRoute();
    const bar = document.getElementById('mic-level');
    const label = document.getElementById('meter-text');
    if (bar) bar.style.width = '0%';
    if (bar) bar.classList.remove('hot');
    if (label) {
      label.textContent = '已关闭';
      label.classList.remove('live', 'hot');
    }
  }

  function meterLoop() {
    if (!meterAnalyser || !meterData) return;
    const bar = document.getElementById('mic-level');
    const label = document.getElementById('meter-text');
    meterAnalyser.getByteTimeDomainData(meterData);
    let sum = 0;
    for (let i = 0; i < meterData.length; i++) {
      const v = (meterData[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / meterData.length);
    const target = Math.min(1, rms * 6.5);
    meterLevel += (target - meterLevel) * 0.28;
    const pct = Math.round(meterLevel * 100);
    bar.style.width = pct + '%';
    bar.classList.toggle('hot', meterLevel > 0.72);
    label.classList.toggle('live', meterLevel > 0.05);
    label.classList.toggle('hot', meterLevel > 0.72);
    label.textContent = meterLevel > 0.72 ? '有点大声' : (meterLevel > 0.05 ? '有声音' : '很安静');
    requestAnimationFrame(meterLoop);
  }

  const callSid = (() => {
    try {
      const key = 'companion_call_sid';
      let sid = localStorage.getItem(key);
      if (!sid) {
        sid = (window.crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : String(Date.now()) + Math.random().toString(16).slice(2);
        localStorage.setItem(key, sid);
      }
      return sid;
    } catch (e) {
      return String(Date.now()) + Math.random().toString(16).slice(2);
    }
  })();

  let wsRetry = 0;
  let wsReconnectTimer = null;

  function connectWS() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
    if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws?sid=${encodeURIComponent(callSid)}` + (IS_PANEL ? '&panel=1' : ''));
    ws.onopen = () => {
      wsRetry = 0;
      setStatus('在线 · 可以说话了', '#67e8f9');
    };
    ws.onclose = () => {
      // 手机切后台、锁屏、信号抖动都会断；退避重连，别一直硬砸
      wsRetry += 1;
      const delay = Math.min(12000, 900 * Math.pow(1.8, Math.min(wsRetry - 1, 5)));
      setStatus(wsRetry <= 1
        ? '连接断开，正在重连…'
        : `连接断开，${Math.round(delay / 1000)} 秒后再试（第 ${wsRetry} 次）`, '#fb7185');
      wsReconnectTimer = setTimeout(connectWS, delay);
    };
    ws.onerror = () => setStatus('连接出错，正在重连…', '#fb7185');
    ws.onmessage = ev => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (data.type === 'ready') {
        setStatus('在线 · 可以说话了', '#67e8f9');
      } else if (data.type === 'status') {
        thinking = data.status === 'thinking';
        speaking = data.status === 'speaking';
        if (thinking) {
          beginReplyAudio();
          resetStreamBubble();
          setStatus('她在想…', '#a78bfa');
        } else if (speaking) setStatus('她在说… · 点麦克风可以打断', '#67e8f9');
        else if (data.status === 'listening') setStatus('她在听…', '#a78bfa');
        else setStatus('在线 · 可以说话了', '#67e8f9');
      } else if (data.type === 'delta') {
        // 流式：字先出来，声音按句跟上，不用等整段合成完
        appendDelta(data.text || '');
      } else if (data.type === 'audio') {
        if (data.audio && !shouldSuppressReply(data.audio)) enqueueAudio(data.audio, data.seq);
        else if (data.seq !== undefined) enqueueAudio('', data.seq);   // 空句也要推进序号
      } else if (data.type === 'reply') {
        finishReply(data.text || '');
        // 兼容老服务端：整段音频还是走 reply
        if (data.audio && !shouldSuppressReply(data.audio)) enqueueAudio(data.audio);
        // 她刚说完话：如果用户点了表情，就先照做；否则按语义闪一下
        if (data.expression !== undefined && window.__companionShowExpression) {
          window.__companionShowExpression(data.expression, (data.expression_sec || 8) * 1000);
        } else {
          reactExpression(data.text || '');
        }
      } else if (data.type === 'blocked') {
      if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
      showBlocked(data.reason || '陪玩中，视频通话已隔离');
    } else if (data.type === 'companion') {
        // 桌面小人自己会冒气泡；这里只在页面聊天气泡里留一份
        bubble(data.text || '', 'her');
        if (data.audio && !shouldSuppressReply(data.audio)) enqueueAudio(data.audio);
      } else if (data.type === 'presence') {
        // 她注意到你在不在（2026-11-09）
        if (data.state === 'in') {
          setStatus('她看见你回来了', '#67e8f9');
        } else if (data.state === 'out') {
          setStatus('你走开了，她还在', '#94a3b8');
        }
      } else if (data.type === 'error') {
        bubble('（没接上：' + (data.message || '未知错误') + '）', 'sys');
        setStatus('出错了', '#fb7185');
      }
    };
  }

  // 诊断：任何地方切"听脸/听鼠标"，都报一下谁切的（带调用行）
  (function wrapGazeMode() {
    if (window.__gazeModeWrapped || typeof window.setGazeMode !== 'function') return;
    window.__gazeModeWrapped = true;
    const orig = window.setGazeMode;
    window.setGazeMode = function (m) {
      try {
        if (window.__paReport) {
          const st = (new Error().stack || '').split('\n').slice(2, 4).join(' | ');
          window.__paReport('gaze-mode', m + ' @ ' + st.slice(0, 160));
        }
      } catch (e) {}
      return orig(m);
    };
  })();

  // 陪玩（2026-11-09）：开关只控制桌面上的小人（旧版 overlay.py），页面内不再画人
  let playalongOn = false;
  const playalongBtn = document.getElementById('playalong');
  const playalongLabel = document.getElementById('playalong-label');
  function paintPlayalong() {
    if (!playalongBtn) return;
    playalongBtn.classList.toggle('on', playalongOn);
    if (playalongLabel) playalongLabel.textContent = playalongOn ? '陪玩中' : '陪玩';
  }
  if (playalongBtn) {
    // 进页面先问服务器：可能上次小人崩了，开关其实已经关了
    fetch('/api/companion/state').then(r => r.json()).then(j => {
      playalongOn = !!(j.on && (j.overlay_pids || []).length);
      paintPlayalong();
    }).catch(() => {});
    playalongBtn.addEventListener('click', async () => {
      playalongOn = !playalongOn;
      paintPlayalong();
      try {
        const res = await fetch('/api/companion/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ on: playalongOn }),
        });
        const j = await res.json();
        if (!j.ok) {
          toast('陪玩没开起来：' + (j.overlay || j.error || '未知'));
          playalongOn = false;
          paintPlayalong();
        } else if (playalongOn) {
          setStatus('陪玩中 · 桌面上的她会看着屏幕', '#67e8f9');
        } else {
          setStatus('陪玩已关', '#94a3b8');
        }
      } catch (e) {
        toast('陪玩开关失败');
        playalongOn = false;
        paintPlayalong();
      }
    });
    paintPlayalong();
  }

  // 记录最后一次"人脸视线"坐标（诊断用，每秒覆盖）
  (function wrapGaze() {
    if (window.__gazeWrapInstalled) return;
    window.__gazeWrapInstalled = true;
    const orig = window.setGaze;
    if (typeof orig !== 'function') return;
    window.setGaze = function (x, y, src) {
      if (src === 'face') window.__lastFaceGaze = [Number(x).toFixed(2), Number(y).toFixed(2)];
      return orig(x, y, src);
    };
  })();

  function sendText(text) {
    text = (text || '').trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return false;
    if (thinking || speaking) {
      // 打断当前播放，允许继续说
      stopHerVoice();
    }
    bubble(text, 'user');
    // adaptive 模式下：你开口这一刻强制看一眼，画面比"上一次定时抓的"新鲜
    try { if (cameraMode === 'adaptive' && camStream) captureFrame(true); } catch (e) {}
    ws.send(JSON.stringify({ text }));
    setStatus('她在想…', '#a78bfa');
    return true;
  }

  // 打断：她还在说话时你一开口，先把她的声音收掉，
  // 否则麦克风会把她的声音也录进去，变成自己跟自己说话。
  function stopHerVoice() {
    clearAudioQueue();
    if (currentAudio && !currentAudio.paused) {
      try { currentAudio.pause(); } catch (e) {}
    }
    speaking = false;
    thinking = false;
    window.__companionSpeaking = false;
    targetLevel = 0;
  }

  // 打断/录麦期间「她的话」先不出声：录完发现你没说成，再把这句补放出来
  let userBusy = false;
  let suppressedReply = null;

  function shouldSuppressReply(audio) {
    if (userBusy && audio) {
      suppressedReply = { audio };
      return true;
    }
    return false;
  }

  function resumeSuppressed() {
    const s = suppressedReply;
    suppressedReply = null;
    if (s && s.audio) enqueueAudio(s.audio);
  }

  // iOS 只允许"用户手势里解锁过"的音频播放，所以整页共用一个 audio 元素，
  // 第一次点屏幕时先解锁，之后她的每一句回复都能直接出声。
  //
  // 【2026-11-01 晚修】以前是"第一次 pointerdown 就无条件把 audio 接进 WebAudio"。
  // 但如果那一刻 AudioContext 还没 running（比如你是先打字、没点过屏幕），
  // 元素的声音就被接到一个挂起的上下文上 → 彻底没声；波形也全是 0，
  // 所以嘴也不张。现在改成：只在上下文真的 running 时才接，
  // 没解锁就先用普通播放（有声音，只是没口型），一有手势再补接。
  let sharedAudio = null;
  let sharedSrcNode = null;

  function ensureSharedAudio() {
    if (!sharedAudio) {
      sharedAudio = new Audio();
      sharedAudio.setAttribute('playsinline', '');
      sharedAudio.preload = 'auto';
    }
    return sharedAudio;
  }

  /**
   * 录音结束后把输出拉回“媒体播放”：
   * - iPhone Safari 录过音后可能把音频路由切到听筒/通话模式，听起来很小；
   * - Android/Win 的“通信降噪”也可能把系统音量压低；
   * - 顺手把元素音量复位，防止别的页面/测试把它改小。
   */
  function restorePlaybackRoute() {
    sessionForPlayback();
    try {
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
      }
    } catch (e) {}
    try {
      const a = ensureSharedAudio();
      a.muted = false;
      a.volume = 1.0;
    } catch (e) {}
  }

  // 2026-11-09：不再把 <audio> 接进 WebAudio。
  // createMediaElementSource 会把元素的声音整体改道，一旦链路有问题就是"有电平没声音"。
  // 现在：元素走系统原生播放（一定有声）；WebAudio 只负责"解码播放"和"电平分析"。
  function ensureAnalyser() {
    try {
      const actx = getAudioCtx();
      if (!actx) return null;
      if (!analyser) {
        analyser = actx.createAnalyser();
        analyser.fftSize = 512;
        analyser.connect(actx.destination);   // 一定要连到扬声器
      }
      return analyser;
    } catch (e) {
      return null;
    }
  }

  function wireAnalyser() { ensureAnalyser(); }

  // 任何一个手势（点、按键、触摸）都顺手解锁一次；不设 once，
  // 因为上下文可能在通话中途被浏览器挂起。
  // 另外：如果之前有句子因为没解锁没播出来，这里补播。
  let pendingAudio = null;
  let lastReplyAudio = "";
  function unlockAudio() {
    try { getAudioCtx(); } catch (e) {}
    try { ensureSharedAudio(); } catch (e) {}
    // 2026-11-09：光建 AudioContext 不够，元素本身也要在"手势里"播过一次，
    // 否则十几秒后才到的语音仍然会被自动播放策略拒（就是"一直显示被拦截"）。
    try {
      const a = ensureSharedAudio();
      if (!window.__companionAudioBlessed) {
        window.__companionAudioBlessed = true;
        const keep = a.src;
        a.muted = true;
        a.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=';
        const pr = a.play();
        if (pr && pr.then) {
          pr.then(() => {
            try { a.pause(); a.currentTime = 0; } catch (e) {}
            a.muted = false;
            if (keep) a.src = keep;
            if (pendingAudio) { const q = pendingAudio; pendingAudio = null; try { playAudio(q); } catch (e) {} }
          }).catch(() => { a.muted = false; });
        } else {
          a.muted = false;
        }
      }
    } catch (e) {}
    try { wireAnalyser(); } catch (e) {}
    if (pendingAudio) {
      const p = pendingAudio;
      pendingAudio = null;
      try { playAudio(p); } catch (e) {}
    }
  }
  ['pointerdown', 'keydown', 'touchstart'].forEach(ev => {
    document.addEventListener(ev, unlockAudio, { passive: true });
  });

  // 自测用：模拟"十几秒后才到的语音"，验证解锁是否有效
  window.__companionBeginReply = () => { beginReplyAudio(); return audioNextSeq; };
  window.__companionEnqueueTest = (b64, seq) => { try { enqueueAudio(b64, seq); return true; } catch (e) { return String(e); } };
  window.__companionPlayTest = (b64) => {
    try { playAudio(b64); return true; } catch (e) { return String(e); }
  };

  /** 诊断用：控制台敲 __companionAudio() 就能看音频到底卡在哪 */
  window.__companionAudio = () => {
    try {
      return {
        ctx: audioCtx ? audioCtx.state : '(还没建)',
        wired: !!sharedSrcNode,
        playing: !!(currentAudio && !currentAudio.paused),
        level: Number(window.__companionLevel || 0),
        volume: sharedAudio ? sharedAudio.volume : null,
        audioSession: (navigator.audioSession && navigator.audioSession.type) || '(none)',
        mic: !!micStream,
        path: window.__companionLastPath || '(未播过)',
      };
    } catch (e) {
      return { error: String(e) };
    }
  };

  // 2026-11-09 修"一直显示被拦截"的根：
  // <audio> 元素即使在手势里解锁过，夸克/Chromium 仍可能在晚到的播放上拒绝；
  // 而测试音（WebAudio 振荡器）是能响的 —— 所以干脆把她的声音也走 WebAudio：
  // base64 -> ArrayBuffer -> decodeAudioData -> AudioBufferSourceNode。
  // 这条路不受"媒体元素自动播放"限制，只要 AudioContext 是 running。
  let currentBufSrc = null;

  function b64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const len = bin.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i += 1) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }

  function playAudioBuffer(b64, done) {
    if (IS_PANEL) { if (typeof done === 'function') done(); return true; }   // 面板页静音
    let ctx = null;
    try { ctx = getAudioCtx(); } catch (e) { ctx = null; }
    if (!ctx) return false;
    if (ctx.state !== 'running') {
      try { ctx.resume().catch(() => {}); } catch (e) {}
      if (ctx.state !== 'running') return false;
    }
    const an = ensureAnalyser();
    try {
      const buf = b64ToArrayBuffer(b64);
      ctx.decodeAudioData(buf, (audioBuf) => {
        try {
          if (currentBufSrc) { try { currentBufSrc.stop(); } catch (e) {} }
          const src = ctx.createBufferSource();
          src.buffer = audioBuf;
          // 有 analyser 就接 analyser（它已经连到 destination），否则直连
          const node = an || analyser;
          if (node) src.connect(node); else src.connect(ctx.destination);
          currentBufSrc = src;
          window.__companionLastPath = 'buffer';
          currentAudio = null;
          speaking = true;
          window.__companionSpeaking = true;
          try {
            const b2 = new Uint8Array(analyser ? analyser.fftSize : 0);
            const readBuf = () => {
              if (!analyser) return;
              analyser.getByteTimeDomainData(b2);
              let sum = 0;
              for (let i = 0; i < b2.length; i += 1) { const v = (b2[i] - 128) / 128; sum += v * v; }
              targetLevel = Math.min(1, Math.sqrt(sum / b2.length) * 5);
              window.__companionLevel = targetLevel;
              if (speaking) requestAnimationFrame(readBuf);
            };
            readBuf();
          } catch (e) {}
          try {
            window.__companionPlayed = (window.__companionPlayed || 0) + 1;
            if (window.__paReport) window.__paReport('audio-play', 'buffer#' + window.__companionPlayed);
          } catch (e) {}
          src.onended = () => {
            speaking = false;
            window.__companionSpeaking = false;
            targetLevel = 0;
            setStatus('在线 · 可以说话了', '#67e8f9');
            done();
          };
          src.start();
        } catch (e) {
          elementFallback(b64, done);
        }
      }, () => elementFallback(b64, done));
      return true;
    } catch (e) {
      return false;
    }
  }

  function playAudio(b64, onDone) {
    if (IS_PANEL) { if (typeof onDone === 'function') onDone(); return; }   // 面板页静音
    let doneOnce = false;
    const done = () => {
      if (doneOnce) return;
      doneOnce = true;
      if (typeof onDone === 'function') onDone();
    };
    lastReplyAudio = b64;
    // 优先：WebAudio 直解 mp3（不受媒体元素自动播放限制）
    try {
      if (playAudioBuffer(b64, done)) return;
    } catch (e) {}
    elementFallback(b64, done);
  }

  function elementFallback(b64, onDone) {
    const done = typeof onDone === 'function' ? onDone : () => {};
    window.__companionLastPath = 'element';
    try {
      const audio = ensureSharedAudio();
      // 先恢复输出路由/音量，再放这一句；录音后声音变小主要在这里兜底。
      restorePlaybackRoute();
      if (currentAudio && currentAudio !== audio) {
        try { currentAudio.pause(); } catch {}
      }
      currentAudio = audio;
      audio.onended = () => {
        speaking = false;
        window.__companionSpeaking = false;
        targetLevel = 0;
        setStatus('在线 · 可以说话了', '#67e8f9');
        done();
      };
      audio.src = 'data:audio/mp3;base64,' + b64;

      // 上下文 running 才能接波形分析；没解锁就走普通播放，先保证听得见
      try { wireAnalyser(); } catch (e) {}
      try { if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume().catch(() => {}); } catch (e) {}

      let abortStreak = 0;
      const failed = (err) => {
        const errName = (err && err.name) || 'unknown';
        // 打断（点麦克风、换句、清队列）会报 AbortError，这不是"被拦"，别吓人
        if (errName === 'AbortError') {
          abortStreak += 1;
          if (abortStreak < 3) { done(); return; }
        }
        try {
          if (window.__paReport) {
            window.__paReport('audio-fail', errName + ' / ' + (err && err.message ? err.message : ''));
          }
        } catch (e) {}
        pendingAudio = b64;      // 记下来，下次有任何手势就补播
        if (errName === 'NotAllowedError' || errName === 'NotSupportedError') {
          bubble('（浏览器拦住了声音，点一下屏幕或按个键就好）', 'sys');
          try { document.getElementById('speaker')?.classList.add('need-tap'); } catch (e) {}
        } else if (errName !== 'AbortError') {
          bubble('（这段声音没放出来：' + errName + '，点一下屏幕再试）', 'sys');
        }
        done();
      };
      // 元素永远是"原生播放"：最稳，先保证听得见
      // 原生播放拿不到真实电平 → 用轻量假电平让嘴巴动起来（音频还在放）
      const fakeMouth = () => {
        let t0 = performance.now();
        const tick = () => {
          if (!audio || audio.paused || audio.ended) {
            window.__companionFakeMouth = 0;
            return;
          }
          const t = (performance.now() - t0) / 1000;
          targetLevel = Math.max(0, 0.25 + 0.35 * Math.abs(Math.sin(t * 9.5)));
          requestAnimationFrame(tick);
        };
        tick();
      };
      audio.play().then(() => {
        try { fakeMouth(); } catch (e) {}
        pendingAudio = null;
        speaking = true;
        window.__companionSpeaking = true;
        try {
          window.__companionPlayed = (window.__companionPlayed || 0) + 1;
          if (window.__paReport) window.__paReport('audio-play', 'element#' + window.__companionPlayed);
        } catch (e) {}
      }).catch(failed);
      return;
      /* 下面旧的波形分支不再执行 */
      // eslint-disable-next-line no-unreachable
      const buf = new Uint8Array(analyser.fftSize);
      const read = () => {
        if (!analyser) return;
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        targetLevel = Math.min(1, Math.sqrt(sum / buf.length) * 5);
        if (!audio.paused && !audio.ended) requestAnimationFrame(read);
      };
      audio.play().then(() => {
        pendingAudio = null;
        speaking = true;
        window.__companionSpeaking = true;
        read();
      }).catch(failed);
    } catch (e) {
      bubble('（音频播放失败：' + e.message + '）', 'sys');
      done();
    }
  }

  // 分句合成的音频会并发到达，顺序不保证。按 seq 排队，凑齐顺序再播，
  // 听起来才是一整段，而不是几段互相打断。
  let audioQueue = [];

  // 2026-11-09：每轮回复都要从头对齐，否则第二句/第二轮的 seq 对不上，
  // 表现就是"前半句没声，后半句才出声"。
  function beginReplyAudio() {
    try {
      audioPending.clear();
      audioQueue = [];
      audioNextSeq = 0;
      audioBusy = false;
    } catch (e) {}
  }

  let audioBusy = false;
  let audioNextSeq = 0;
  const audioPending = new Map();

  function enqueueAudio(b64, seq) {
    if (typeof seq === 'number') {
      if (seq < audioNextSeq) {
        // 迟到的旧块：以前直接丢弃 → 少一句；现在照播
        if (b64) audioQueue.push(b64);
        if (!audioBusy) drainAudio();
        return;
      }
      audioPending.set(seq, b64);
      while (audioPending.has(audioNextSeq)) {
        const chunk = audioPending.get(audioNextSeq);
        audioPending.delete(audioNextSeq);
        audioNextSeq += 1;
        if (chunk) audioQueue.push(chunk);
      }
      // 缺口等待上限：1.5 秒还没等到缺失的那块，就先把已有的按序播掉，
      // 宁可顺序略乱，也不让整段没声。
      if (audioPending.size) {
        clearTimeout(window.__companionGapTimer);
        window.__companionGapTimer = setTimeout(() => {
          try {
            const keys = Array.from(audioPending.keys()).sort((a, b) => a - b);
            for (const k of keys) {
              const chunk = audioPending.get(k);
              audioPending.delete(k);
              if (chunk) audioQueue.push(chunk);
            }
            if (keys.length) audioNextSeq = Math.max.apply(null, keys) + 1;
            if (!audioBusy) drainAudio();
          } catch (e) {}
        }, 1500);
      }
    } else if (b64) {
      audioQueue.push(b64);
    }
    if (!audioBusy) drainAudio();
  }
  function drainAudio() {
    // 2026-11-09：以前遇到空段（'' 用来推进序号）就 audioBusy=false 直接 return，
    // 后面已经排队的句子就永远不播了 —— 表现正是"第一句有声音，第二句没声音"。
    // 现在：空段直接跳过，继续找下一段真音频。
    let next = null;
    while (audioQueue.length) {
      const cand = audioQueue.shift();
      if (cand) { next = cand; break; }
    }
    if (!next) {
      audioBusy = false;
      return;
    }
    audioBusy = true;
    let finished = false;
    playAudio(next, () => {
      if (finished) return;      // 双回调保护：一次只推进一格
      finished = true;
      audioBusy = false;
      drainAudio();
    });
  }
  function clearAudioQueue() {
    audioQueue = [];
    audioPending.clear();
    audioNextSeq = 0;
    audioBusy = false;
  }

  // 兜底：如果 userBusy 卡在 true（权限弹窗被关、页面切后台、录音回调没回来），
  // 她的每一句回复都会被"静音处理"——表现就是"有字没声音"。
  // 这里 30 秒没动静就强制放开，并把压住的那句补放出来。
  let userBusyAt = 0;
  setInterval(() => {
    if (!userBusy) { userBusyAt = 0; return; }
    const busyDoing = micLabel.textContent === '点击结束' || micLabel.textContent === '处理中…';
    if (busyDoing) { userBusyAt = performance.now(); return; }
    if (!userBusyAt) { userBusyAt = performance.now(); return; }
    if (performance.now() - userBusyAt > 30000) {
      userBusy = false;
      userBusyAt = 0;
      try { resumeSuppressed(); } catch (e) {}
    }
  }, 5000);

  function sendCurrent() {
    // 连接断着的时候不要清空输入框——以前会直接把打好的字吞掉，看着像"点了没反应"
    const ok = sendText(input.value);
    if (ok) {
      input.value = '';
    } else {
      try { toast('还没连上，正在重连；这句先留着'); } catch (e) {}
      try { connectWS(); } catch (e) {}
    }
  }

  sendBtn.onclick = sendCurrent;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') sendCurrent();
  });
  const testMicBtn = document.getElementById('test-mic');
  testMicBtn.onclick = async () => {
    if (micStream) {
      stopMicMeter();
      testMicBtn.textContent = '测麦克风';
    } else {
      const ok = await ensureMicMeter();
      testMicBtn.textContent = ok ? '关闭测试' : '测麦克风';
    }
  };

  // 录音后交给电脑本地的 Windows 中文识别，网页不显示转写文字
  // 注意：手机用 http:// 局域网地址打开时不是"安全上下文"，浏览器会直接禁掉麦克风，
  // 这时改用系统录音机（<input capture>），录完上传给 /api/voice，效果一样。
  const secureCtx = window.isSecureContext
    || location.hostname === '127.0.0.1'
    || location.hostname === 'localhost';
  const canRecord = secureCtx && !!(navigator.mediaDevices && window.MediaRecorder);
  if (!canRecord && !secureCtx) {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'audio/*';
    picker.setAttribute('capture', 'microphone');
    picker.style.display = 'none';
    document.body.appendChild(picker);

    micLabel.textContent = '点我说话';
    hint.textContent = '手机上会弹出录音机：录完点“使用/完成”，她会听';
    testMicBtn.style.display = 'none';
    document.getElementById('meter-text').textContent = '手机录音';

    picker.onchange = async () => {
      const file = picker.files && picker.files[0];
      picker.value = '';
      userBusy = false;
      if (!file) {
        resumeSuppressed();      // 打开了录音机又退出来，把她那句补放回去
        return;
      }
      if (file.size < 1000) {
        hint.textContent = '录得太短了，再试一次';
        resumeSuppressed();
        return;
      }
      suppressedReply = null;
      getAudioCtx();
      bubble('语音消息', 'user');
      setStatus('她在听…', '#a78bfa');
      hint.textContent = '上传中…';
      try {
        const res = await fetch('/api/voice', {
          method: 'POST',
          headers: { 'Content-Type': file.type || 'application/octet-stream' },
          body: file,
        });
        const data = await res.json();
        if (!res.ok || data.error) {
          hint.textContent = '没听清：' + (data.error || res.status);
          setStatus('在线 · 可以说话了', '#67e8f9');
          return;
        }
        if (data.transcript) bubble('“' + data.transcript + '”', 'user');
        bubble(data.text || '', 'bot');
        showCaption(data.text || '');
        if (data.audio) enqueueAudio(data.audio);
        if (data.expression !== undefined && window.__companionShowExpression) {
          window.__companionShowExpression(data.expression, (data.expression_sec || 8) * 1000);
        } else {
          setTimeout(() => { try { window.__companionRefreshMood?.(); } catch (e) {} }, 300);
        }
        setStatus('在线 · 可以说话了', '#67e8f9');
        hint.textContent = '想说就再点一下';
      } catch (e) {
        hint.textContent = '发送失败：' + (e.message || e);
        setStatus('出错了', '#fb7185');
      }
    };

    // 手机录音机被取消（没选文件）时，很多浏览器不触发 onchange，
    // 那样 userBusy 会一直为 true，她刚才那句就永远补放不出来了。
    picker.oncancel = () => {
      userBusy = false;
      resumeSuppressed();
    };

    mic.onclick = () => {
      getAudioCtx();
      stopHerVoice();          // 手机录音机打开前先收声
      userBusy = true;
      picker.click();
    };
  } else if (!canRecord) {
    micLabel.textContent = '用文字';
    hint.textContent = '这个浏览器不支持录音，用下面的输入框也可以';
    mic.onclick = () => input.focus();
  } else {
    let recorder = null;
    let chunks = [];
    let recording = false;
    let starting = false;   // 防连点：getUserMedia 是异步的，双击会开出两个录音器

    function resetMicUI() {
      listening = false;
      mic.classList.remove('listening');
      micLabel.textContent = '点击说话';
      if (!speaking && !thinking) setStatus('在线 · 可以说话了', '#67e8f9');
    }

    function pickMime() {
      const types = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/ogg;codecs=opus',
      ];
      for (const t of types) {
        try { if (MediaRecorder.isTypeSupported(t)) return t; } catch {}
      }
      return '';
    }

    async function startRecording() {
      if (starting || recording) return;   // 连点只认第一次
      starting = true;
      stopHerVoice();          // 先把她的话收住，避免录进她自己的声音
      // adaptive：你开口之前先把她眼前这一帧发上去，等她回话时画面是新鲜的
      try { if (cameraMode === 'adaptive' && camStream) captureFrame(true); } catch (e) {}
      userBusy = true;
      const ok = await ensureMicMeter().catch(() => false);   // 万一它抛了，别把 starting 卡死
      if (!ok) {
        starting = false;
        userBusy = false;
        resumeSuppressed();
        hint.textContent = lastMicError === 'NotAllowedError'
          ? '麦克风被拒绝了：点地址栏左边的小锁 → 麦克风 → 允许，再点一次'
          : '麦克风打不开（可能被别的 App 占着），或者直接打字';
        return;
      }
      const mime = pickMime();
      try {
        recorder = mime
          ? new MediaRecorder(micStream, { mimeType: mime })
          : new MediaRecorder(micStream);
      } catch (e) {
        starting = false;
        userBusy = false;
        resumeSuppressed();
        hint.textContent = '录音启动失败：' + (e.message || e.name);
        stopMicMeter();
        return;
      }
      chunks = [];
      recorder.ondataavailable = e => {
        if (e.data && e.data.size) chunks.push(e.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        chunks = [];
        recording = false;
        userBusy = false;
        resetMicUI();
        stopMicMeter();
        testMicBtn.textContent = '测麦克风';
        if (!blob.size) {
          hint.textContent = '没录到声音，再试一次';
          resumeSuppressed();
          return;
        }
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          // 别让人以为发出去了：说清楚没发，并立刻催一次重连（原来只写了"刷新页面"）
          hint.textContent = '连接断了，正在重连——刚才那段没发出去，再说一次';
          setStatus('连接断开，正在重连…', '#fb7185');
          try { connectWS(); } catch (e) {}
          return;
        }
        suppressedReply = null;
        bubble('语音消息', 'user');
        setStatus('她在听…', '#a78bfa');
        ws.send(await blob.arrayBuffer());
      };
      recorder.start(200);
      starting = false;
      recording = true;
      mic.classList.add('listening');
      micLabel.textContent = '点击结束';
      setStatus('在听你说话…再点一下结束', '#f472b6');
    }

    mic.onclick = async () => {
      getAudioCtx();
      if (recording) {
        recording = false;
        micLabel.textContent = '处理中…';
        try { recorder.stop(); } catch { resetMicUI(); stopMicMeter(); }
        // 关键：先把麦克风轨道真正停掉，再在“这次点击”的手势里把
        // Safari 的音频会话从 play-and-record 切回 playback。
        // 只改 audioSession、仍占着麦克风的话，Safari 可能忽略这次切换。
        try { stopMicMeter(); } catch (e) {}
        try { restorePlaybackRoute(); } catch (e) {}
        return;
      }
      // 必须在这次点击的手势里、早于任何 await：Safari 只在手势里认会话切换
      sessionForCapture();
      await startRecording();
    };
  }

  function draw() {
    const now = performance.now();
    const t = (now - t0) / 1000;
    level += (targetLevel - level) * 0.12;
    window.__companionLevel = level;
    if (!speaking && !audioCtx) targetLevel = 0;
    if (!speaking && level < 0.01) targetLevel = 0;

    ctx.clearRect(0, 0, W, H);

    for (const s of stars) {
      const a = s.a * (0.55 + 0.45 * Math.sin(t * 1.6 + s.p));
      ctx.fillStyle = `rgba(150,205,255,${a})`;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }

    const cx = W / 2;
    const cy = H * 0.44;

    // 光环
    const glow = ctx.createRadialGradient(cx, cy, 20, cx, cy, Math.min(W, H) * 0.36);
    glow.addColorStop(0, `rgba(80,220,255,${0.10 + level * 0.12})`);
    glow.addColorStop(0.55, 'rgba(40,90,180,0.06)');
    glow.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, Math.min(W, H) * 0.36, 0, Math.PI * 2);
    ctx.fill();

    // 以前这里会在 Live2D 没就绪时画一张静态立绘兜底，现在那张图撤掉了；
    // 只剩一句提示，超过 8 秒还没起来就直说没加载出来，别让人对着空屏等
    if (!window.__live2dReady) {
      const waited = (performance.now() - t0) / 1000;
      ctx.fillStyle = waited > 8 ? 'rgba(251,113,133,.75)' : 'rgba(120,220,255,.5)';
      ctx.font = '14px "Microsoft YaHei"';
      ctx.textAlign = 'center';
      ctx.fillText(waited > 8 ? '形象没加载出来，刷新一下试试' : 'TA正在加载…', cx, cy);
    }

    requestAnimationFrame(draw);
  }

  addEventListener('resize', resize);
  resize();
  applyBackground(true);
  setInterval(() => applyBackground(), 30000);
  draw();
  connectWS();

  // 手机从后台回来（锁屏、切 App）时 WS 往往已经断了，立刻重连，不等退避
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      wsRetry = 0;
      connectWS();
    }
  });

  // 任意点击/按键都会解锁音频上下文（见上面 unlockAudio 的注册），
  // 这里不用再单独挂 once 监听。
  // 手机用 http 打开时，浏览器不给麦克风；iPhone 尤其如此，只有 https 才行
  if (location.protocol === 'http:' && !['127.0.0.1', 'localhost'].includes(location.hostname)) {
    const bar = document.createElement('div');
    bar.style.cssText =
      'position:fixed;left:0;right:0;top:0;z-index:99;padding:10px 14px;'
      + 'background:#7c2d12;color:#ffe4d6;font-size:14px;text-align:center;'
      + 'cursor:pointer;letter-spacing:.3px';
    // 第一次用必须先在手机装一次根证书，直接跳 https 会被“非私人连接”吓退；
    // location.search 带着口令（?t=），切过去不会被拦 403
    bar.innerHTML =
      '<b>手机开麦要用 HTTPS</b>：第一次先 '
      + '<span class="xy-cert" style="text-decoration:underline">装证书</span>，'
      + '再 <span style="text-decoration:underline">点这里切过去 →</span>';
    bar.querySelector('.xy-cert').onclick = e => {
      e.stopPropagation();
      location.href = '/static/cert-help.html' + location.search;
    };
    bar.onclick = () => {
      location.href = 'https://' + location.hostname + ':8004/' + location.search;
    };
    document.body.appendChild(bar);
  }

  // ---------------- 摄像头：让她看见我 ----------------
  const camBtn = document.getElementById('cam');
  const camLabel = document.getElementById('cam-label');
  const camWrap = document.getElementById('cam-wrap');
  const selfView = document.getElementById('selfview');
  const seenEl = document.getElementById('seen');
  let camStream = null;
  let camTimer = null;
  let camBusy = false;
  let camStarting = false;
  const camStateEl = document.getElementById('cam-state');

  // 镜头：user=前置（拍自己，镜像），environment=后置（拍眼前，不镜像）
  // 选了会记住，下次开摄像头还是这个镜头。
  const LENS_KEY = 'companion_cam_lens';
  const LENS_NAME = { user: '前置', environment: '后置' };
  const lensBox = document.getElementById('lens');
  let camFacing = 'user';
  try {
    if (localStorage.getItem(LENS_KEY) === 'environment') camFacing = 'environment';
  } catch (e) {}

  // 抓帧间隔跟着服务端配置走（/api/settings），别在前后端各写死一个数
  let visionIntervalMs = 4500;
  let cameraMode = 'fixed';          // fixed=定时看；adaptive=画面变了才看
  let globalCameraSource = 'pc';      // pc=电脑摄像头；pico=带TA出门
  let cameraIntervalMs = 15000;
  let camDiffThreshold = 0.045;
  try {
    fetch('/api/settings').then(r => r.json()).then(s => {
      const v = Number(s && s.vision_interval_ms);
      if (v >= 1500 && v <= 60000) visionIntervalMs = v;
      const t = Number(s && s.vision_max_tokens);
      if (t > 0) window.__companionVisionTokens = t;
      if (s && s.camera_mode === 'adaptive') cameraMode = 'adaptive';
      const ci = Number(s && s.camera_interval_ms);
      if (ci >= 3000 && ci <= 120000) cameraIntervalMs = ci;
      const th = Number(s && s.camera_diff_threshold);
      if (th >= 0 && th <= 1) camDiffThreshold = th;
    }).catch(() => {});
  } catch (e) {}
  function visionHint(prefix) {
    const secs = Math.max(2, Math.round(
      (cameraMode === 'adaptive' ? cameraIntervalMs : visionIntervalMs) / 1000));
    return prefix + (cameraMode === 'adaptive'
      ? '，有变化就' + secs + ' 秒内看一眼'
      : '，每 ' + secs + ' 秒看一眼');
  }

  // 变化门：缩到 64×36 做灰度差，比一次上传便宜几个数量级
  const diffCanvas = document.createElement('canvas');
  diffCanvas.width = 64;
  diffCanvas.height = 36;
  const diffCtx = diffCanvas.getContext('2d', { willReadFrequently: true });
  let lastDiffData = null;
  const camStats = { sent: 0, skipped: 0, forced: 0, lastDiff: 0 };
  window.__companionCamStats = camStats;

  function camDiff(srcCanvas) {
    try {
      diffCtx.drawImage(srcCanvas, 0, 0, 64, 36);
      const cur = diffCtx.getImageData(0, 0, 64, 36).data;
      if (!lastDiffData) { lastDiffData = cur; return 1; }
      let sum = 0, n = 0;
      for (let i = 0; i < cur.length; i += 16) {
        sum += Math.abs(cur[i] - lastDiffData[i]);
        n++;
      }
      lastDiffData = cur;
      const d = (sum / Math.max(n, 1)) / 255;
      camStats.lastDiff = Math.round(d * 1000) / 1000;
      return d;
    } catch (e) { return 1; }
  }

  function paintLens() {
    // 后置拍的是外面，不该做镜像；不给容器加类，画面会是反的
    if (camWrap) camWrap.classList.toggle('rear', camFacing === 'environment');
    // 给一个稳定的状态出口：CSS 和自动化测试都认这一个值
    try { document.body.dataset.lens = camFacing; } catch (e) {}
    if (!lensBox) return;
    lensBox.hidden = !camStream;          // 摄像头没开时这一排不出现，免得点了没反应
    lensBox.querySelectorAll('button').forEach(b => {
      const on = b.dataset.lens === camFacing;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }


  // 轻提示：底部浮一句，2.2 秒自己消失
  let toastTimer = null;
  function toast(msg) {
    let el = document.getElementById('toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
  }

  function setCamState(text, cls) {
    if (!camStateEl) return;
    camStateEl.textContent = text;
    camStateEl.className = 'cam-state' + (cls ? ' ' + cls : '');
  }


  // 她说了什么 -> 脸上先给个即时反应，随后回到真实情绪
  // 只有"真的情绪上来了"才闪，日常回话不换脸
  const FLASH_RULES = [
    [/哈哈|嘿嘿|嘻嘻|笑死|好笑|逗我/, 'exp05_brackets'],
    [/呜呜|想哭|难过|委屈|舍不得/, 'exp08_worry'],
    [/哼|讨厌|生气|不理你|坏你/, 'exp02_grit'],
    [/最喜欢|好喜欢|贴贴|抱抱|亲亲/, 'exp04_blush'],
    [/不嘛|就要|偏不|我不管|不管嘛/, 'exp08_chestnut'],
    [/略略略|笨蛋|傻你|坏蛋/, 'exp02_three_mouth'],
    [/好耶|太棒了|最喜欢你/, 'exp05_brackets'],
  ];

  function reactExpression(text) {
    let hit = '';
    for (const [re, name] of FLASH_RULES) {
      if (re.test(text)) { hit = name; break; }
    }
    if (hit && window.__companionFlashExpression) {
      window.__companionFlashExpression(hit, 1400);
      setTimeout(() => { try { window.__companionRefreshMood?.(); } catch (e) {} }, 2100);
    } else {
      setTimeout(() => { try { window.__companionRefreshMood?.(); } catch (e) {} }, 300);
    }
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, s => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
  }

  function stopCam(force) {
    const wasOn = !!camStream;
    try {
      if (window.__paReport) {
        window.__paReport('cam-stop', 'force=' + !!force + ' wasOn=' + wasOn);
      }
    } catch (e) {}
    if (camTimer) { clearInterval(camTimer); camTimer = null; }
    if (camStream) {
      try { camStream.getTracks().forEach(t => t.stop()); } catch (e) {}
      camStream = null;
    }
    if (selfView) selfView.srcObject = null;
    // 视线立刻交还鼠标（你的要求：关摄像头必须马上回到跟鼠标）
    try { window.__companionFaceGaze?.stop(); } catch (e) {}
    try { window.setGazeMode?.('mouse'); } catch (e) {}
    try { window.resetGaze?.(); } catch (e) {}
    if (camWrap) camWrap.classList.remove('show');
    if (camBtn) camBtn.classList.remove('on');
    if (camLabel) camLabel.textContent = '让她看见我';
    if (seenEl) seenEl.textContent = '';
    camStarting = false;
    paintLens();          // 摄像头关了，前置/后置这一排跟着收起来
    // force=true：切镜头彻底失败时 camStream 已经被清空，这里也必须把状态写干净，
    // 否则状态栏会一直卡在"正在切到…"上。
    if (!wasOn && !force) return;   // 本来就没开，不要弹提示
    stopPresenceLoop();
    setCamState('摄像头已关闭', '');
    try { toast('摄像头已关闭，她看不见你了'); } catch (e) {}
  }

  // 在场心跳（2026-11-09）：每 3 秒发一张 320 宽的小图，
// 服务端只做"有没有脸"的判断，用来知道你进/出。
  // 全局视觉入口：带TA出门时，网页端主动关掉电脑摄像头
  async function syncCameraSource() {
    try {
      const r = await fetch('/api/camera_source', { cache: 'no-store' });
      const j = await r.json();
      const next = j.source === 'pico' ? 'pico' : 'pc';
      if (next === globalCameraSource) return;
      globalCameraSource = next;
      if (next === 'pico') {
        if (camStream) stopCam(true);
        if (camBtn) camBtn.disabled = true;
        setCamState('已带TA出门 · 电脑摄像头关闭', '');
        if (hint) hint.textContent = '现在她的眼睛是 PICO 眼镜，电脑摄像头不参与';
      } else {
        if (camBtn) camBtn.disabled = false;
        setCamState('在家 · 电脑摄像头可用', '');
        if (hint) hint.textContent = '电脑摄像头可用，点“让她看见我”开始';
      }
    } catch (e) {}
  }

let presenceTimer = null;
let presenceBusy = false;
let presenceMiss = 0;

async function presencePing() {
  if (IS_PANEL) return;   // 面板页不上报在场
  if (presenceBusy || !camStream || !selfView || !selfView.videoWidth) return;
  presenceBusy = true;
  try {
    const w = Math.min(320, selfView.videoWidth);
    const h = Math.round(selfView.videoHeight * (w / selfView.videoWidth));
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    cv.getContext('2d').drawImage(selfView, 0, 0, w, h);
    const blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', 0.6));
    if (!blob) return;
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), 8000);
    try {
      const res = await fetch('/api/presence', { method: 'POST', body: blob, signal: ac.signal });
      const j = await res.json();
      if (j && j.ok) presenceMiss = j.faces > 0 ? 0 : presenceMiss + 1;
    } finally {
      clearTimeout(timer);
    }
  } catch (e) {
    /* 失败就安静，别打断通话 */
  } finally {
    presenceBusy = false;
  }
}

function startPresenceLoop() {
  if (presenceTimer) return;
  presenceTimer = setInterval(presencePing, 3000);
}

function stopPresenceLoop() {
  if (presenceTimer) { clearInterval(presenceTimer); presenceTimer = null; }
}

// force=true：开口说话时强制看一眼，不经过"变化门"
  async function captureFrame(force) {
    if (!camStream || (!force && camBusy) || !selfView || !selfView.videoWidth) return;
    camBusy = true;
    try {
      const w = Math.min(640, selfView.videoWidth);
      const h = Math.round(selfView.videoHeight * (w / selfView.videoWidth));
      const cv = document.createElement('canvas');
      cv.width = w;
      cv.height = h;
      cv.getContext('2d').drawImage(selfView, 0, 0, w, h);

      // adaptive：画面没变就不上传。你坐着不动时，一帧都不发。
      if (cameraMode === 'adaptive' && !force) {
        const d = camDiff(cv);
        if (d < camDiffThreshold) {
          camStats.skipped += 1;
          return;
        }
      } else if (force) {
        camStats.forced += 1;
      }
      startPresenceLoop();   // 摄像头起来了，开始判断在不在
    camStats.sent += 1;

      const blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', 0.82));
      if (!blob) return;
      // 加超时：以前 fetch 卡住时 camBusy 会永远是 true，摄像头就再也不发帧了
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), 12000);
      let res;
      try {
        res = await fetch('/api/look', { method: 'POST', body: blob, signal: ac.signal });
      } finally {
        clearTimeout(timer);
      }
      const data = await res.json();
      if (data.caption) {
        seenEl.innerHTML = '她看到：<b>' + escapeHtml(data.caption) + '</b>';
      } else if (data.error) {
        seenEl.textContent = '（没看清：' + data.error + '）';
      }
    } catch (e) {
      /* 看不了就安静，不打断通话 */
    } finally {
      camBusy = false;
    }
  }

  // 后置拍外面，给高一点的解析度；前置是自拍，640 就够，省流量也省显存
  // 返回 {stream, fellBack}：fellBack=true 表示这台设备没有这个镜头，
  // 是第三层兜底给的默认摄像头 —— 界面不能假装切成功了。
  async function openStream(facing) {
    const back = facing === 'environment';
    const wanted = {
      audio: false,
      video: {
        facingMode: { ideal: facing },
        width: { ideal: back ? 1280 : 640 },
        height: { ideal: back ? 720 : 480 },
        frameRate: { ideal: 24, max: 30 },
      },
    };
    try {
      return { stream: await navigator.mediaDevices.getUserMedia(wanted), fellBack: false };
    } catch (err) {
      // 有的机型不认 ideal 朝向：先只给 facingMode 再试一次
      try {
        return {
          stream: await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { facingMode: facing },
          }),
          fellBack: false,
        };
      } catch (e2) {
        // 最后一层：随便给个摄像头，但必须告诉调用方这是兜底
        return {
          stream: await navigator.mediaDevices.getUserMedia({ audio: false, video: true }),
          fellBack: true,
        };
      }
    }
  }

  // 视线数值抽样：每 3 秒报一条，最多 10 条（排查"眼睛不跟着我"）
  function watchGazeForDiag() {
    if (window.__gazeDiagOn || !window.__paReport) return;
    window.__gazeDiagOn = true;
    let n = 0;
    const tick = setInterval(() => {
      n += 1;
      const g = window.__lastFaceGaze;
      window.__paReport('gaze-sample',
        JSON.stringify({ g: g || null, mode: (window.getGazeMode && window.getGazeMode()) || '?',
                         dbg: window.__gazeDbg || null,
                         err: window.__companionFaceGazeError || null, n: n }));
      if (n >= 10) { clearInterval(tick); window.__gazeDiagOn = false; }
    }, 3000);
  }

  // 视线：只有前置才有脸可跟。后置拍的是外面，直接回到鼠标模式。
  async function startGaze() {
    if (camFacing !== 'user' || !camStream) {
      try { window.setGazeMode?.('mouse'); } catch (e) {}
      return;
    }
    try { window.setGazeMode?.('face'); } catch (e) {}
    // 先回原位：不让她从"鼠标最后的位置"开始转
    try { window.resetGaze?.(); } catch (e) {}
    try {
      const ok = await window.__companionFaceGaze?.start(selfView, (st) => {
        if (window.__paReport) window.__paReport('gaze-state', st);
        if (!camStream) return;
        if (st === 'loading') setCamState('摄像头已打开 · 正在准备看她…（首次约 3MB）', 'busy');
        else if (st === 'ready') setCamState('摄像头已打开 · 在找你的脸…', 'busy');
        else if (st === 'locked') setCamState('摄像头已打开 · 她在看着你', 'on');
        else if (st === 'searching') setCamState('摄像头已打开 · 她在找你…', 'busy');
        else if (st === 'failed') {
          setCamState('摄像头已打开 · 这次只跟鼠标', '');
          if (window.__paReport) {
            window.__paReport('gaze-failed', window.__companionFaceGazeError || 'unknown');
          }
        }
      });
      if (!camStream) return;              // 加载期间用户把摄像头关了
      watchGazeForDiag();
      if (ok === false) {
        try { window.setGazeMode?.('mouse'); } catch (e) {}
        setCamState('摄像头已打开 · 这次只跟鼠标', '');
      }
    } catch (e) {
      if (!camStream) return;
      try { window.setGazeMode?.('mouse'); } catch (err) {}
      setCamState('摄像头已打开 · 这次只跟鼠标', '');
    }
  }

  async function switchLens(next) {
    const target = next === 'environment' ? 'environment' : 'user';
    if (!camStream || camStarting || target === camFacing) return;
    const prev = camFacing;
    camFacing = target;
    try { localStorage.setItem(LENS_KEY, camFacing); } catch (e) {}
    paintLens();
    setCamState('正在切到' + LENS_NAME[camFacing] + '镜头…', 'busy');
    // 先把视线交还鼠标：切镜头时旧画面立刻作废
    try { window.__companionFaceGaze?.stop(); } catch (e) {}
    try { window.setGazeMode?.('mouse'); } catch (e) {}
    const old = camStream;
    camStream = null;
    camStarting = true;
    if (old) { try { old.getTracks().forEach(t => t.stop()); } catch (e) {} }
    // iOS 上前后摄切换：前一路流没完全释放就申请下一路，偶尔会拿到黑帧或
    // NotReadableError。等一小会儿再申请，代价只有 150ms。
    await new Promise(r => setTimeout(r, 150));
    try {
      const got = await openStream(camFacing);
      if (got.fellBack) {
        // 设备没有后置镜头：把这路流交给调用方之前先扔掉，别让界面撒谎
        try { got.stream.getTracks().forEach(t => t.stop()); } catch (e) {}
        const err = new Error('这台设备没有后置镜头');
        err.name = 'NoRearCamera';
        throw err;
      }
      const stream = got.stream;
      camStream = stream;
      camStarting = false;
      stream.getVideoTracks().forEach(track => {
        track.onended = () => { stopCam(); try { toast('摄像头被系统关掉了'); } catch (e) {} };
      });
      selfView.srcObject = stream;
      try { await selfView.play(); } catch (e) {}
      try { restorePlaybackRoute(); } catch (e) {}
      camWrap.classList.add('show');
      camBtn.classList.add('on');
      camLabel.textContent = '关掉摄像头';
      setCamState('摄像头已打开 · ' + LENS_NAME[camFacing] + '镜头', 'on');
      hint.textContent = camFacing === 'environment'
        ? visionHint('后置镜头对着你眼前')
        : visionHint('前置镜头对着你');
      await startGaze();
      paintLens();
      try { toast('已切到' + LENS_NAME[camFacing] + '镜头'); } catch (e) {}
    } catch (e) {
      // 切不过去就退回原来那个镜头，别把摄像头留成黑屏
      camStarting = false;
      camFacing = prev;
      try { localStorage.setItem(LENS_KEY, camFacing); } catch (err) {}
      const noRear = e && e.name === 'NoRearCamera';
      try {
        const back = (await openStream(camFacing)).stream;
        camStream = back;
        selfView.srcObject = back;
        try { await selfView.play(); } catch (err) {}
        setCamState(noRear
          ? '这台设备没有后置镜头，还是' + LENS_NAME[camFacing]
          : '切镜头失败，已回到' + LENS_NAME[camFacing], 'on');
        await startGaze();
      } catch (e2) {
        camStream = null;
        stopCam(true);      // 强制收尾，别让状态栏卡在"正在切到…"
      }
      hint.textContent = noRear
        ? '没找到后置镜头，先留在' + LENS_NAME[camFacing]
        : '这个镜头打不开（' + (e.name || '未知') + '），先留在' + LENS_NAME[camFacing];
      paintLens();
    }
  }

  async function startCam() {
    if (globalCameraSource === 'pico') {
      try { setCamState("已带TA出门 · 电脑摄像头已关闭", ""); } catch (e) {}
      try { hint.textContent = "现在她的眼睛是 PICO 眼镜，电脑摄像头不参与"; } catch (e) {}
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      hint.textContent = '手机要开摄像头得用 https 地址（8004 那个）';
      return;
    }
    if (camStarting) return;
    camStarting = true;
    setCamState('正在打开' + LENS_NAME[camFacing] + '摄像头…', 'busy');
    try {
      const got = await openStream(camFacing);
      camStream = got.stream;
      if (got.fellBack && camFacing === 'environment') {
        // 记着"后置"但设备没有后置：安静回到前置，界面不能说成后置
        camFacing = 'user';
        try { localStorage.setItem(LENS_KEY, camFacing); } catch (err) {}
      }
    } catch (e) {
      camStarting = false;
      setCamState('打不开（' + (e.name || '权限被拒') + '）', '');
      hint.textContent = '摄像头打不开：' + (e.name || e.message);
      try { toast('摄像头打不开：' + (e.name || '权限被拒')); } catch (err) {}
      return;
    }
    camStarting = false;
    // 设备被拔掉 / 权限被系统收回时，自动收尾并提示
    try {
      camStream.getVideoTracks().forEach(track => {
        track.onended = () => { stopCam(); try { toast('摄像头被系统关掉了'); } catch (e) {} };
      });
    } catch (e) {}
    selfView.srcObject = camStream;
    try { await selfView.play(); } catch (e) {}
    // 摄像头也是 getUserMedia；某些 iOS 版本会顺手把音频会话切到
    // play-and-record。这里在用户手势里再拉回 playback，避免“开摄像头后变小声”。
    try { restorePlaybackRoute(); } catch (e) {}
    camWrap.classList.add('show');
    camBtn.classList.add('on');
    camLabel.textContent = '关掉摄像头';
    paintLens();
    setCamState('摄像头已打开 · ' + LENS_NAME[camFacing] + '镜头', 'on');
    hint.textContent = camFacing === 'environment'
      ? visionHint('后置镜头对着你眼前')
      : visionHint('她可以看见你了');
    try {
      toast(camFacing === 'environment'
        ? '后置镜头已打开，她能看见你眼前的'
        : '摄像头已打开，她能看见你了');
    } catch (e) {}
    // fixed：每 N 秒看一次；adaptive：间隔放长，主要靠"变化了"和"开口时"触发
    camTimer = setInterval(captureFrame,
      cameraMode === 'adaptive' ? cameraIntervalMs : visionIntervalMs);
    setTimeout(() => captureFrame(true), 2000);   // 刚开就先看一眼

    // 视线切到人脸（只有前置）。认脸模型第一次要下 3MB 左右，装不上就安静地留在鼠标模式。
    await startGaze();
  }

  if (lensBox) {
    lensBox.querySelectorAll('button').forEach(b => {
      b.onclick = ev => {
        ev.preventDefault();
        ev.stopPropagation();
        try { getAudioCtx(); } catch (e) {}
        switchLens(b.dataset.lens);
      };
    });
  }

  if (camBtn) {
    camBtn.onclick = () => {
      try { getAudioCtx(); } catch (e) {}
      if (camStream) stopCam();
      else startCam();
    };
    window.addEventListener('beforeunload', () => stopCam());
    // 2026-11-09 夜里定案：页面"不可见"就关摄像头这条路彻底去掉。
    // 原因：浏览器（夸克/Chromium）在窗口被别的窗口遮住时也会报 hidden，
    //       于是"你没动它，摄像头自己关了、视线也退回鼠标"——这正是部署者遇到的现象。
    // 现在：摄像头只由你点「关掉摄像头」或关页面来停，别的什么都不关它。
    document.addEventListener('visibilitychange', () => {
      try {
        if (window.__paReport) window.__paReport('vis', document.hidden ? 'hidden' : 'visible');
      } catch (e) {}
    });
  }

  // 手机 Safari 的兜底：声音小/听不到时点一下，强制切 playback 并重播最近一句。
  const speakerBtn = document.getElementById('speaker');
  if (speakerBtn) {
    speakerBtn.onclick = () => {
      try { getAudioCtx(); } catch (e) {}
      restorePlaybackRoute();
      if (lastReplyAudio) {
        playAudio(lastReplyAudio);
        hint.textContent = '已切到外放，重播最近一句';
      } else {
        hint.textContent = '外放已就绪，下次回复会从扬声器播';
      }
    };
  }
  syncCameraSource();
  setInterval(syncCameraSource, 4000);
})();






/* 日程 → 表情的映射不属于视频通话页。
   2026-11-01 晚你的原话：「不是改视频通话啊，视频通话改回去，我们一直在聊的是陪玩！」
   这段原本接在视频页，会每 20 秒按 activity 覆盖真实情绪表情 60 秒；
   已移除，视频页恢复「表情只跟情绪和命令走」。陪玩窗口走 widget2.html，不加载 app.js。 */

/* ---------------- 2026-11-16 授权界面：摄像头 / 麦克风 ---------------- */
(function initPermissionBar(){
  const bar = document.getElementById('perm-bar');
  if (!bar) return;
  const txt = document.getElementById('perm-txt');
  const dot = document.getElementById('perm-dot');
  const allowBtn = document.getElementById('perm-allow');
  const openBtn = document.getElementById('perm-open');
  const xBtn = document.getElementById('perm-x');
  const isElectronApp = /electron/i.test(navigator.userAgent || '');
  const md = navigator.mediaDevices;
  const canAsk = !!(md && md.getUserMedia);
  const CN = {granted:'已允许', denied:'被拒绝', prompt:'还没问过', unknown:'未知', unsupported:'不支持'};

  if (isElectronApp){
    // 在「TA」App（Electron）里：摄像头/麦克风由 App 自动放行，不再显示"未授权"误导
    setDot('#22c55e');
    txt.textContent = '已由「TA」App 授权：摄像头 / 麦克风直接可用 ✓';
    allowBtn.hidden = true;
    openBtn.hidden = true;
    bar.hidden = false;
    setTimeout(function(){ bar.hidden = true; }, 2200);
    return;
  }

  function setDot(color){ try { dot.style.background = color; dot.style.boxShadow = '0 0 0 4px ' + color + '33'; } catch(e){} }

  async function permState(name){
    try {
      if (!navigator.permissions || !navigator.permissions.query) return 'unknown';
      const p = await navigator.permissions.query({ name: name });
      return p.state || 'unknown';
    } catch (e) { return 'unknown'; }
  }

  function tellParent(msg){
    try { if (window.parent && window.parent !== window) window.parent.postMessage(msg, '*'); } catch (e) {}
  }

  async function refresh(){
    if (!canAsk){
      txt.textContent = '这个页面不能调用摄像头/麦克风：需要 https 或 localhost（当前地址不满足）';
      allowBtn.hidden = true; bar.hidden = false; setDot('#ef4444');
      tellParent({ type: 'companion-perm', ok: false, reason: 'insecure-context' });
      return;
    }
    const cam = await permState('camera');
    const mic = await permState('microphone');
    const granted = cam === 'granted' && mic === 'granted';
    const denied = cam === 'denied' || mic === 'denied';
    tellParent({ type: 'companion-perm', ok: granted, camera: cam, microphone: mic });
    if (granted){
      setDot('#22c55e');
      txt.textContent = '摄像头 / 麦克风：已授权 ✓';
      allowBtn.hidden = true;
      clearTimeout(refresh._t);
      refresh._t = setTimeout(function(){ bar.hidden = true; }, 1600);
      return;
    }
    allowBtn.hidden = false;
    setDot(denied ? '#ef4444' : '#f59e0b');
    if (denied){
      txt.textContent = '摄像头或麦克风被浏览器拒绝了（' + CN[cam] + ' / ' + CN[mic] + '）。'
        + '点「在浏览器里打开」重新允许一次，之后这个应用就能直接用。';
    } else {
      txt.textContent = '还没授权点我：摄像头 ' + CN[cam] + ' · 麦克风 ' + CN[mic];
    }
    bar.hidden = false;
  }

  allowBtn.addEventListener('click', async function(){
    try {
      allowBtn.disabled = true;
      txt.textContent = '正在弹授权窗口…请在提示里点「允许」';
      const stream = await md.getUserMedia({ video: true, audio: true });
      stream.getTracks().forEach(function(t){ t.stop(); });
      txt.textContent = '授权成功，正在检查…';
      await refresh();
    } catch (err){
      const name = (err && err.name) || String(err);
      setDot('#ef4444');
      txt.textContent = '授权失败：' + name
        + '（可能是浏览器静默拦截了嵌入页的授权请求，点右边「在浏览器里打开」再允许一次）';
    } finally {
      allowBtn.disabled = false;
    }
  });

  openBtn.addEventListener('click', function(){
    try { window.open(location.href, '_blank', 'noopener'); } catch (e) {}
  });
  xBtn.addEventListener('click', function(){ bar.hidden = true; });

  refresh();
  setInterval(refresh, 20000);
  try { navigator.permissions.addEventListener?.('change', refresh); } catch (e) {}
})();


// 陪玩/视频通话隔离：收到 blocked 时挡住页面并给出出口
function showBlocked(reason) {
  if (document.getElementById('blockedLayer')) return;
  const d = document.createElement('div');
  d.id = 'blockedLayer';
  d.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(5,10,20,.94);'
    + 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;'
    + 'color:#dbeafe;font:15px "Microsoft YaHei",system-ui,sans-serif;text-align:center;padding:24px';
  d.innerHTML = '<div style="font-size:19px;font-weight:600">' + reason + '</div>'
    + '<div style="opacity:.75">陪玩和视频通话是隔离的，同一时间只能开一个。</div>'
    + '<div style="display:flex;gap:14px;margin-top:6px">'
    + '<a href="/playalong' + location.search + '" style="color:#67e8f9;text-decoration:none">去陪玩页</a>'
    + '<a href="javascript:location.reload()" style="color:#67e8f9;text-decoration:none">重试</a>'
    + '</div>';
  document.body.appendChild(d);
}
