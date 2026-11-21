/* TA · 大平层 3D（Three.js）
 * 立体房间 / 家具；鼠标拖拽平移、滚轮缩放；挡住TA的物体自动变透明；
 * TA用视频通话那套 Live2D（cubism4）叠在 3D 画面上。
 *
 * 边界：这里只是"看"。
 *   - 视角切换、拖拽、第一人称都不会写她的记忆，也不会让她产生"被你看过"的记忆。
 *   - 她去哪（厕所/阳台/客厅）由 houseviz 后台按身体信号和心情自动决定，和观看无关。
 */
(() => {
  'use strict';

  const canvas = document.getElementById('c3d');
  const liveCanvas = document.getElementById('live2d');
  const $ = id => document.getElementById(id);

  let plan = null;
  let state = null;
  let skew = 0;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  // 平衡方案：DPR 封顶 1.35，保留真实阴影/SSAO，但不超过 2x 超采样。
  const QUALITY = {
    dprCap: 1.35,
    dpr: Math.min(1.35, window.devicePixelRatio || 1),
    // 默认关闭全屏 SSAO/Bloom：这两项最吃性能，保留真实阴影和灯光更划算。
    // 想开高画质时在页面加 ?post=1。
    ssao: false,
    bloom: false,
  };
  // 2026-11-05：触屏 / 小屏自动降一档（以前必须手动加 ?quality=low 才不卡）
  const IS_MOBILE = !!((window.matchMedia && window.matchMedia('(pointer: coarse)').matches)
    || window.innerWidth < 820);
  if (IS_MOBILE) {
    QUALITY.dprCap = 1.0;
    QUALITY.dpr = Math.min(1.0, window.devicePixelRatio || 1);
  }
  renderer.setPixelRatio(QUALITY.dpr);
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // 场景和太阳几乎静止，阴影贴图按需刷新，不再每帧重画三张阴影图。
  renderer.shadowMap.autoUpdate = false;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x04070b);
  scene.fog = new THREE.FogExp2(0x04070b, 0.008);

  // 环境反射：让金属、玻璃有东西可反射，不是纯色块
  function makeEnvMap() {
    const c = document.createElement('canvas');
    c.width = 512;
    c.height = 256;
    const g = c.getContext('2d');
    const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, '#03060b');
    grad.addColorStop(0.45, '#0a1420');
    grad.addColorStop(0.55, '#101a26');
    grad.addColorStop(1, '#020408');
    g.fillStyle = grad;
    g.fillRect(0, 0, 512, 256);
    const hg = g.createRadialGradient(256, 150, 10, 256, 150, 260);
    hg.addColorStop(0, 'rgba(120,220,255,.16)');
    hg.addColorStop(1, 'rgba(120,220,255,0)');
    g.fillStyle = hg;
    g.fillRect(0, 0, 512, 256);
    const tex = new THREE.CanvasTexture(c);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromEquirectangular(tex).texture;
    pmrem.dispose();
    tex.dispose();
    return env;
  }
  scene.environment = makeEnvMap();

  // 接触阴影 / 地面软阴影贴图
  function makeContactTex() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const rad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    rad.addColorStop(0, 'rgba(0,0,0,.8)');
    rad.addColorStop(0.6, 'rgba(0,0,0,.35)');
    rad.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = rad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }
  const CONTACT_TEX = makeContactTex();
  const CONTACT_MAT = new THREE.MeshBasicMaterial({
    map: CONTACT_TEX, transparent: true, opacity: 0.55, depthWrite: false,
  });
  function addContact(x, z, w, d, opacity) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), CONTACT_MAT);
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, 0.015, z);
    scene.add(m);
    return m;
  }

  function makeGlowTex() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const rad = g.createRadialGradient(64, 64, 2, 64, 64, 64);
    rad.addColorStop(0, 'rgba(255,255,255,.9)');
    rad.addColorStop(0.4, 'rgba(180,240,255,.35)');
    rad.addColorStop(1, 'rgba(180,240,255,0)');
    g.fillStyle = rad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }
  const GLOW_TEX = makeGlowTex();

  function makeSoftShadowTex() {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(0,0,0,0)';
    g.fillRect(0, 0, 256, 256);
    g.shadowColor = 'rgba(0,0,0,.9)';
    g.shadowBlur = 34;
    g.fillStyle = 'rgba(0,0,0,1)';
    g.beginPath();
    g.roundRect ? g.roundRect(48, 48, 160, 160, 28) : g.rect(48, 48, 160, 160);
    g.fill();
    const t = new THREE.CanvasTexture(c);
    return t;
  }
  const SOFT_SHADOW_TEX = makeSoftShadowTex();
  const SOFT_SHADOW_MAT = new THREE.MeshBasicMaterial({
    map: SOFT_SHADOW_TEX, transparent: true, opacity: 0.6, depthWrite: false,
  });
  function addSoftShadow(x, z, w, d) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), SOFT_SHADOW_MAT);
    m.rotation.x = -Math.PI / 2;
    m.position.set(x + 0.16, 0.012, z + 0.2);
    scene.add(m);
  }

  function makeCityTexture(night) {
    const c = document.createElement('canvas');
    c.width = 1024;
    c.height = 512;
    const g = c.getContext('2d');
    const sky = g.createLinearGradient(0, 0, 0, 512);
    if (night) {
      sky.addColorStop(0, '#030711');
      sky.addColorStop(0.55, '#0a1730');
      sky.addColorStop(1, '#1a2c48');
    } else {
      sky.addColorStop(0, '#2f5f88');
      sky.addColorStop(0.6, '#7fa8c4');
      sky.addColorStop(1, '#b8ccd8');
    }
    g.fillStyle = sky;
    g.fillRect(0, 0, 1024, 512);
    if (night) {
      for (let i = 0; i < 140; i++) {
        g.fillStyle = 'rgba(220,240,255,' + (0.3 + Math.random() * 0.7) + ')';
        g.fillRect(Math.random() * 1024, Math.random() * 260, 1.5, 1.5);
      }
      const mg = g.createRadialGradient(820, 90, 4, 820, 90, 60);
      mg.addColorStop(0, 'rgba(220,240,255,.9)');
      mg.addColorStop(1, 'rgba(220,240,255,0)');
      g.fillStyle = mg;
      g.beginPath();
      g.arc(820, 90, 60, 0, Math.PI * 2);
      g.fill();
    } else {
      const sg = g.createRadialGradient(760, 80, 10, 760, 80, 90);
      sg.addColorStop(0, 'rgba(255,250,220,.9)');
      sg.addColorStop(1, 'rgba(255,250,220,0)');
      g.fillStyle = sg;
      g.beginPath();
      g.arc(760, 80, 90, 0, Math.PI * 2);
      g.fill();
    }
    let x = -20;
    while (x < 1044) {
      const w = 30 + Math.random() * 70;
      const h = 90 + Math.random() * 300;
      const top = 512 - h;
      g.fillStyle = night ? '#060d18' : '#435660';
      g.fillRect(x, top, w, h);
      const cols = Math.floor(w / 12);
      const rows = Math.floor(h / 16);
      for (let cx = 0; cx < cols; cx++) {
        for (let cy = 0; cy < rows; cy++) {
          const lit = Math.random() > 0.45;
          g.fillStyle = night
            ? (lit ? 'rgba(255,214,140,.8)' : 'rgba(40,60,80,.4)')
            : 'rgba(40,70,90,.35)';
          g.fillRect(x + 6 + cx * 12, top + 8 + cy * 16, 5, 7);
        }
      }
      x += w + 6;
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
  }
  const CITY_NIGHT = makeCityTexture(true);
  const CITY_DAY = makeCityTexture(false);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 140);
  const view = {
    target: new THREE.Vector3(6.3, 0, 4.85),
    dist: 20,
    az: Math.PI / 4,
    el: Math.PI / 4,
  };

  let composer = null;
  let bloomPass = null;
  let ssaoPass = null;
  let fxaaPass = null;

  function resizePost() {
    if (!composer) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    const pr = renderer.getPixelRatio();
    composer.setSize(w, h);
    if (ssaoPass) ssaoPass.setSize(w, h);
    if (bloomPass) bloomPass.setSize(w, h);
    if (fxaaPass) fxaaPass.material.uniforms.resolution.value.set(1 / (w * pr), 1 / (h * pr));
  }

  function applyQuality() {
    renderer.setPixelRatio(QUALITY.dpr);
    if (ssaoPass) ssaoPass.enabled = QUALITY.ssao;
    if (bloomPass) bloomPass.enabled = QUALITY.bloom;
    resizePost();
  }

  function initPostprocessing() {
    if (qs.get('nopost') === '1') return;
    if (!THREE.EffectComposer || !THREE.RenderPass) return;
    composer = new THREE.EffectComposer(renderer);
    renderer.outputEncoding = THREE.LinearEncoding;
    renderer.toneMappingExposure = 1.7;
    composer.addPass(new THREE.RenderPass(scene, camera));
    if (THREE.SSAOPass && qs.get('ssao') !== '0') {
      ssaoPass = new THREE.SSAOPass(scene, camera, window.innerWidth, window.innerHeight);
      ssaoPass.kernelRadius = 8;
      ssaoPass.minDistance = 0.002;
      ssaoPass.maxDistance = 0.12;
      ssaoPass.output = THREE.SSAOPass.OUTPUT.Default;
      composer.addPass(ssaoPass);
    }
    if (THREE.UnrealBloomPass) {
      bloomPass = new THREE.UnrealBloomPass(
        new THREE.Vector2(window.innerWidth, window.innerHeight), 0.30, 0.45, 0.85);
      composer.addPass(bloomPass);
    }
    if (THREE.FXAAShader && THREE.ShaderPass) {
      fxaaPass = new THREE.ShaderPass(THREE.FXAAShader);
      composer.addPass(fxaaPass);
    }
    resizePost();
    applyQuality();
  }

  const hemi = new THREE.HemisphereLight(0xffd8b0, 0x1a1410, 0.5);
  const amb = new THREE.AmbientLight(0x3a3028, 0.9);
  const sun = new THREE.DirectionalLight(0xdfefff, 0.9);
  sun.position.set(8, 13, 10);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);  sun.shadow.camera.left = -10;
  sun.shadow.camera.right = 10;
  sun.shadow.camera.top = 10;
  sun.shadow.camera.bottom = -10;
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 50;
  sun.shadow.bias = -0.0006;
  sun.target.position.set(6.3, 0, 4.45);
  scene.add(sun.target);

  const keySpot = new THREE.SpotLight(0xffc890, 1.4, 18, 0.62, 0.55, 1.2);
  keySpot.position.set(4.6, 7.2, 2.8);
  keySpot.target.position.set(6.2, 0, 4.8);
  keySpot.castShadow = true;
  keySpot.shadow.mapSize.set(1024, 1024);
  keySpot.shadow.camera.near = 1;
  keySpot.shadow.camera.far = 18;
  keySpot.shadow.bias = -0.0004;
  keySpot.shadow.normalBias = 0.02;
  keySpot.shadow.radius = 4;
  scene.add(keySpot, keySpot.target);

  const moonFill = new THREE.DirectionalLight(0x8fb0d0, 0.28);
  moonFill.position.set(-8, 12, -8);
  scene.add(moonFill);

  const roomSpot = new THREE.SpotLight(0xffd7a8, 1.1, 11, 0.85, 0.6, 1.2);
  roomSpot.position.set(8.8, 5.2, 1.4);
  roomSpot.target.position.set(10.4, 0, 2.9);
  roomSpot.castShadow = true;
  roomSpot.shadow.mapSize.set(512, 512);
  roomSpot.shadow.camera.near = 0.8;
  roomSpot.shadow.camera.far = 12;
  roomSpot.shadow.bias = -0.0004;
  roomSpot.shadow.normalBias = 0.02;
  roomSpot.shadow.radius = 3;
  scene.add(roomSpot, roomSpot.target);
  scene.add(hemi, amb, sun);

  const qs = new URLSearchParams(location.search);
  if (qs.get('quality') === 'low') {
    QUALITY.dpr = 1.0;
    QUALITY.ssao = false;
    QUALITY.bloom = false;
  }
  const AZ = Number(qs.get('az'));
  if (Number.isFinite(AZ) && qs.get('az')) view.az = AZ * Math.PI / 180;
  const DS = Number(qs.get('dist'));
  const HR = Number(qs.get('hour'));
  const HOUR_LOCK = Number.isFinite(HR) && qs.get('hour') ? HR : null;
  const SHADOW_TEST = qs.get('shadow') === '1';
  const EXPR_LOCK = qs.get('expr') || '';
  const EL = Number(qs.get('el'));
  const TX = Number(qs.get('tx'));
  const TZ = Number(qs.get('tz'));
  if (Number.isFinite(EL) && qs.get('el')) view.el = EL * Math.PI / 180;
  if (Number.isFinite(DS) && DS > 4 && DS < 40) view.dist = DS;
  if (Number.isFinite(TX) && qs.get('tx')) view.target.x = TX;
  if (Number.isFinite(TZ) && qs.get('tz')) view.target.z = TZ;

  const raycaster = new THREE.Raycaster();
  const faders = [];          // { obj, mats, target }
  const occluderMeshes = [];  // meshes for raycast
  const lamps = [];
  const roomLights = [];
  const windowMats = [];
  const cityMats = [];
  const viewMats = [];
  const windowSpots = [];
  const roomLabels = [];
  let lastWindowDay = null;

  const neon = 0xf0b878;

  // 像素级遮挡：在"相机→TA"的视线上挖一个圆柱窗口，只挖掉挡住她的像素
  const holeU = {
    uHerPos: { value: new THREE.Vector3(6.3, 0.95, 4.4) },
    uCamPos: { value: new THREE.Vector3() },
    uRadius: { value: 0.5 },
  };

  function applyHole(m) {
    if (!m || m.userData.hole) return;
    m.userData.hole = true;
    m.onBeforeCompile = (shader) => {
      shader.uniforms.uHerPos = holeU.uHerPos;
      shader.uniforms.uCamPos = holeU.uCamPos;
      shader.uniforms.uRadius = holeU.uRadius;
      shader.vertexShader = 'varying vec3 vWPos;\n' + shader.vertexShader.replace(
        '#include <begin_vertex>',
        '#include <begin_vertex>\n  vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;'
      );
      shader.fragmentShader = 'varying vec3 vWPos;\nuniform vec3 uHerPos;\nuniform vec3 uCamPos;\nuniform float uRadius;\n' + shader.fragmentShader.replace('#include <clipping_planes_fragment>', '#include <clipping_planes_fragment>\n  vec3 seg = uHerPos - uCamPos;\n  float tt = clamp(dot(vWPos - uCamPos, seg) / max(dot(seg, seg), 0.0001), 0.0, 1.0);\n  float dd = length(vWPos - (uCamPos + seg * tt));\n  float camD = length(vWPos - uCamPos);\n  float herD = length(uHerPos - uCamPos);\n  if (dd < uRadius && camD < herD - 1.6) discard;'
      );
    };
    m.needsUpdate = true;
  }

  // ------------------------------------------------------------ 工具
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const dist2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  // ------------------------------------------------------------ 第一人称（TA视角）
  // 站在她所在的位置、用她的眼睛高度看这个家；拖动看四周，房间按钮可切换。
  const FP_VIEW = {
    her_room: { pos: [9.9, 3.6], look: [11.5, 0.9] },
    living: { pos: [4.3, 4.1], look: [6.2, 2.3] },
    kitchen: { pos: [0.95, 7.05], look: [2.2, 4.85] },
    toilet: { pos: [8.65, 5.15], look: [11.9, 7.3] },
    gallery: { pos: [13.55, 7.75], look: [14.65, 2.0] },
    balcony: { pos: [6.2, 8.3], look: [6.2, 6.8] },
    dad_room: { pos: [2.95, 3.7], look: [0.6, 0.6] },
  };
  const GALLERY_VIEWS = {
    "gallery-entry": { label: "入口", pos: [13.55, 7.65], look: [14.65, 6.8] },
    "gallery-west": { label: "西墙", pos: [13.55, 5.0], look: [12.45, 4.8] },
    "gallery-east": { label: "东墙", pos: [13.55, 3.0], look: [14.72, 3.4] },
    "gallery-north": { label: "北墙", pos: [13.55, 2.2], look: [13.4, 0.9] },
  };
  const fp = {
    on: false,
    pos: new THREE.Vector3(6.3, 1.52, 4.4),
    yaw: 0,
    pitch: 0,
    eye: 1.52,
    room: '',
    her: false,
    oldFov: 42,
    savedTarget: null,
    savedDist: 20,
    savedAz: Math.PI / 4,
    savedEl: Math.PI / 4,
  };

  function now() { return Date.now() / 1000 + skew; }

  function hourOf(t) {
    const d = new Date(t * 1000);
    return d.getHours() + d.getMinutes() / 60;
  }

  function routePos(route, t0, speed, t) {
    if (!route || !route.length) return [6.3, 4.4];
    if (route.length === 1) return route[0].slice();
    let remain = Math.max(0, (t - t0) * speed);
    let cur = route[0];
    for (let i = 1; i < route.length; i++) {
      const nxt = route[i];
      const seg = dist2(cur, nxt);
      if (seg <= remain) { remain -= seg; cur = nxt; continue; }
      if (seg < 1e-9) { cur = nxt; continue; }
      const k = remain / seg;
      return [cur[0] + (nxt[0] - cur[0]) * k, cur[1] + (nxt[1] - cur[1]) * k];
    }
    return cur.slice();
  }

  function herPos(t) {
    if (!state) return [6.3, 4.4];
    return routePos(state.her.route, state.her.route_at, state.her.speed, t);
  }

  function mat(color, o = {}) {
    return new THREE.MeshStandardMaterial({
      color,
      metalness: o.metal != null ? o.metal : 0.45,
      roughness: o.rough != null ? o.rough : 0.5,
      emissive: o.emissive != null ? o.emissive : 0x000000,
      emissiveIntensity: o.ei != null ? o.ei : 1,
      transparent: true,
      opacity: 1,
      envMapIntensity: 0.3,
      flatShading: false,
    });
  }

  function box(w, h, d, m, x, y, z) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function rbox(w, h, d, r, m, x, y, z) {
    const radius = Math.min(r, w * 0.45, d * 0.45, h * 0.45);
    const geo = (THREE.RoundedBoxGeometry && radius > 0.002)
      ? new THREE.RoundedBoxGeometry(w, h, d, 2, radius)
      : new THREE.BoxGeometry(w, h, d);
    const mesh = new THREE.Mesh(geo, m);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }
  function cyl(rt, rb, h, m, x, y, z, seg = 18) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function addEdges(mesh, color = neon, opacity = 0.22) {
    const line = new THREE.LineSegments(
      new THREE.EdgesGeometry(mesh.geometry),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
    line.position.copy(mesh.position);
    line.rotation.copy(mesh.rotation);
    line.scale.copy(mesh.scale);
    return line;
  }

  /** 注册可淡出对象（整组/单件），把所有材质收集起来 */
  function registerFade(obj) {
    const mats = [];
    obj.traverse(o => {
      if (o.isMesh && o.material) {
        if (Array.isArray(o.material)) mats.push(...o.material);
        else mats.push(o.material);
        o.userData.fader = obj;
      }
    });
    const rec = { obj, mats: [...new Set(mats)], target: 1 };
    for (const m of rec.mats) applyHole(m);
    faders.push(rec);
    obj.userData.fadeRec = rec;
    return rec;
  }

  // ------------------------------------------------------------ 地面
  function makeFloorTexture(base) {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = base;
    g.fillRect(0, 0, 256, 256);
    const lg = g.createLinearGradient(0, 0, 256, 256);
    lg.addColorStop(0, 'rgba(140,190,235,.06)');
    lg.addColorStop(1, 'rgba(0,0,0,.18)');
    g.fillStyle = lg;
    g.fillRect(0, 0, 256, 256);
    g.strokeStyle = 'rgba(120,160,200,.35)';
    g.lineWidth = 3;
    g.strokeRect(0, 0, 256, 256);
    g.strokeStyle = 'rgba(103,232,249,.10)';
    g.lineWidth = 1;
    g.strokeRect(10, 10, 236, 236);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    return t;
  }

  const FLOOR_TEX = makeFloorTexture('#101a26');

  function makeWoodTexture(base, dark) {
    const c = document.createElement('canvas');
    c.width = c.height = 512;
    const g = c.getContext('2d');
    g.fillStyle = base;
    g.fillRect(0, 0, 512, 512);
    for (let y = 0; y < 512; y += 64) {
      g.fillStyle = dark;
      g.fillRect(0, y, 512, 3);
      g.fillStyle = 'rgba(255,225,185,.035)';
      g.fillRect(0, y + 3, 512, 61);
    }
    for (let i = 0; i < 90; i++) {
      const yy = Math.random() * 512;
      g.strokeStyle = 'rgba(28,16,8,.12)';
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(0, yy);
      g.bezierCurveTo(170, yy + 8, 340, yy - 8, 512, yy + 3);
      g.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    return t;
  }
  const WOOD_TEX = makeWoodTexture('#2a1c12', '#180f09');
  const WOOD_DARK_TEX = makeWoodTexture('#241a11', '#140e08');

  function makeStoneTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 512;
    const g = c.getContext('2d');
    g.fillStyle = '#26272b';
    g.fillRect(0, 0, 512, 512);
    for (let y = 0; y < 512; y += 128) {
      for (let x = 0; x < 512; x += 128) {
        g.fillStyle = 'rgba(255,255,255,' + (Math.random() * 0.02) + ')';
        g.fillRect(x + 3, y + 3, 122, 122);
        g.strokeStyle = 'rgba(10,10,12,.6)';
        g.lineWidth = 2;
        g.strokeRect(x, y, 128, 128);
      }
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    return t;
  }
  const STONE_TEX = makeStoneTexture();

  function makeWallTexture(len) {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = '#18181b';
    g.fillRect(0, 0, 256, 256);
    for (let x = 0; x < 256; x += 64) {
      g.fillStyle = 'rgba(8,7,6,.6)';
      g.fillRect(x, 0, 4, 256);
      g.fillStyle = 'rgba(255,200,140,.05)';
      g.fillRect(x + 4, 0, 1, 256);
    }
    for (let i = 0; i < 50; i++) {
      g.strokeStyle = 'rgba(255,215,170,.025)';
      g.beginPath();
      g.moveTo(0, i * 5.2);
      g.lineTo(256, i * 5.2);
      g.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(Math.max(1, len / 1.3), 1);
    t.anisotropy = 8;
    return t;
  }

  function makeRugTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = '#16232f';
    g.fillRect(0, 0, 256, 256);
    g.strokeStyle = 'rgba(103,232,249,.45)';
    g.lineWidth = 4;
    g.strokeRect(6, 6, 244, 244);
    g.strokeStyle = 'rgba(103,232,249,.16)';
    g.lineWidth = 2;
    g.strokeRect(20, 20, 216, 216);
    g.strokeStyle = 'rgba(103,232,249,.10)';
    for (let i = 0; i < 4; i++) {
      g.beginPath();
      g.moveTo(34, 64 + i * 40);
      g.lineTo(222, 64 + i * 40);
      g.stroke();
    }
    return new THREE.CanvasTexture(c);
  }

  function makeArtTexture(seed) {
    const c = document.createElement('canvas');
    c.width = 320;
    c.height = 200;
    const g = c.getContext('2d');
    const r = Math.random;
    const bg = g.createLinearGradient(0, 0, 320, 200);
    bg.addColorStop(0, '#0a1826');
    bg.addColorStop(1, '#14324a');
    g.fillStyle = bg;
    g.fillRect(0, 0, 320, 200);
    const px = 90 + r() * 140, py = 85 + r() * 40, rad = 26 + r() * 28;
    const pg = g.createRadialGradient(px - rad * 0.3, py - rad * 0.3, rad * 0.1, px, py, rad);
    pg.addColorStop(0, 'rgba(160,240,255,.9)');
    pg.addColorStop(1, 'rgba(20,80,120,.2)');
    g.fillStyle = pg;
    g.beginPath(); g.arc(px, py, rad, 0, Math.PI * 2); g.fill();
    g.strokeStyle = 'rgba(120,230,255,.55)';
    g.lineWidth = 2;
    g.beginPath(); g.ellipse(px, py, rad * 1.7, rad * 0.45, -0.4, 0, Math.PI * 2); g.stroke();
    for (let i = 0; i < 40; i++) {
      g.fillStyle = 'rgba(200,240,255,' + (0.2 + r() * 0.6) + ')';
      g.fillRect(r() * 320, r() * 200, 1.4, 1.4);
    }
    return new THREE.CanvasTexture(c);
  }

  function addArt(x, y, z, w, h, rotY) {
    const g = new THREE.Group();
    const frame = box(w, h, 0.05, mat(0x0b131b, { metal: 0.6, rough: 0.35 }), 0, 0, 0);
    const art = box(w - 0.08, h - 0.08, 0.02,
      new THREE.MeshBasicMaterial({ map: makeArtTexture(x * 3 + z), color: 0xbfeaff }), 0, 0, 0.035);
    g.add(frame, art);
    const rim = box(w + 0.04, 0.012, 0.02,
      new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }), 0, h / 2, 0.03);
    g.add(rim);
    g.position.set(x, y, z);
    g.rotation.y = rotY;
    scene.add(g);
  }

  function addGalleryFrame(x, y, z, w, h, rotY, url) {
    const g = new THREE.Group();
    g.add(box(w + 0.08, h + 0.08, 0.06, mat(0x0a1118, { metal: 0.7, rough: 0.3 }), 0, 0, 0));
    g.add(box(w, h, 0.03, mat(0x1a2733, { metal: 0.4, rough: 0.5 }), 0, 0, 0.03));
    let material;
    if (url) {
      const tex = new THREE.TextureLoader().load(url, undefined, undefined, () => {});
      tex.colorSpace = THREE.SRGBColorSpace;
      material = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide });
    } else {
      material = new THREE.MeshStandardMaterial({
        color: 0x1d2a35, metalness: 0.1, roughness: 0.9, emissive: 0x0a151d, emissiveIntensity: 0.6,
      });
    }
    const art = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.10, h - 0.10), material);
    art.position.z = 0.05;
    g.add(art);
    g.add(box(w + 0.12, 0.012, 0.02,
      new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }), 0, h / 2, 0.04));
    g.position.set(x, y, z);
    g.rotation.y = rotY;
    scene.add(g);
  }

  async function buildGallery() {
    let items = [];
    try {
      items = await fetch('/art/index.json', { cache: 'no-store' }).then(r => r.json());
      if (!Array.isArray(items)) items = [];
    } catch (e) {}
    const latest = items.slice(-12).reverse(); // 最新的先挂
    const slots = [];
    // 北墙 3 幅
    for (let i = 0; i < 3; i++) slots.push([12.95 + i * 0.62, 1.42, 0.88, 0.46, 0.62, 0]);
    // 西墙 5 幅（避开 z=3 的门）
    for (let i = 0; i < 5; i++) slots.push([12.47, 1.42, 4.15 + i * 0.66, 0.46, 0.62, Math.PI / 2]);
    // 东墙 4 幅
    for (let i = 0; i < 4; i++) slots.push([14.73, 1.42, 1.35 + i * 0.66, 0.46, 0.62, -Math.PI / 2]);
    slots.forEach((s, i) => {
      const it = latest[i];
      let url = null;
      if (it) {
        const name = String(it.image || '').split(/[\\/]/).pop();
        if (name) url = '/art/file/' + encodeURIComponent(name);
      }
      addGalleryFrame(s[0], s[1], s[2], s[3], s[4], s[5], url);
    });
    // 长画廊的两盏顶灯
    for (const z of [3.1, 6.5]) {
      const lamp = new THREE.PointLight(0xffe0b0, 1.25, 5.0);
      lamp.position.set(13.45, 2.25, z);
      scene.add(lamp);
    }
  }
  const FLOOR_COLORS = {
    her_room: 0x9db8d0,
    dad_room: 0x8fa8c0,
    living: 0xa8c0d8,
    kitchen: 0x8090a0,
    toilet: 0x90a8b8,
    balcony: 0x708898,
  };

  function buildFloors() {
    const [sx, sy, sw, sh] = plan.slab;
    const groundTex = FLOOR_TEX.clone();
    groundTex.repeat.set(26, 26);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(70, 70),
      new THREE.MeshStandardMaterial({ map: (STONE_TEX.clone()), color: 0x1a1714, metalness: 0.2, roughness: 0.9 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(6.3, -0.2, 4.45);
    ground.receiveShadow = true;
    scene.add(ground);
    const base = box(sw, 0.16, sh, mat(0x0b131c, { metal: 0.5, rough: 0.6 }), sx + sw / 2, -0.11, sy + sh / 2);
    scene.add(base);
    for (const room of plan.rooms) {
      const [x, y, w, h] = room.rect;
      const isWood = ['her_room', 'dad_room', 'living'].indexOf(room.id) >= 0;
      const src = isWood ? WOOD_TEX : (room.id === 'balcony' ? WOOD_DARK_TEX : STONE_TEX);
      const tex = src.clone();
      tex.needsUpdate = true;
      const cell = isWood ? 1.2 : 0.64;
      tex.repeat.set(Math.max(1, w / cell), Math.max(1, h / cell));
      const m = new THREE.MeshStandardMaterial({
        map: tex,
        color: 0x9a7a5a,
        metalness: 0.12,
        roughness: 0.78,
        transparent: true,
        envMapIntensity: 0.25,
      });
      const floor = box(w, 0.08, h, m, x + w / 2, -0.02, y + h / 2);
      scene.add(floor);
      // 房间冷光边
      const edgeMat = new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 });
      const e1 = box(w, 0.015, 0.025, edgeMat, x + w / 2, 0.03, y + 0.02);
      const e2 = box(0.025, 0.015, h, edgeMat, x + 0.02, 0.03, y + h / 2);
      scene.add(e1, e2);
      if (room.id === 'balcony') {
        const deckTex = WOOD_DARK_TEX.clone();
        deckTex.wrapS = deckTex.wrapT = THREE.RepeatWrapping;
        deckTex.repeat.set(12, 1.2);
        deckTex.needsUpdate = true;
        const deckMat = new THREE.MeshStandardMaterial({
          map: deckTex, color: 0xb0a090, metalness: 0.1, roughness: 0.85,
        });
        scene.add(box(12.2, 0.1, 1.1, deckMat, 6.3, -0.04, 9.25));
        scene.add(box(12.3, 0.28, 1.15, mat(0x18140f, { metal: 0.2, rough: 0.8 }), 6.3, -0.24, 9.25));
        const railGlass = new THREE.MeshStandardMaterial({
          color: 0x9fb8c8, transparent: true, opacity: 0.16, metalness: 0.2, roughness: 0.1,
        });
        scene.add(box(12.2, 1.05, 0.03, railGlass, 6.3, 0.55, 9.78));
        scene.add(box(12.3, 0.05, 0.1, mat(0x2a2622, { metal: 0.6, rough: 0.4 }), 6.3, 1.1, 9.78));
        for (let px = 0.35; px <= 12.25; px += 2.0) {
          scene.add(box(0.06, 1.1, 0.06, mat(0x2a2622, { metal: 0.6, rough: 0.4 }), px, 0.55, 9.78));
        }
        for (const sideX of [0.28, 12.32]) {
          scene.add(box(0.03, 1.05, 1.05, railGlass, sideX, 0.55, 9.25));
          scene.add(box(0.1, 0.05, 1.1, mat(0x2a2622, { metal: 0.6, rough: 0.4 }), sideX, 1.1, 9.25));
        }
      }
      if (room.id !== 'balcony') {        const lamp = new THREE.PointLight(0xffd7a8, 0, 7, 1.7);
        lamp.position.set(x + w / 2, 2.32, y + h / 2);
        scene.add(lamp);
        roomLights.push(lamp);
      }
    }
  }

  // ------------------------------------------------------------ 墙
  const WALL_H = 2.55;
  const CURB_H = 0.32;

  function wallSeg(x1, z1, x2, z2, h, yBase = 0) {
    const len = Math.hypot(x2 - x1, z2 - z1);
    if (len < 0.02) return;
    const vertical = Math.abs(z2 - z1) > Math.abs(x2 - x1);
    const m = mat(0xffffff, { metal: 0.55, rough: 0.45 });
    m.map = makeWallTexture(len);
    const mesh = box(len, h, 0.1, m,
      (x1 + x2) / 2, yBase + h / 2, (z1 + z2) / 2);
    if (vertical) mesh.rotation.y = Math.PI / 2;
    scene.add(mesh);
    registerFade(mesh);
    occluderMeshes.push(mesh);
    // 踢脚线（只在地面层）
    if (yBase < 0.1 && h > 0.5) {
      const base = box(len, 0.1, 0.14, mat(0x070d14, { metal: 0.6, rough: 0.4 }),
        (x1 + x2) / 2, yBase + 0.05, (z1 + z2) / 2);
      if (vertical) base.rotation.y = Math.PI / 2;
      scene.add(base);
    }
    if (h > 0.8) {
      const mid = box(len, 0.012, 0.02, new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.28 }),
        (x1 + x2) / 2, yBase + h * 0.6, (z1 + z2) / 2);
      if (vertical) mid.rotation.y = Math.PI / 2;
      scene.add(mid);
    }
    // 墙顶冷光
    const top = box(len, 0.012, 0.12, new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }),
      (x1 + x2) / 2, yBase + h + 0.006, (z1 + z2) / 2);
    if (vertical) top.rotation.y = Math.PI / 2;
    scene.add(top);
  }

  function segmentsFor(start, end, gaps) {
    const sorted = gaps.slice().sort((a, b) => a[0] - b[0]);
    let cur = start;
    const out = [];
    for (const g of sorted) {
      const gs = Math.max(start, g[0]);
      const ge = Math.min(end, g[1]);
      if (ge <= cur) continue;
      if (gs > cur) out.push([cur, Math.min(gs, end)]);
      cur = Math.max(cur, ge);
    }
    if (cur < end) out.push([cur, end]);
    return out.filter(s => s[1] - s[0] > 0.02);
  }

  function gapsFor(room, axis) {
    const [x, y, w, h] = room.rect;
    const gaps = [];
    for (const win of plan.windows) {
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      if (axis === 'h' && Math.abs(ay - by) < 0.02 && Math.abs(ay - y) < 0.12) {
        gaps.push([Math.min(ax, bx) - 0.04, Math.max(ax, bx) + 0.04]);
      }
      if (axis === 'v' && Math.abs(ax - bx) < 0.02 && Math.abs(ax - x) < 0.12) {
        gaps.push([Math.min(ay, by) - 0.04, Math.max(ay, by) + 0.04]);
      }
    }
    for (const d of plan.doors) {
      if (axis === 'h' && d.dir === 'h' && Math.abs(d.y - y) < 0.35) {
        gaps.push([d.x - 0.04, d.x + d.w + 0.04]);
      }
      if (axis === 'v' && d.dir === 'v' && Math.abs(d.x - x) < 0.35) {
        gaps.push([d.y - 0.04, d.y + d.w + 0.04]);
      }
    }
    return gaps;
  }

  function buildWalls() {
    for (const room of plan.rooms) {
      const [x, y, w, h] = room.rect;
      const hGaps = gapsFor(room, 'h');
      if (room.id === 'balcony') {
        const doorGap = [[4.15, 7.05]];
        for (const [a, b] of segmentsFor(x, x + w, doorGap)) {
          wallSeg(a, y, b, y, WALL_H);
        }
        const fm = mat(0x141210, { metal: 0.7, rough: 0.35 });
        scene.add(box(0.14, WALL_H, 0.16, fm, 4.15, WALL_H / 2, y));
        scene.add(box(0.14, WALL_H, 0.16, fm, 7.05, WALL_H / 2, y));
        scene.add(box(3.05, 0.14, 0.16, fm, 5.6, WALL_H - 0.07, y));
        scene.add(box(1.25, 2.3, 0.04, new THREE.MeshStandardMaterial({
          color: 0x9fb8c8, transparent: true, opacity: 0.12, metalness: 0.2, roughness: 0.05,
        }), 4.95, 1.15, y - 0.03));
        scene.add(box(3.0, 0.04, 0.34, mat(0x2a2622, { metal: 0.4, rough: 0.5 }), 5.6, 0.02, y - 0.08));
      } else {
        for (const [a, b] of segmentsFor(x, x + w, hGaps)) {
          wallSeg(a, y, b, y, WALL_H);
        }
      }
      // 窗下墙 / 窗上墙
      for (const win of plan.windows) {
        const [ax, ay] = win.a;
        const [bx, by] = win.b;
        if (Math.abs(ay - by) < 0.02 && Math.abs(ay - y) < 0.12) {
          const a = Math.min(ax, bx);
          const b = Math.max(ax, bx);
          wallSeg(a, y, b, y, 0.9);
          wallSeg(a, y, b, y, WALL_H - 2.2, 2.2);
        }
      }
      const vGaps = gapsFor(room, 'v');
      for (const [a, b] of segmentsFor(y, y + h, vGaps)) {
        wallSeg(x, a, x, b, WALL_H);
      }
      // 南、东矮挡边（阳台南边接外延木平台）
      if (room.id === 'living') {
        for (const [a, b] of segmentsFor(x, x + w, [[4.35, 6.85]])) {
          wallSeg(a, y + h, b, y + h, CURB_H);
        }
      } else if (room.id !== 'balcony') {
        wallSeg(x, y + h, x + w, y + h, CURB_H);
      }
      const eastGaps = plan.doors
        .filter(d => d.dir === 'v' && Math.abs(d.x - (x + w)) < 0.35)
        .map(d => [d.y - 0.04, d.y + d.w + 0.04]);
      for (const [a, b] of segmentsFor(y, y + h, eastGaps)) {
        wallSeg(x + w, a, x + w, b, CURB_H);
      }
      // 画廊最东侧是外墙，拉满整面墙给画框挂画
      if (room.id === 'gallery') {
        wallSeg(x + w, y, x + w, y + h, WALL_H);
      }
    }
    // 外墙（沿楼板四周一圈矮墙 + 四角立柱）
    const [sx, sy, sw, sh] = plan.slab;
    wallSeg(sx, sy, sx + sw, sy, CURB_H);
    wallSeg(sx, sy, sx, sy + sh, CURB_H);
    wallSeg(sx + sw, sy, sx + sw, sy + sh, CURB_H);
    const postMat = mat(0x22303e, { metal: 0.7, rough: 0.35, emissive: 0x0a2a33, ei: 1 });
    for (const [px, pz] of [[sx, sy], [sx + sw, sy], [sx, sy + sh], [sx + sw, sy + sh]]) {
      const p = cyl(0.09, 0.12, 2.8, postMat, px, 1.4, pz, 12);
      scene.add(p);
    }
  }

  // ------------------------------------------------------------ 窗 / 门
  function buildWindows() {
    for (const win of plan.windows) {
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      const len = Math.hypot(bx - ax, by - ay);
      if (len < 0.2) continue;
      const horiz = Math.abs(ay - by) < 0.01;
      const cx = (ax + bx) / 2, cz = (ay + by) / 2;
      // 玻璃（城市外景贴图暂不启用，避免窗面像一块海报）
      const glass = box(horiz ? len : 0.06, 1.35, horiz ? 0.06 : len,
        new THREE.MeshStandardMaterial({
          color: 0x9fb8c8, transparent: true, opacity: 0.035,
          metalness: 0.2, roughness: 0.05, emissive: 0x0a1a22, emissiveIntensity: 0.6, envMapIntensity: 0.2,
        }),
        cx, 1.55, cz);
      glass.castShadow = false;
      glass.receiveShadow = false;
      scene.add(glass);
      // 框
      const fm = mat(0x0c141c, { metal: 0.8, rough: 0.3 });
      const f1 = box(horiz ? len : 0.1, 0.06, horiz ? 0.1 : len, fm, cx, 0.88, cz);
      const f2 = box(horiz ? len : 0.1, 0.06, horiz ? 0.1 : len, fm, cx, 2.22, cz);
      scene.add(f1, f2);
      const jamb = 0.07;
      for (const k of [0, 1]) {
        const px = ax + (bx - ax) * k;
        const pz = ay + (by - ay) * k;
        scene.add(box(horiz ? jamb : 0.1, 1.4, horiz ? 0.1 : jamb, fm, px, 1.55, pz));
      }
      scene.add(box(horiz ? len : 0.1, 0.07, horiz ? 0.1 : len, fm, cx, 2.2, cz));
      scene.add(box(horiz ? len + 0.2 : 0.26, 0.06, horiz ? 0.26 : len + 0.2,
        mat(0x2a2622, { metal: 0.2, rough: 0.6 }), cx, 0.9, cz));
      // 竖向窗棂
      const n = Math.max(1, Math.round(len / 0.9));
      for (let i = 1; i < n; i++) {
        const k = i / n;
        const px = ax + (bx - ax) * k;
        const pz = ay + (by - ay) * k;
        const bar = box(0.05, 1.35, 0.05, fm, px, 1.55, pz);
        scene.add(bar);
      }
      // 窗帘（软装）
      const inward = horiz ? (ay < 4 ? 1 : -1) : (ax > 6 ? -1 : 1);
      const curtainMat = mat(0x3a2e26, { metal: 0.05, rough: 0.95 });
      for (const k of [0.04, 0.96]) {
        const px = ax + (bx - ax) * k;
        const pz = ay + (by - ay) * k;
        const curt = horiz
          ? box(0.32, 2.15, 0.1, curtainMat, px, 1.15, pz + inward * 0.22)
          : box(0.1, 2.15, 0.32, curtainMat, px + inward * 0.22, 1.15, pz);
        scene.add(curt);
      }
      const rod = horiz
        ? box(len + 0.4, 0.04, 0.04, mat(0x0c141c, { metal: 0.8, rough: 0.3 }), cx, 2.28, cz + inward * 0.22)
        : box(0.04, 0.04, len + 0.4, mat(0x0c141c, { metal: 0.8, rough: 0.3 }), cx + inward * 0.22, 2.28, cz);
      scene.add(rod);
    }
  }

  function buildDoors() {
    for (const d of plan.doors) {
      const fm = mat(0x141210, { metal: 0.7, rough: 0.35 });
      const wood = mat(0x2a1c12, { metal: 0.25, rough: 0.7 });
      const brass = mat(0xc8b090, { metal: 0.85, rough: 0.2 });
      const glass = new THREE.MeshStandardMaterial({
        color: 0x9fb8c8, transparent: true, opacity: 0.16, metalness: 0.2, roughness: 0.08,
      });
      const head = mat(0x1f242b, { metal: 0.4, rough: 0.65 });
      const v = d.dir === 'v';
      const fx = v ? d.x + 0.12 : d.x + d.w / 2;
      const fz = v ? d.y + d.w / 2 : d.y + 0.12;

      // 门洞上方的墙头（以免门洞一直开到顶）
      scene.add(box(v ? 0.12 : d.w, WALL_H - 2.2, v ? d.w : 0.12,
        head, fx, 2.2 + (WALL_H - 2.2) / 2, fz));

      // 门框 + 门槛
      if (v) {
        scene.add(box(0.2, 2.2, 0.08, fm, fx, 1.1, d.y));
        scene.add(box(0.2, 2.2, 0.08, fm, fx, 1.1, d.y + d.w));
        scene.add(box(0.2, 0.1, d.w + 0.16, fm, fx, 2.2, fz));
        scene.add(box(0.34, 0.03, d.w, mat(0x2a2622, { metal: 0.4, rough: 0.5 }), fx, 0.015, fz));
      } else {
        scene.add(box(0.08, 2.2, 0.2, fm, d.x, 1.1, fz));
        scene.add(box(0.08, 2.2, 0.2, fm, d.x + d.w, 1.1, fz));
        scene.add(box(d.w + 0.16, 0.1, 0.2, fm, fx, 2.2, fz));
        scene.add(box(d.w, 0.03, 0.34, mat(0x2a2622, { metal: 0.4, rough: 0.5 }), fx, 0.015, fz));
      }

      // 门扇：推拉门半开玻璃；平开门转到 90° 靠着墙，不堵通道
      if (d.no_leaf) {
        // 画廊留成敞开的门洞，第一人称才不会被门扇挡住
      } else if (d.sliding) {
        const slideMat = (d.y > 5.0 && d.x < 8.5)
          ? new THREE.MeshStandardMaterial({
              color: 0xdfe8ee, transparent: true, opacity: 0.55, metalness: 0.1, roughness: 0.35,
            })
          : glass;
        const panel = v
          ? box(0.04, 2.05, d.w * 0.55, slideMat, fx, 1.025, d.y + d.w * 0.25)
          : box(d.w * 0.55, 2.05, 0.04, slideMat, d.x + d.w * 0.25, 1.025, fz);
        panel.castShadow = false;
        scene.add(panel);
      } else if (v) {
        scene.add(box(d.w * 0.95, 2.05, 0.04, wood,
          fx + d.w * 0.45, 1.025, d.y + d.w + 0.04));
        scene.add(box(0.025, 0.025, 0.14, brass,
          fx + d.w * 0.85, 1.0, d.y + d.w + 0.04));
      } else {
        scene.add(box(0.04, 2.05, d.w * 0.95, wood,
          d.x + d.w + 0.04, 1.025, fz + d.w * 0.45));
        scene.add(box(0.14, 0.025, 0.025, brass,
          d.x + d.w + 0.04, 1.0, fz + d.w * 0.85));
      }
    }
  }

  // ------------------------------------------------------------ 家具
  function makeLabel(text) {
    const c = document.createElement('canvas');
    c.width = 512; c.height = 128;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(4,10,16,.78)';
    g.fillRect(0, 0, 512, 128);
    g.strokeStyle = 'rgba(103,232,249,.5)';
    g.lineWidth = 3;
    g.strokeRect(2, 2, 508, 124);
    g.font = '600 54px "Microsoft YaHei", sans-serif';
    g.fillStyle = '#9fe8ff';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 256, 68);
    const tex = new THREE.CanvasTexture(c);
    const m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
    const s = new THREE.Sprite(m);
    s.scale.set(1.5, 0.38, 1);
    return s;
  }

  function buildBathroomFix() {
    const glass = new THREE.MeshStandardMaterial({
      color: 0xbfd8e4, transparent: true, opacity: 0.14, metalness: 0.15, roughness: 0.12,
    });
    const frame = mat(0x141210, { metal: 0.8, rough: 0.3 });
    const wet = mat(0x202a31, { metal: 0.2, rough: 0.85 });
    const chrome = mat(0xb8c8d0, { metal: 0.9, rough: 0.2 });
    const x = 10.25;

    // 湿区深色地面
    scene.add(box(2.08, 0.02, 2.55, wet, 11.32, 0.025, 6.2));

    // 玻璃隔断：两段固定 + 中间门洞（z 5.5~6.4）
    const panel = (w, h, d, px, py, pz) => {
      const m = box(w, h, d, glass, px, py, pz);
      m.castShadow = false;
      m.receiveShadow = false;
      scene.add(m);
      return m;
    };
    panel(0.03, 1.4, 0.6, x, 0.72, 5.2);
    panel(0.03, 1.4, 1.1, x, 0.72, 6.95);
    panel(0.9, 1.35, 0.03, x + 0.45, 0.68, 5.5); // 半开玻璃门

    // 框 + 门槛
    scene.add(box(0.06, 0.06, 2.6, frame, x, 1.43, 6.2));
    scene.add(box(0.06, 0.04, 2.6, frame, x, 0.02, 6.2));
    for (const z of [4.9, 5.5, 6.4, 7.5]) {
      scene.add(box(0.06, 1.45, 0.06, frame, x, 0.725, z));
    }
    scene.add(box(0.03, 0.03, 0.14, chrome, x + 0.82, 0.68, 5.5));
    scene.add(box(0.12, 0.035, 2.58, mat(0x2a2622, { metal: 0.4, rough: 0.5 }), x, 0.018, 6.2));

    // 干区毛巾杆 + 卫生纸架
    const bar = cyl(0.015, 0.015, 0.62, chrome, 8.31, 1.15, 5.28, 8);
    bar.rotation.x = Math.PI / 2;
    scene.add(bar);
    scene.add(box(0.025, 0.025, 0.16, chrome, 8.3, 0.66, 6.55));
  }

  function buildRoomLabels() {
    const names = {
      her_room: '她的房间', dad_room: '我的房间', living: '客厅',
      kitchen: '厨房', toilet: '厕所', balcony: '阳台',
    };
    for (const room of plan.rooms) {
      const [x, y, w, h] = room.rect;
      const s = makeLabel(names[room.id] || room.name);
      s.position.set(x + w / 2, 2.62, y + h / 2);
      scene.add(s);
      roomLabels.push(s);
    }
  }

  function buildFurniture() {
    for (const f of plan.furniture) {
      const g = new THREE.Group();
      const r = f.r;
      let cx, cz, w, d;
      if (Array.isArray(r) && r.length === 4) {
        cx = r[0] + r[2] / 2;
        cz = r[1] + r[3] / 2;
        w = r[2]; d = r[3];
      } else {
        cx = f.x; cz = f.y; w = d = 0.3;
      }
      g.position.set(cx, 0, cz);
      if (f.rot) g.rotation.y = f.rot;
      const kind = f.t;
      // 有成熟 GLTF 的物品不再同时生成程序模型，否则两套家具会叠在一起。
      // 盆栽/桌椅/柜子/书架/书桌/茶几都走 Poly Haven 模型。
      if (MODEL_MAP[kind]) continue;

      if (kind === 'bed') {
        const base = rbox(w, 0.35, d, 0.05, mat(0x2a2623, { metal: 0.5, rough: 0.5 }), 0, 0.2, 0);
        const mattress = rbox(w - 0.08, 0.22, d - 0.08, 0.06,
          mat(0xe2dacb, { metal: 0.05, rough: 0.9 }), 0, 0.47, 0);
        const duvet = rbox(w - 0.12, 0.14, d * 0.66, 0.06,
          mat(0x3b3b43, { metal: 0.15, rough: 0.88 }), 0, 0.61, d * 0.15);
        g.add(base, mattress, duvet);
        // 床头软包竖条
        for (let i = 0; i < 5; i++) {
          const cw = (w - 0.1) / 5;
          g.add(rbox(cw - 0.03, 0.8, 0.1, 0.03,
            mat(i % 2 ? 0x2e2822 : 0x3a322a, { metal: 0.2, rough: 0.85 }),
            -w / 2 + 0.05 + cw * (i + 0.5), 0.52, -d / 2 + 0.08));
        }
        // 床脚
        for (const [lx, lz] of [[-w / 2 + 0.12, -d / 2 + 0.12], [w / 2 - 0.12, -d / 2 + 0.12],
          [-w / 2 + 0.12, d / 2 - 0.12], [w / 2 - 0.12, d / 2 - 0.12]]) {
          g.add(box(0.07, 0.13, 0.07, mat(0x15110d, { metal: 0.5, rough: 0.4 }), lx, 0.065, lz));
        }
        // 被子上沿翻边 + 床尾毯
        g.add(rbox(w - 0.18, 0.05, 0.28, 0.03,
          mat(0xd8cfbf, { metal: 0.05, rough: 0.92 }), 0, 0.67, -d * 0.12));
        g.add(rbox(w - 0.22, 0.06, 0.5, 0.03,
          mat(0xb08a5a, { metal: 0.05, rough: 0.95 }), 0, 0.68, d * 0.32));
        // 枕头
        for (const sx of [-w * 0.2, w * 0.2]) {
          g.add(rbox(w * 0.34, 0.16, 0.4, 0.06,
            mat(0xe6ddd0, { metal: 0.05, rough: 0.9 }), sx, 0.67, -d / 2 + 0.36));
        }
        // 床底灯带
        g.add(box(w - 0.16, 0.012, 0.03,
          new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }),
          0, 0.12, d / 2 - 0.1));
      } else if (kind === 'sofa') {
        const base = rbox(w, 0.28, d * 0.8, 0.05,
          mat(0x26262b, { metal: 0.15, rough: 0.9 }), 0, 0.14, d * 0.05);
        const back = rbox(w, 0.78, 0.18, 0.06,
          mat(0x36363d, { metal: 0.15, rough: 0.88 }), 0, 0.42, -d / 2 + 0.09);
        const armL = rbox(0.16, 0.58, d * 0.8, 0.06,
          mat(0x36363d, { metal: 0.15, rough: 0.88 }), -w / 2 + 0.08, 0.29, d * 0.05);
        const armR = armL.clone(); armR.position.x = w / 2 - 0.08;
        g.add(base, back, armL, armR);
        // 两块独立座垫
        for (const sx of [-w * 0.235, w * 0.235]) {
          g.add(rbox(w * 0.44, 0.18, d * 0.7, 0.06,
            mat(0x3e3e46, { metal: 0.1, rough: 0.92 }), sx, 0.4, d * 0.05));
        }
        // 三块靠背垫
        for (let i = 0; i < 3; i++) {
          g.add(rbox(0.36, 0.34, 0.18, 0.06,
            mat(0x44444c, { metal: 0.1, rough: 0.9 }),
            -w * 0.28 + i * w * 0.28, 0.55, -d / 2 + 0.2));
        }
        // 滚边
        g.add(box(w - 0.24, 0.02, 0.03,
          mat(0x5a5a62, { metal: 0.3, rough: 0.6 }), 0, 0.5, d * 0.05 + d * 0.36));
        // 搭毯 + 抱枕
        g.add(rbox(0.3, 0.42, 0.5, 0.04,
          mat(0xb08a5a, { metal: 0.05, rough: 0.95 }), w / 2 - 0.2, 0.45, d / 2 - 0.28));
        g.add(rbox(0.32, 0.28, 0.12, 0.06,
          mat(0x6a6a72, { metal: 0.1, rough: 0.9 }), -w * 0.22, 0.55, -d / 2 + 0.26));
        // 沙发脚
        for (const lx of [-w / 2 + 0.12, w / 2 - 0.12]) {
          for (const lz of [-d / 2 + 0.12, d / 2 - 0.12]) {
            g.add(cyl(0.035, 0.025, 0.1,
              mat(0x15110d, { metal: 0.7, rough: 0.35 }), lx, 0.05, lz, 8));
          }
        }
      } else if (kind === 'desk' || kind === 'table') {
        const top = rbox(w, 0.06, d, 0.025, mat(0x4a3322, { metal: 0.5, rough: 0.35 }), 0, 0.74, 0);
        g.add(top);
        g.add(box(0.2, 0.03, 0.14, mat(0x8a6a3a, { metal: 0.05, rough: 0.9 }), 0.08, 0.785, 0.02));
        g.add(cyl(0.045, 0.035, 0.07, mat(0xc6d3dd, { metal: 0.1, rough: 0.4 }), -0.1, 0.8, 0.04, 10));
        for (const [lx, lz] of [[-w / 2 + 0.08, -d / 2 + 0.08], [w / 2 - 0.08, -d / 2 + 0.08],
          [-w / 2 + 0.08, d / 2 - 0.08], [w / 2 - 0.08, d / 2 - 0.08]]) {
          g.add(box(0.05, 0.74, 0.05, mat(0x1a1816, { metal: 0.7, rough: 0.4 }), lx, 0.37, lz));
        }
      } else if (kind === 'chair') {
        const seat = box(w * 0.8, 0.08, d * 0.8, mat(0x3a2a1d, { metal: 0.3, rough: 0.7 }), 0, 0.46, 0);
        const back = box(w * 0.8, 0.55, 0.07, mat(0x2e2e33, { metal: 0.3, rough: 0.7 }), 0, 0.72, -d * 0.35);
        const leg = box(0.05, 0.46, 0.05, mat(0x121a24, { metal: 0.7, rough: 0.4 }), 0, 0.23, 0);
        g.add(seat, back, leg);
      } else if (kind === 'shelf' || kind === 'wardrobe' || kind === 'rack') {
        const hh = kind === 'rack' ? 1.7 : 2.0;
        const body = box(w, hh, d, mat(0x1e2a38, { metal: 0.45, rough: 0.5 }), 0, hh / 2, 0);
        g.add(body);
        if (kind === 'shelf') {
          const colors = [0x2f6f7a, 0x4a5f8a, 0x6b4a7a, 0x8a6a3a, 0x35607a];
          for (let i = 0; i < 12; i++) {
            const bh = 0.18 + (i % 3) * 0.04;
            g.add(box(0.06, bh, 0.22, mat(colors[i % colors.length], { metal: 0.1, rough: 0.8 }),
              -w / 2 + 0.12 + (i % 6) * 0.13, 0.5 + Math.floor(i / 6) * 0.7, 0));
          }
        }
      } else if (kind === 'cabinet') {
        g.add(rbox(w, 0.9, d, 0.03, mat(0x22303f, { metal: 0.45, rough: 0.5 }), 0, 0.45, 0));
        for (const sx of [-w * 0.25, w * 0.25]) {
          g.add(box(w * 0.46, 0.8, 0.02,
            mat(0x2e3c4a, { metal: 0.4, rough: 0.55 }), sx, 0.45, d / 2 + 0.01));
          g.add(box(0.03, 0.2, 0.03,
            mat(0xc8b090, { metal: 0.85, rough: 0.2 }), sx + w * 0.18, 0.45, d / 2 + 0.04));
        }
      } else if (kind === 'counter') {
        g.add(rbox(w, 0.88, d, 0.03, mat(0x2b3642, { metal: 0.55, rough: 0.4 }), 0, 0.44, 0));
        g.add(rbox(w + 0.04, 0.05, d + 0.04, 0.02, mat(0x3a4856, { metal: 0.7, rough: 0.3 }), 0, 0.9, 0));
      } else if (kind === 'fridge') {
        g.add(box(w, 1.9, d, mat(0x4a5a6b, { metal: 0.75, rough: 0.3 }), 0, 0.95, 0));
        g.add(box(w + 0.01, 0.02, d + 0.01, new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.3 }), 0, 1.2, 0));
        // 冰箱门朝南（+Z），门缝和把手做得清楚一点
        g.add(box(0.012, 1.78, 0.015, mat(0x26313c, { metal: 0.5, rough: 0.45 }),
          0, 0.95, d / 2 + 0.009));
        g.add(box(0.04, 0.42, 0.03, mat(0xc8d8e0, { metal: 0.9, rough: 0.15 }),
          w * 0.30, 1.2, d / 2 + 0.025));
      } else if (kind === 'microwave') {
        // 放在可够到的柜子上（柜面 0.9m），门朝南（+Z）
        const by = 1.12;
        g.add(box(w, 0.38, d, mat(0xd7dee6, { metal: 0.65, rough: 0.35 }), 0, by, 0));
        g.add(box(w * 0.66, 0.26, 0.015,
          new THREE.MeshStandardMaterial({
            color: 0x0a1018, metalness: 0.2, roughness: 0.1,
            emissive: 0x123244, emissiveIntensity: 0.8,
            transparent: true, opacity: 0.92,
          }), 0, by, d / 2 + 0.009));
        g.add(box(0.035, 0.22, 0.03,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.15 }),
          w * 0.34, by, d / 2 + 0.028));
        g.add(box(0.10, 0.10, 0.02,
          mat(0x0a0f16, { metal: 0.3, rough: 0.3 }),
          -w * 0.33, by, d / 2 + 0.022));
      } else if (kind === 'water') {
        // 客厅饮水机：下柜 + 蓝色水桶 + 两个龙头；水一直是满的
        g.add(box(w, 0.9, d, mat(0x2c3846, { metal: 0.6, rough: 0.4 }), 0, 0.45, 0));
        g.add(box(w + 0.02, 0.04, d + 0.02,
          mat(0x3d4c5c, { metal: 0.7, rough: 0.3 }), 0, 0.92, 0));
        const bottle = cyl(w * 0.34, w * 0.34, 0.55,
          new THREE.MeshStandardMaterial({
            color: 0x6fd0ff, metalness: 0.1, roughness: 0.15,
            transparent: true, opacity: 0.6,
            emissive: 0x0a3a55, emissiveIntensity: 0.8,
          }), 0, 1.24, 0, 20);
        g.add(bottle);
        g.add(cyl(0.035, 0.03, 0.12, mat(0xc8d8e0, { metal: 0.9, rough: 0.15 }),
          0, 0.98, d / 2 + 0.03, 10));
        g.add(box(0.14, 0.018, 0.1, mat(0x9fd3ff, { metal: 0.2, rough: 0.2 }),
          0, 0.99, d / 2 + 0.08));
      } else if (kind === 'toilet') {
        g.add(box(w * 0.6, 0.75, d * 0.35, mat(0xc6d3dd, { metal: 0.05, rough: 0.6 }), 0, 0.38, -d * 0.28));
        const bowl = cyl(w * 0.42, w * 0.34, 0.4, mat(0xe2ecf2, { metal: 0.05, rough: 0.5 }), 0, 0.2, d * 0.08, 24);
        bowl.scale.z = 0.8;
        g.add(bowl);
        g.add(rbox(w * 0.5, 0.06, d * 0.4, 0.03,
          mat(0xf0f6fa, { metal: 0.05, rough: 0.35 }), 0, 0.43, d * 0.04));
      } else if (kind === 'vanity') {
        g.add(box(w, 0.8, d, mat(0x22303f, { metal: 0.45, rough: 0.5 }), 0, 0.4, 0));
        g.add(box(w * 0.7, 0.04, d * 0.6, mat(0x8ea4b4, { metal: 0.6, rough: 0.25 }), 0, 0.83, 0));
        g.add(rbox(w * 0.46, 0.1, d * 0.38, 0.03,
          mat(0xe2ecf2, { metal: 0.05, rough: 0.35 }), 0, 0.88, 0));
        g.add(box(w * 0.38, 0.02, d * 0.3,
          mat(0x7f96a6, { metal: 0.4, rough: 0.3 }), 0, 0.9, 0));
        g.add(cyl(0.02, 0.02, 0.24,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.2 }), 0, 1.02, -d * 0.2, 10));
        g.add(box(0.16, 0.02, 0.02,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.2 }), 0.07, 1.13, -d * 0.2));
      } else if (kind === 'tub') {
        const chrome = mat(0xc8d8e0, { metal: 0.9, rough: 0.2 });
        g.add(box(w, 0.55, d, mat(0xc6d3dd, { metal: 0.05, rough: 0.5 }), 0, 0.28, 0));
        g.add(box(w - 0.2, 0.06, d - 0.2, mat(0x7f96a6, { metal: 0.1, rough: 0.5 }), 0, 0.56, 0));
        g.add(cyl(0.018, 0.018, 0.32, chrome, w / 2 - 0.12, 0.72, -d * 0.3, 8));
        g.add(box(0.16, 0.03, 0.03, chrome, w / 2 - 0.2, 0.88, -d * 0.3));
      } else if (kind === 'monitor') {
        // 书桌上的电脑：屏幕落在桌面附近，键盘/鼠标/主机都在
        g.add(box(0.30, 0.02, 0.18, mat(0x0b1016, { metal: 0.4, rough: 0.4 }), 0, 0.74, 0));
        g.add(box(0.035, 0.24, 0.035, mat(0x1a1816, { metal: 0.7, rough: 0.4 }), 0, 0.86, 0));
        g.add(box(0.26, 0.02, 0.14, mat(0x1a1816, { metal: 0.6, rough: 0.4 }), 0, 0.77, 0.06));
        const screen = box(0.58, 0.34, 0.04,
          mat(0x071019, { metal: 0.25, rough: 0.22, emissive: 0x0b4a5e, ei: 0.9 }),
          0, 1.02, 0);
        g.add(screen);
        g.add(box(0.64, 0.40, 0.05, mat(0x141c24, { metal: 0.5, rough: 0.35 }), 0, 1.02, -0.02));
        g.add(box(0.34, 0.018, 0.13, mat(0x202830, { metal: 0.2, rough: 0.8 }), 0, 0.78, 0.10));
        g.add(box(0.07, 0.02, 0.045, mat(0x202830, { metal: 0.2, rough: 0.8 }), 0.24, 0.78, 0.10));
        const pc = box(0.20, 0.42, 0.24, mat(0x10161d, { metal: 0.5, rough: 0.35 }), 0, 0.21, -0.12);
        g.add(pc);
        g.add(box(0.05, 0.05, 0.01, new THREE.MeshBasicMaterial({ color: 0x67e8f9 }), -0.03, 0.32, 0.012));
        g.add(box(0.05, 0.03, 0.01, new THREE.MeshBasicMaterial({ color: 0xf472b6 }), 0.04, 0.25, 0.012));
        const glow = new THREE.PointLight(0x67e8f9, 0.35, 1.2);
        glow.position.set(0, 1.05, 0.25);
        g.add(glow);
      } else if (kind === 'tv') {
        // 电视靠西墙：薄屏朝东，下面有矮柜和回音壁
        g.add(box(0.34, 0.32, 1.18, mat(0x1b211f, { metal: 0.35, rough: 0.55 }), 0, 0.18, 0));
        g.add(box(0.48, 0.05, 1.34, mat(0x2a2118, { metal: 0.5, rough: 0.35 }), 0, 0.36, 0));
        g.add(box(0.06, 0.72, 1.14,
          mat(0x03070b, { metal: 0.15, rough: 0.18, emissive: 0x072a3a, ei: 0.7 }),
          0.02, 1.12, 0));
        g.add(box(0.08, 0.80, 1.22, mat(0x0a0f14, { metal: 0.55, rough: 0.3 }), 0, 1.12, 0));
        g.add(box(0.06, 0.045, 1.02, new THREE.MeshBasicMaterial({ color: 0x67e8f9 }), 0.065, 0.76, 0));
        const tvGlow = new THREE.PointLight(0x67e8f9, 0.5, 2.4);
        tvGlow.position.set(0.45, 1.12, 0);
        g.add(tvGlow);
      } else if (kind === 'lamp') {
        const rad = typeof f.r === 'number' ? f.r : 0.14;
        const pole = cyl(0.025, 0.03, 1.5, mat(0x2a3745, { metal: 0.8, rough: 0.3 }), 0, 0.75, 0, 10);
        const bulb = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.09, rad * 1.0), 16, 12),
          new THREE.MeshBasicMaterial({ color: 0x8fe0f5 }));
        bulb.position.set(0, 1.55, 0);
        g.add(pole, bulb);
        if (GLOW_TEX) {
          const halo = new THREE.Sprite(new THREE.SpriteMaterial({
            map: GLOW_TEX, color: 0xffc880, transparent: true, opacity: 0.55,
            depthWrite: false, blending: THREE.AdditiveBlending,
          }));
          halo.scale.set(0.6, 0.6, 1);
          halo.position.set(0, 1.55, 0);
          g.add(halo);
        }
        const light = new THREE.PointLight(0x9fe8ff, 0, 6.5);
        light.position.set(0, 1.55, 0);
        g.add(light);
        lamps.push(light);
      } else if (kind === 'plant') {
        const rad = typeof f.r === 'number' ? f.r : 0.2;
        const pot = cyl(rad * 0.5, rad * 0.4, 0.3, mat(0x16302c, { metal: 0.1, rough: 0.8 }), 0, 0.15, 0, 14);
        g.add(pot);
        for (let i = 0; i < 3; i++) {
          const leaf = new THREE.Mesh(new THREE.SphereGeometry(rad * 0.55, 12, 10),
            mat(0x2e6b5e, { metal: 0.05, rough: 0.9 }));
          leaf.position.set((i - 1) * rad * 0.3, 0.55 + i * 0.12, (i % 2) * rad * 0.2);
          leaf.scale.set(1, 1.25, 1);
          g.add(leaf);
        }
      } else if (kind === 'rug') {
        const rugMat = new THREE.MeshStandardMaterial({
          map: makeRugTexture(), color: 0xffffff, metalness: 0.1, roughness: 0.92, transparent: true, envMapIntensity: 0.25,
        });
        const rug = box(w, 0.02, d, rugMat, 0, 0.035, 0);
        g.add(rug);
        const rim = box(w, 0.005, 0.03, new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.25 }), 0, 0.05, d / 2 - 0.04);
        g.add(rim);
      } else if (kind === 'sink') {
        g.add(rbox(0.46, 0.06, 0.34, 0.02,
          mat(0x9fb0bc, { metal: 0.7, rough: 0.3 }), 0, 0.93, 0));
        g.add(box(0.34, 0.02, 0.24,
          mat(0x0b1218, { metal: 0.4, rough: 0.3 }), 0, 0.96, 0));
        g.add(cyl(0.025, 0.03, 0.28,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.2 }), 0, 1.08, -0.15, 10));
        g.add(box(0.2, 0.025, 0.025,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.2 }), 0.1, 1.21, -0.15));
      } else if (kind === 'stove') {
        g.add(rbox(0.58, 0.03, 0.52, 0.02,
          mat(0x10161c, { metal: 0.5, rough: 0.3 }), 0, 0.94, 0));
        for (const [bx, bz] of [[-0.14, -0.12], [0.14, -0.12], [-0.14, 0.12], [0.14, 0.12]]) {
          g.add(cyl(0.07, 0.07, 0.015,
            mat(0x222a30, { metal: 0.6, rough: 0.3 }), bx, 0.955, bz, 16));
          g.add(cyl(0.055, 0.055, 0.006,
            mat(0x0a0f14, { metal: 0.3, rough: 0.5 }), bx, 0.965, bz, 16));
        }
      } else if (kind === 'coffee') {
        g.add(box(w, 0.05, d, mat(0x1e3244, { metal: 0.4, rough: 0.3 }), 0, 0.42, 0));
        g.add(box(w * 0.9, 0.38, d * 0.9, mat(0x2e2e33, { metal: 0.4, rough: 0.6 }), 0, 0.2, 0));
      } else if (kind === 'rail') {
        if (f.a && f.a[1] > 8.5) continue;
        if (f.a && f.b) {
          const len = Math.hypot(f.b[0] - f.a[0], f.b[1] - f.a[1]);
          const rail = box(len, 0.05, 0.05, mat(0x2a3745, { metal: 0.8, rough: 0.3 }), 0, 0.9, 0);
          rail.position.set(cx, 0.9, cz);
          rail.rotation.y = Math.atan2(f.b[1] - f.a[1], f.b[0] - f.a[0]);
          scene.add(rail);
        }
        continue;
      } else if (kind === 'shower') {
        const showerGlass = new THREE.MeshStandardMaterial({
          color: 0x9fc8d8, transparent: true, opacity: 0.16, metalness: 0.2, roughness: 0.08,
        });
        const chrome = mat(0xb8c8d0, { metal: 0.9, rough: 0.2 });
        g.add(rbox(w, 0.08, d, 0.02, mat(0x2a3038, { metal: 0.2, rough: 0.7 }), 0, 0.04, 0));
        g.add(box(w, 0.05, 0.04, mat(0x3a4048, { metal: 0.2, rough: 0.6 }), 0, 0.085, -d / 2 + 0.02));
        const gp = box(0.03, 1.95, d, showerGlass, w / 2, 0.98, 0);
        gp.castShadow = false;
        g.add(gp);
        g.add(cyl(0.018, 0.018, 0.85, chrome, 0, 1.42, d / 2 - 0.06, 8));
        g.add(box(0.04, 0.04, 0.38, chrome, 0, 1.85, d / 2 - 0.22));
        g.add(cyl(0.11, 0.11, 0.018, chrome, 0, 1.85, d / 2 - 0.4, 16));
        g.add(cyl(0.05, 0.05, 0.008, mat(0x0a0f14, { metal: 0.5, rough: 0.4 }), 0, 0.085, 0.1, 12));
      } else if (kind === 'towel' || kind === 'rack') {
        g.add(box(w, 0.5, d, mat(0x3a4a58, { metal: 0.1, rough: 0.9 }), 0, 0.9, 0));
      }

      if (g.children.length === 0) continue;
      // 顶面/底边冷光
      if (kind !== 'rug' && kind !== 'rail') {
        const edge = new THREE.Box3().setFromObject(g);
        const sx2 = edge.max.x - edge.min.x;
        const sz2 = edge.max.z - edge.min.z;
        const topY = edge.max.y;
        if (topY > 0.1 && sx2 > 0.05 && sz2 > 0.05) {
          const rim = box(sx2 * 0.92, 0.015, 0.02,
            new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }),
            0, topY + 0.01, sz2 / 2 - 0.03);
          g.add(rim);
        }
      }
      if (Array.isArray(f.r) && f.r.length === 4 &&
          ['bed', 'sofa', 'desk', 'table', 'counter', 'cabinet', 'fridge',
            'wardrobe', 'shelf', 'tub', 'toilet', 'vanity', 'coffee'].indexOf(kind) >= 0) {
        addContact(cx, cz, w + 0.4, d + 0.4);
        addSoftShadow(cx, cz, w + 0.7, d + 0.7);
      }
      scene.add(g);
      f._proc = g;
      registerFade(g);
      g.traverse(o => { if (o.isMesh) occluderMeshes.push(o); });
    }
  }

  // ------------------------------------------------------------ 成熟模型（Poly Haven, CC0）
  const MODEL_MAP = {
    coffee: 'coffee_table',
    table: 'dining_table',
    chair: 'dining_chair',
    shelf: 'shelf',
    cabinet: 'cabinet',
    desk: 'office_desk',
    plant: 'planter',
  };
  const MODEL_ROT = {
    bed: 0, sofa: Math.PI / 2, coffee_table: 0, dining_table: 0, dining_chair: 0,
    shelf: 0, cabinet: 0, office_desk: 0, planter: 0,
  };

  function tuneModel(root) {
    root.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mats) {
        if (!m) continue;
        m.envMapIntensity = 0.6;
        applyHole(m);
      }
      occluderMeshes.push(o);
    });
  }

  function chairRotation(f) {
    const r = f.r;
    const cx = r[0] + r[2] / 2;
    const cz = r[1] + r[3] / 2;
    let bx = null, bz = null, bd = 1e9;
    for (const g of plan.furniture) {
      if (['table', 'desk', 'coffee'].indexOf(g.t) < 0) continue;
      if (!Array.isArray(g.r)) continue;
      const gx = g.r[0] + g.r[2] / 2;
      const gz = g.r[1] + g.r[3] / 2;
      const d = Math.hypot(gx - cx, gz - cz);
      if (d < bd && d < 3.2) { bd = d; bx = gx; bz = gz; }
    }
    if (bx === null) return 0;
    // dining_chair 模型的椅背在 -Z、座位朝 +Z；转到"座位朝向桌子"即可。
    // 以前多加了 PI，导致所有椅子背对桌子（你 2026-11-01 指出的问题）。
    return Math.atan2(bx - cx, bz - cz);
  }
  function loadFurnitureModels() {
    const loader = new THREE.GLTFLoader();
    for (const f of plan.furniture) {
      const key = MODEL_MAP[f.t];
      if (!key) continue;
      let x, z, w, d;
      if (f.t === 'plant' && typeof f.r === 'number') {
        x = f.x; z = f.y; w = d = Math.max(0.18, f.r * 2);
      } else if (Array.isArray(f.r) && f.r.length === 4) {
        x = f.r[0] + f.r[2] / 2;
        z = f.r[1] + f.r[3] / 2;
        w = f.r[2]; d = f.r[3];
      } else {
        continue;
      }
      loader.load('/static/models/' + key + '/model.gltf', gltf => {
        const root = gltf.scene;
        let rot = MODEL_ROT[key] || 0;
        if (f.t === 'chair') rot = chairRotation(f);
        root.rotation.y = rot;
        root.updateMatrixWorld(true);
        let box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3());
        let s;
        if (f.t === 'plant') {
          s = Math.min(w / Math.max(0.01, size.x), d / Math.max(0.01, size.z));
        } else if (f.t === 'table' || f.t === 'desk' || f.t === 'coffee') {
          // 按真实桌面高度定 Y，避免只按平面尺寸缩放后桌子矮成茶几。
          const targetH = f.t === 'coffee' ? 0.43 : (f.t === 'desk' ? 0.74 : 0.75);
          const sx = w / Math.max(0.01, size.x);
          const sz = d / Math.max(0.01, size.z);
          const sy = targetH / Math.max(0.01, size.y);
          root.scale.set(sx, sy, sz);
          s = null;
        } else if (size.y > 1.2) s = 1.9 / size.y;
        else s = Math.min(w / Math.max(0.01, size.x), d / Math.max(0.01, size.z));
        if (s !== null && s !== undefined) root.scale.setScalar(s);
        root.updateMatrixWorld(true);
        box = new THREE.Box3().setFromObject(root);
        const c = box.getCenter(new THREE.Vector3());
        root.position.set(x - c.x, -box.min.y, z - c.z);
        tuneModel(root);
        registerFade(root);
        addContact(x, z, w + 0.35, d + 0.35);
        scene.add(root);
        if (f._proc) {
          scene.remove(f._proc);
          f._proc.traverse(o => {
            if (!o.isMesh) return;
            const i = occluderMeshes.indexOf(o);
            if (i >= 0) occluderMeshes.splice(i, 1);
          });
          f._proc = null;
        }
      }, undefined, err => {
        console.warn('model load failed', key, err);
      });
    }
  }

  // ------------------------------------------------------------ 摆设（复用已有模型）
  function buildProps() {
    const loader = new THREE.GLTFLoader();

    function place(url, x, z, y, targetW, rotY) {
      loader.load(url, gltf => {
        const root = gltf.scene;
        root.rotation.y = rotY || 0;
        root.updateMatrixWorld(true);
        let box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3());
        const s = targetW / Math.max(0.2, Math.max(size.x, size.z));
        root.scale.setScalar(s);
        root.updateMatrixWorld(true);
        box = new THREE.Box3().setFromObject(root);
        root.position.set(x, y - box.min.y, z);
        tuneModel(root);
        scene.add(root);
      }, undefined, () => {});
    }


    // 阳台花箱
    for (const [px, pz] of [[1.2, 8.15], [4.2, 8.15], [8.8, 8.15]]) {
      place('/static/models/planter/model.gltf', px, pz, 0, 0.72, Math.PI / 2);
    }

    // 客厅单椅（面向咖啡桌）
    place('/static/models/armchair2/model.gltf', 5.5, 6.55, 0, 0.85, Math.PI);
    // 客厅角落绿植
    place('/static/models/planter/model.gltf', 7.55, 0.55, 0, 0.7, 0);

    // 床头柜 + 小灯
    for (const f of plan.furniture) {
      if (f.t !== 'bed' || !Array.isArray(f.r)) continue;
      const [bx, by, bw, bd] = f.r;
      let nx = bx + bw + 0.25;
      if (nx > plan.slab[0] + plan.slab[2] - 0.2) nx = bx - 0.3;
      const nz = by + 0.35;
      const ns = box(0.42, 0.42, 0.42, mat(0x1a2532, { metal: 0.4, rough: 0.5 }), nx, 0.21, nz);
      scene.add(ns);
      const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.06, 10, 8),
        new THREE.MeshBasicMaterial({ color: 0xffe0b0 }));
      bulb.position.set(nx, 0.56, nz);
      scene.add(cyl(0.025, 0.035, 0.16, mat(0x2a2622, { metal: 0.6, rough: 0.4 }), nx, 0.5, nz, 8));
      scene.add(bulb);
      const pl = new THREE.PointLight(0xffd8a8, 0.5, 2.2, 1.5);
      pl.position.set(nx, 0.6, nz);
      scene.add(pl);
      lamps.push(pl);
    }
  }

  function buildDetails() {
    for (const f of plan.furniture) {
      if (!Array.isArray(f.r)) continue;
      const [x, y, w, d] = f.r;
      const cx = x + w / 2;
      const cz = y + d / 2;
      if (f.t === 'bed' && f.note === '她的床') {
        for (let i = 0; i < 20; i++) {
          const zz = 0.55 + i * 0.2;
          if (zz > 2.3 && zz < 3.6) continue; // 给她的房门让出洞口
          scene.add(box(0.03, 2.45, 0.06, mat(0x3a2a1e, { metal: 0.1, rough: 0.8 }), 8.32, 1.25, zz));
        }
      }
      if (f.t === 'tv') {
        // 电视柜/回音壁已在 buildFurniture 的 tv 分支里，这里不再叠一套。
      }
      if (f.t === 'counter') {
        scene.add(box(w, 0.9, 0.03, mat(0x2a2622, { metal: 0.2, rough: 0.6 }), cx, 1.35, y - 0.02));
        scene.add(box(w, 0.55, 0.32, mat(0x3a2e24, { metal: 0.3, rough: 0.5 }), cx, 1.95, y + 0.16));
        scene.add(box(w * 0.9, 0.012, 0.02, new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.25 }), cx, 1.72, y + 0.33));
        scene.add(cyl(0.02, 0.02, 0.35, mat(0x9fb8c8, { metal: 0.9, rough: 0.2 }), cx - 0.2, 1.07, cz, 10));
      }
      if (f.t === 'vanity') {
        scene.add(box(w * 0.9, 0.75, 0.04, mat(0x1a1816, { metal: 0.5, rough: 0.4 }), cx, 1.5, y - 0.05));
        scene.add(box(w * 0.82, 0.65, 0.03, mat(0x9fb8c8, { metal: 0.8, rough: 0.15 }), cx, 1.5, y - 0.02));
        const cols = [0x8a6a4a, 0x5a6a7a, 0x9a8a6a];
        for (let i = 0; i < 3; i++) {
          scene.add(cyl(0.03, 0.035, 0.12 + i * 0.03, mat(cols[i], { metal: 0.2, rough: 0.4 }), x + 0.1 + i * 0.08, 0.86, cz + 0.05, 8));
        }
      }
      if (f.t === 'table' || f.t === 'coffee' || f.t === 'desk') {
        // 模型实际高度不同：餐桌约 0.75m，茶几约 0.43m，书桌约 0.74m。
        const topY = f.t === 'coffee' ? 0.43 : (f.t === 'desk' ? 0.74 : 0.75);
        scene.add(box(0.24, 0.03, 0.17, mat(0x7a5a3a, { metal: 0.05, rough: 0.9 }), cx + 0.15, topY, cz + 0.1));
        scene.add(cyl(0.04, 0.035, 0.07, mat(0xd8d0c2, { metal: 0.1, rough: 0.4 }), cx - 0.12, topY + 0.01, cz + 0.06, 10));
      }
    }
  }
  // 楼外：地面 + 街道 + 3D 楼群 + 路灯 + 夜空
  function buildExterior() {
    // 夜空
    const c = document.createElement('canvas');
    c.width = 2048;
    c.height = 1024;
    const g = c.getContext('2d');
    const grad = g.createLinearGradient(0, 0, 0, 1024);
    grad.addColorStop(0, '#04070e');
    grad.addColorStop(0.45, '#0a1828');
    grad.addColorStop(0.62, '#15304a');
    grad.addColorStop(0.72, '#2a4152');
    grad.addColorStop(1, '#0a0f16');
    g.fillStyle = grad;
    g.fillRect(0, 0, 2048, 1024);
    for (let i = 0; i < 900; i++) {
      g.fillStyle = 'rgba(220,240,255,' + (0.15 + Math.random() * 0.7) + ')';
      g.fillRect(Math.random() * 2048, Math.random() * 560, 1.5, 1.5);
    }
    const mg = g.createRadialGradient(1500, 220, 10, 1500, 220, 130);
    mg.addColorStop(0, 'rgba(225,242,255,.9)');
    mg.addColorStop(1, 'rgba(200,230,255,0)');
    g.fillStyle = mg;
    g.beginPath();
    g.arc(1500, 220, 130, 0, Math.PI * 2);
    g.fill();
    scene.background = new THREE.Color(0x0b1624);

    // 地面 + 街道
    const gc = document.createElement('canvas');
    gc.width = gc.height = 512;
    const gg = gc.getContext('2d');
    gg.fillStyle = '#0b0d12';
    gg.fillRect(0, 0, 512, 512);
    gg.strokeStyle = '#1b2430';
    gg.lineWidth = 2;
    for (let i = 0; i <= 512; i += 64) {
      gg.beginPath(); gg.moveTo(i, 0); gg.lineTo(i, 512); gg.stroke();
      gg.beginPath(); gg.moveTo(0, i); gg.lineTo(512, i); gg.stroke();
    }
    gg.strokeStyle = '#3a3f48';
    gg.lineWidth = 3;
    for (let i = 0; i <= 512; i += 256) {
      gg.beginPath(); gg.moveTo(0, i); gg.lineTo(512, i); gg.stroke();
    }
    gg.strokeStyle = 'rgba(240,220,160,.5)';
    gg.lineWidth = 2;
    gg.setLineDash([14, 14]);
    gg.beginPath(); gg.moveTo(0, 256); gg.lineTo(512, 256); gg.stroke();
    gg.setLineDash([]);
    const gt = new THREE.CanvasTexture(gc);
    gt.wrapS = gt.wrapT = THREE.RepeatWrapping;
    gt.repeat.set(18, 18);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(160, 160),
      new THREE.MeshStandardMaterial({ map: gt, color: 0x55606a, metalness: 0.1, roughness: 0.95, emissive: 0x0a1018, emissiveIntensity: 0.8 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(6.3, -0.45, -20);
    ground.receiveShadow = true;
    scene.add(ground);

    // 楼群
    function makeBuildingTexture() {
      const bc = document.createElement('canvas');
      bc.width = 128;
      bc.height = 256;
      const bg = bc.getContext('2d');
      bg.fillStyle = '#070d16';
      bg.fillRect(0, 0, 128, 256);
      for (let y = 6; y < 250; y += 12) {
        for (let x = 6; x < 122; x += 14) {
          const lit = Math.random() > 0.45;
          bg.fillStyle = lit
            ? 'rgba(255,214,150,' + (0.5 + Math.random() * 0.5) + ')'
            : 'rgba(30,50,70,.5)';
          bg.fillRect(x, y, 7, 6);
        }
      }
      return new THREE.CanvasTexture(bc);
    }
    const bTex = makeBuildingTexture();
    function tower(x, z, w, h) {
      const tex = bTex.clone();
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.set(Math.max(1, Math.round(w / 2)), Math.max(1, Math.round(h / 3)));
      tex.needsUpdate = true;
      const m = new THREE.MeshBasicMaterial({ map: tex, color: 0x9fb8d0, toneMapped: false, fog: true });
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, w * 0.9), m);
      b.position.set(x, h / 2 - 0.4, z);
      scene.add(b);
    }
    for (let i = 0; i < 26; i++) {
      tower(6.3 + (Math.random() - 0.5) * 44, -12 - Math.random() * 18, 2 + Math.random() * 3, 5 + Math.random() * 10);
    }
    for (let i = 0; i < 12; i++) {
      tower(26 + Math.random() * 12, 2 + (Math.random() - 0.5) * 24, 2 + Math.random() * 3, 4 + Math.random() * 8);
    }

    // 路灯
    for (let i = 0; i < 8; i++) {
      const x = -2 + i * 3.0;
      const z = -6;
      scene.add(box(0.07, 3.4, 0.07, mat(0x1a1a1a, { metal: 0.8, rough: 0.3 }), x, 1.7, z));
      const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.1, 8, 6),
        new THREE.MeshBasicMaterial({ color: 0xffd8a0 }));
      bulb.position.set(x, 3.45, z);
      scene.add(bulb);
      const pl = new THREE.PointLight(0xffc880, 0.5, 6, 1.4);
      pl.position.set(x, 3.3, z);
      scene.add(pl);
    }
  }
  // 窗外景：贴合窗洞的城市画面（3D 城市在 45° 机位下会浮在屋顶上，故回退）
  function buildWindowViews() {
    for (const win of plan.windows) {
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      const len = Math.hypot(bx - ax, by - ay);
      if (len < 0.4) continue;
      // 厕所南窗：磨砂，不显示城市
      if (Math.abs(ay - by) < 0.02 && ay > 7.3 && Math.min(ax, bx) > 10.0) {
        const frost = new THREE.Mesh(new THREE.PlaneGeometry(len + 0.3, 1.4),
          new THREE.MeshBasicMaterial({ color: 0x9fb8c8, transparent: true, opacity: 0.28, toneMapped: false }));
        frost.position.set((ax + bx) / 2, 1.55, ay + 0.06);
        scene.add(frost);
        continue;
      }
      const horiz = Math.abs(ay - by) < 0.02;
      const out = horiz ? (ay < 4 ? -1 : 1) : (ax > 6 ? 1 : -1);
      const cx = (ax + bx) / 2;
      const cz = (ay + by) / 2;
      const tex = CITY_NIGHT.clone();
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.set(Math.max(1, len / 4.5), 1);
      tex.needsUpdate = true;
      const m = new THREE.MeshBasicMaterial({ map: tex, color: 0xc8d8e8, toneMapped: false });
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(len + 0.3, 1.4), m);
      if (horiz) {
        plane.position.set(cx, 1.55, cz + out * 0.55);
      } else {
        plane.position.set(cx + out * 0.55, 1.55, cz);
        plane.rotation.y = out > 0 ? -Math.PI / 2 : Math.PI / 2;
      }
      scene.add(plane);
      viewMats.push({ mat: m, night: tex });
    }
  }
  function buildWindowLights() {
    for (const win of plan.windows) {
      if (win.kind !== 'city') continue;
      const [ax, ay] = win.a;
      const [bx, by] = win.b;
      if (Math.abs(ay - by) > 0.02) continue;
      const cx = (ax + bx) / 2;
      const spot = new THREE.SpotLight(0xb0d8ff, 2.5, 16, 0.5, 0.55, 1.2);
      spot.position.set(cx, 2.4, ay - 2.2);
      spot.target.position.set(cx, 0, ay + 2.8);
      spot.castShadow = true;
      spot.shadow.mapSize.set(512, 512);
      spot.shadow.camera.near = 0.5;
      spot.shadow.camera.far = 12;
      spot.shadow.bias = -0.0005;
      spot.shadow.normalBias = 0.02;
      spot.shadow.radius = 3;
      scene.add(spot, spot.target);
      windowSpots.push(spot);
    }
  }
  function buildFineDetails() {
    for (const f of plan.furniture) {
      if (!Array.isArray(f.r)) continue;
      const [x, y, w, d] = f.r;
      const cx = x + w / 2;
      const cz = y + d / 2;
      if (f.t === 'bed') {
        // 被子横向褶皱
        for (let i = 0; i < 6; i++) {
          const zz = y + d * 0.4 + (i / 5) * d * 0.52;
          scene.add(rbox(w - 0.3, 0.03, 0.07, 0.015,
            mat(i % 2 ? 0x3c3c44 : 0x30303a, { metal: 0.1, rough: 0.92 }),
            cx, 0.665, zz));
        }
        // 腰枕
        scene.add(rbox(w * 0.36, 0.2, 0.2, 0.06,
          mat(0xb08a5a, { metal: 0.05, rough: 0.9 }), cx, 0.68, y + 0.42));
        // 床边地毯
        scene.add(box(w * 0.85, 0.02, 0.55,
          mat(0x4a3a2e, { metal: 0.05, rough: 0.98 }), cx, 0.015, y + d + 0.32));
      }
      if (f.t === 'counter') {
        const cz2 = y + 0.16;
        // 吊柜门 + 把手
        for (const sx of [-w * 0.24, w * 0.24]) {
          scene.add(box(w * 0.44, 0.5, 0.02,
            mat(0x2a2018, { metal: 0.3, rough: 0.55 }), cx + sx, 1.95, cz2 + 0.17));
          scene.add(box(0.26, 0.02, 0.02,
            mat(0xc8b090, { metal: 0.85, rough: 0.2 }), cx + sx, 1.7, cz2 + 0.19));
        }
        // 抽油烟机
        scene.add(box(w * 0.5, 0.08, 0.5,
          mat(0x8a9098, { metal: 0.85, rough: 0.25 }), cx, 2.02, cz));
        scene.add(box(w * 0.14, 0.5, 0.2,
          mat(0x6a7078, { metal: 0.7, rough: 0.3 }), cx, 2.28, y + 0.12));
        // 案板 + 水壶
        scene.add(rbox(0.36, 0.03, 0.24, 0.01,
          mat(0x8a6a4a, { metal: 0.05, rough: 0.85 }), cx - 0.32, 0.96, cz));
        scene.add(cyl(0.07, 0.06, 0.16,
          mat(0x2a2a2e, { metal: 0.6, rough: 0.35 }), cx + 0.3, 0.99, cz, 12));
        scene.add(cyl(0.02, 0.02, 0.12,
          mat(0x1a1a1a, { metal: 0.8, rough: 0.3 }), cx + 0.3, 1.08, cz, 8));
      }
      if (f.t === 'vanity') {
        // 毛巾杆 + 毛巾
        const bar = cyl(0.018, 0.018, 0.7,
          mat(0xc8d8e0, { metal: 0.9, rough: 0.2 }), x + w + 0.06, 1.15, cz, 8);
        bar.rotation.z = Math.PI / 2;
        scene.add(bar);
        scene.add(rbox(0.3, 0.42, 0.03, 0.01,
          mat(0xcfc8ba, { metal: 0.05, rough: 0.95 }), x + w + 0.08, 0.93, cz));
        // 地垫
        scene.add(box(w * 0.7, 0.02, 0.5,
          mat(0x6a6f74, { metal: 0.05, rough: 0.98 }), cx, 0.012, y + d + 0.38));
      }
      if (f.t === 'wardrobe') {
        scene.add(box(0.025, 1.75, 0.03,
          mat(0x0c1118, { metal: 0.4, rough: 0.5 }), cx, 1.0, y + d + 0.02));
        for (const sx of [cx - w * 0.22, cx + w * 0.22]) {
          scene.add(box(0.03, 0.26, 0.03,
            mat(0xc8b090, { metal: 0.85, rough: 0.2 }), sx, 1.1, y + d + 0.05));
        }
      }
    }
    // 她的房间壁灯
    for (const sz of [1.9, 3.5]) {
      scene.add(box(0.08, 0.14, 0.12,
        mat(0x2a2622, { metal: 0.6, rough: 0.4 }), 8.42, 1.92, sz));
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6),
        new THREE.MeshBasicMaterial({ color: 0xffd8a0 }));
      b.position.set(8.48, 1.84, sz);
      scene.add(b);
      const pl = new THREE.PointLight(0xffc880, 0.35, 3.2, 1.5);
      pl.position.set(8.5, 1.8, sz);
      scene.add(pl);
    }
    // 你房间壁灯
    for (const sz of [1.4, 2.9]) {
      scene.add(box(0.08, 0.14, 0.12,
        mat(0x2a2622, { metal: 0.6, rough: 0.4 }), 0.38, 1.92, sz));
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6),
        new THREE.MeshBasicMaterial({ color: 0xffd8a0 }));
      b.position.set(0.44, 1.84, sz);
      scene.add(b);
      const pl = new THREE.PointLight(0xffc880, 0.35, 3.2, 1.5);
      pl.position.set(0.46, 1.8, sz);
      scene.add(pl);
    }
    // 客厅落地灯
    const lampGroup = new THREE.Group();
    lampGroup.add(cyl(0.16, 0.18, 0.03, mat(0x1a1816, { metal: 0.7, rough: 0.4 }), 0, 0.015, 0, 16));
    lampGroup.add(cyl(0.018, 0.022, 1.5, mat(0x2a2622, { metal: 0.8, rough: 0.3 }), 0, 0.77, 0, 10));
    lampGroup.add(cyl(0.15, 0.19, 0.26,
      mat(0xe8d8b8, { metal: 0.05, rough: 0.8, emissive: 0x3a2a12, ei: 0.7 }), 0, 1.55, 0, 18));
    const pl = new THREE.PointLight(0xffc880, 0.55, 4.2, 1.5);
    pl.position.set(0, 1.5, 0);
    lampGroup.add(pl);
    lampGroup.position.set(3.95, 0, 6.9);
    scene.add(lampGroup);
  }
  // ------------------------------------------------------------ TA
  const herRing = new THREE.Mesh(
    new THREE.RingGeometry(0.42, 0.5, 48),
    new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.10, side: THREE.DoubleSide }));
  herRing.rotation.x = -Math.PI / 2;
  herRing.position.y = 0.03;
  scene.add(herRing);
  const herLight = new THREE.PointLight(0x67e8f9, 0.35, 3.2);
  herLight.position.set(6.3, 1.0, 4.4);
  scene.add(herLight);

  const herShadow = addContact(6.3, 4.4, 1.7, 1.05);
  herShadow.material = CONTACT_MAT.clone();
  herShadow.material.opacity = 0.55;

  const herGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: GLOW_TEX, color: 0x67e8f9, transparent: true, opacity: 0.045, depthWrite: false,
  }));
  herGlow.scale.set(1.8, 1.8, 1);
  herGlow.position.set(6.3, 0.95, 4.4);
  scene.add(herGlow);

  // ------------------------------------------------------------ Live2D
  let liveApp = null;
  let liveModel = null;
  let liveHolder = null;

  async function initLive2D() {
    if (!window.PIXI || !PIXI.live2d) return;
    try {
      liveApp = new PIXI.Application({
        view: liveCanvas,
        transparent: true,
        resizeTo: window,
        antialias: true,
        autoDensity: true,
        resolution: Math.min(1.35, window.devicePixelRatio || 1),
      });
      liveModel = await PIXI.live2d.Live2DModel.from('/static/live2d/companion/model3.json');
      liveHolder = new PIXI.Container();
      liveHolder.addChild(liveModel);
      liveApp.stage.addChild(liveHolder);
      liveCanvas.style.display = '';
      liveCanvas.style.visibility = 'visible';
      liveCanvas.style.opacity = '1';
    } catch (e) {
      console.warn('live2d load failed', e);
      liveCanvas.style.display = 'none';
    }
  }

  function project3(x, y, z) {
    const v = new THREE.Vector3(x, y, z).project(camera);
    const w = renderer.domElement.clientWidth;
    const h = renderer.domElement.clientHeight;
    return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h, z: v.z, visible: v.z < 1 };
  }

  const bubble = $('bubble');

  // 表情：跟情绪/痛经联动（复用视频通话那套参数）
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
  };
  const EXP_KEYS = ['PARAM_EXP1', 'PARAM_EXP2', 'PARAM_EXP3', 'PARAM_EXP4',
    'PARAM_EXP5', 'PARAM_EXP6', 'PARAM_EXP7', 'PARAM_EXP8',
    'Paramcol_1', 'Paramcol_2', 'Paramcol_3'];
  let lastExpr = '';

  function setExpression(name) {
    if (!liveModel) return;
    const core = liveModel.internalModel && liveModel.internalModel.coreModel;
    if (!core) return;
    for (const key of EXP_KEYS) {
      try { core.setParameterValueById(key, 0); } catch (e) { /* 模型没有这个参数 */ }
    }
    const p = EXPR_PARAMS[name];
    if (!p) return;
    for (const [k, v] of Object.entries(p)) {
      try { core.setParameterValueById(k, v); } catch (e) { /* 忽略 */ }
    }
  }

  function applyExpression() {
    if (!state || !liveModel) return;
    if (EXPR_LOCK) {
      if (EXPR_LOCK !== lastExpr) { lastExpr = EXPR_LOCK; setExpression(EXPR_LOCK); }
      return;
    }
    const m = state.mood || {};
    const emo = m.emotion || '';
    let name = '';
    if (m.period_pain > 0.35 || m.cramps > 0.35) name = 'exp08_worry';
    else if (m.anger > 0.4) name = 'exp06_xx';
    else if (m.sad > 0.4) name = 'exp08_worry';
    else if (emo.indexOf('羞') >= 0) name = 'exp04_blush';
    else if (emo.indexOf('惊') >= 0) name = 'exp05_oo';
    else if (m.valence > 0.35) name = 'exp04_blush';
    else if (m.valence > 0.15) name = 'exp01_mouth';
    if (name === lastExpr) return;
    lastExpr = name;
    setExpression(name);
  }

  function placeLive2D() {
    if (fp.on && fp.her) {
      // "她此刻"：镜头就是她的眼睛，不能再把她的立绘贴在画面上。
      // 注意用 opacity/visibility 隐藏，不用 display:none —— WebGL canvas 被
      // display:none 后再恢复，部分显卡会把画布顶部（头）裁掉。
      liveCanvas.style.opacity = '0';
      liveCanvas.style.visibility = 'hidden';
      if (herRing) herRing.visible = false;
      if (herShadow) herShadow.visible = false;
      if (herGlow) herGlow.visible = false;
      if (bubble) bubble.style.display = 'none';
      return;
    }
    if (!liveHolder || !liveModel || !state) return;
    // 其它第一人称房间 / 俯瞰：都要正常显示她的 Live2D
    liveCanvas.style.display = '';
    liveCanvas.style.visibility = 'visible';
    liveCanvas.style.opacity = '1';
    const [hx, hz] = herPos(now());
    const feet = project3(hx, 0.02, hz);
    const head = project3(hx, 1.72, hz);
    const pxH = Math.max(30, feet.y - head.y);
    let fpSeen = true;
    if (fp.on) {
      // 房间视角里，只有真的能看见她（中间没有墙/家具）才显示，
      // 否则 2D 立绘会隔墙浮在墙上。
      const chest = new THREE.Vector3(hx, 1.0, hz);
      const dir = chest.clone().sub(camera.position);
      const d = dir.length();
      if (d > 0.05) {
        dir.normalize();
        raycaster.set(camera.position, dir);
        raycaster.far = Math.max(0.05, d - 0.2);
        fpSeen = raycaster.intersectObjects(occluderMeshes, true).length === 0;
      }
    }
    const s = (pxH * 1.08) / liveModel.height;
    liveHolder.scale.set(s);
    liveHolder.x = feet.x - liveModel.width * s / 2;
    liveHolder.y = feet.y - liveModel.height * s;
    liveHolder.visible = fpSeen && feet.visible && feet.x > -300 && feet.x < window.innerWidth + 300;
    if (fp.on) {
      if (herRing) herRing.visible = false;
      if (herGlow) herGlow.visible = false;
      if (herShadow) herShadow.visible = fpSeen;
    }

    // 只淡脚踝以下：整张画布默认不透明，到脚踝附近才开始透明。
    // 不再用固定高度的 band —— 小窗口/远视角时 band 会把头也裁掉。
    const fadeTop = Math.max(0, feet.y - 26);
    const fadeBottom = Math.max(fadeTop + 1, feet.y + 6);
    // 2026-11-05：这几行以前每帧都写一遍（每秒 60 次 style + 字符串拼接 = 每帧一次样式重算）。
    // 只有脚的位置真的变了才重建 mask；其余属性是常量，设一次就够。
    const key = Math.round(fadeTop) + ':' + Math.round(fadeBottom);
    if (key !== maskKey) {
      maskKey = key;
      const fadeMid = fadeTop + (fadeBottom - fadeTop) * 0.55;
      const mask = `linear-gradient(to bottom, #000 0px, #000 ${fadeTop}px, rgba(0,0,0,.55) ${fadeMid}px, transparent ${fadeBottom}px, transparent 100%)`;
      liveCanvas.style.maskImage = mask;
      liveCanvas.style.webkitMaskImage = mask;
      liveCanvas.style.maskSize = '100% 100%';
      liveCanvas.style.webkitMaskSize = '100% 100%';
      liveCanvas.style.maskPosition = '0 0';
      liveCanvas.style.webkitMaskPosition = '0 0';
      liveCanvas.style.maskRepeat = 'no-repeat';
    }
    // 不再给整张全屏 Live2D 画布加 CSS drop-shadow：
    // 那会在每一帧对整屏做离屏滤镜，是本页最大的隐性开销之一。
    if (liveCanvas.style.filter !== 'none') liveCanvas.style.filter = 'none';

    herRing.position.set(hx, 0.03, hz);
    herLight.position.set(hx, 1.0, hz);
    herShadow.position.set(hx, 0.018, hz);
    herGlow.position.set(hx, 0.95, hz);

    const act = state.her.activity;
    if (act && (!fp.on || fpSeen)) {
      bubble.style.display = 'block';
      bubble.textContent = act;
      const b = project3(hx, 1.75, hz);
      bubble.style.left = b.x + 'px';
      bubble.style.top = (b.y - 8) + 'px';
    } else {
      bubble.style.display = 'none';
    }
  }

  // ------------------------------------------------------------ 视角控制
  function applyCamera() {
    if (fp.on) {
      camera.position.copy(fp.pos);
      camera.rotation.order = 'YXZ';
      camera.rotation.set(fp.pitch, fp.yaw, 0, 'YXZ');
      camera.updateMatrixWorld();
      return;
    }
    const t = view.target;
    const d = view.dist;
    camera.position.set(
      t.x + d * Math.cos(view.el) * Math.cos(view.az),
      t.y + d * Math.sin(view.el),
      t.z + d * Math.cos(view.el) * Math.sin(view.az));
    camera.lookAt(t);
  }

  function fpRoom(id) {
    if (!plan) return null;
    return plan.rooms.find(r => r.id === id) || plan.rooms[0];
  }

  function fpJump(roomId, useHer) {
    if (!plan) return;
    const room = fpRoom(roomId);
    if (!room) return;
    const [rx, rz, rw, rh] = room.rect;
    const cx = rx + rw / 2, cz = rz + rh / 2;
    let x, z, eye = 1.52, look = [cx, cz];

    if (useHer && state && state.her) {
      const p = herPos(now());
      x = p[0];
      z = p[1];
      eye = state.her.asleep ? 0.78 : 1.52;
      // 从床/椅子里往外挪一点，别让镜头卡在家具里
      const dx = cx - x, dz = cz - z;
      const dd = Math.hypot(dx, dz);
      if (dd > 0.01) { x += dx / dd * 0.45; z += dz / dd * 0.45; }
      look = [cx, cz];
    } else {
      const cfg = FP_VIEW[room.id];
      if (cfg) {
        x = cfg.pos[0];
        z = cfg.pos[1];
        look = cfg.look.slice();
      } else {
        const spots = (plan.spots && plan.spots[room.id]) || {};
        const p = spots.mid || spots.stand || spots.sofa || spots.desk || [cx, cz];
        x = p[0];
        z = p[1];
      }
      x = clamp(x, rx + 0.35, rx + rw - 0.35);
      z = clamp(z, rz + 0.35, rz + rh - 0.35);
      if (Math.hypot(look[0] - x, look[1] - z) < 0.4) look = [x, z - 1.2];
    }

    fp.pos.set(x, eye, z);
    fp.eye = eye;
    fp.room = room.id;
    fp.her = !!useHer;
    fp.yaw = Math.atan2(-(look[0] - x), -(look[1] - z));
    fp.pitch = 0;
    const tag = document.querySelector('#fpbar .tag');
    if (tag) {
      tag.textContent = useHer
        ? 'TA第一人称 · 她此刻'
        : 'TA第一人称 · ' + (room.name || room.id);
    }
    updateFpButtons();
    applyCamera();
    if (fp.on) syncFpAvatar();
  }

  function fpGallery(key) {
    const cfg = GALLERY_VIEWS[key];
    if (!cfg) return;
    if (!fp.on) setFP(true);
    fp.pos.set(cfg.pos[0], 1.52, cfg.pos[1]);
    fp.eye = 1.52;
    fp.room = 'gallery';
    fp.her = false;
    fp.yaw = Math.atan2(-(cfg.look[0] - cfg.pos[0]), -(cfg.look[1] - cfg.pos[1]));
    fp.pitch = 0;
    const tag = document.querySelector('#fpbar .tag');
    if (tag) tag.textContent = 'TA第一人称 · 画廊·' + cfg.label;
    updateFpButtons();
    applyCamera();
    syncFpAvatar();
  }

  function updateGalleryBar() {
    const bar = document.getElementById('gallerybar');
    if (!bar) return;
    bar.classList.toggle('show', fp.on && fp.room === 'gallery');
  }

  function syncFpAvatar() {
    if (!fp.on) return;
    const hide = fp.her;
    liveCanvas.style.display = '';
    liveCanvas.style.opacity = hide ? '0' : '1';
    liveCanvas.style.visibility = hide ? 'hidden' : 'visible';
    if (herRing) herRing.visible = false;
    if (herGlow) herGlow.visible = false;
    if (herShadow) herShadow.visible = !hide;
    if (hide) {
      if (bubble) bubble.style.display = 'none';
    } else {
      // 其它房间视角：让她在场景里出现；被墙挡住时 placeLive2D 会自己隐藏
      placeLive2D();
      if (liveApp) liveApp.render();
    }
  }

  function updateFpButtons() {
    document.querySelectorAll('#fpbar [data-room]').forEach(b => {
      b.classList.toggle('on', b.dataset.room === fp.room && !fp.her);
    });
    const hb = document.querySelector('#fpbar [data-fp="her"]');
    if (hb) hb.classList.toggle('on', fp.her);
    updateGalleryBar();
  }

  function bindFpEnter() {
    const el = $('fp-enter');
    if (el) el.onclick = (e) => { e.preventDefault(); setFP(true); };
  }

  function setFP(on, roomId, useHer) {
    if (!plan) return;
    if (on === fp.on) {
      if (on && roomId) fpJump(roomId, useHer !== false);
      return;
    }
    fp.on = on;
    if (on) {
      // 记住进来之前的俯瞰机位，出去时原样还回去，不要硬跳到另一个角度
      fp.savedTarget = view.target.clone();
      fp.savedDist = view.dist;
      fp.savedAz = view.az;
      fp.savedEl = view.el;
      fp.oldFov = camera.fov;
      camera.fov = 58;
      camera.updateProjectionMatrix();
      const rid = roomId || (state && state.her && state.her.room) || 'living';
      fpJump(rid, useHer !== false);
      document.body.classList.add('fp');
      $('fpbar').style.display = 'flex';
      const vb = $('viewbtn');
      if (vb) { vb.textContent = '俯瞰视角'; vb.classList.add('on'); }
      const sub = $('subhint');
      if (sub) sub.textContent = 'TA的第一人称 · 拖动看四周';
      $('hint').innerHTML = '拖动看四周 · 滚轮调视野 · 点房间切换 · <a href="#" id="fp-exit2">F 返回俯瞰</a>';
      $('hint').style.bottom = '58px';
      const ex = $('fp-exit2');
      if (ex) ex.onclick = (e) => { e.preventDefault(); setFP(false); };
      syncFpAvatar();
      roomLabels.forEach(s => { s.visible = false; });
      canvas.style.cursor = 'grab';
    } else {
      document.body.classList.remove('fp');
      $('fpbar').style.display = 'none';
      const vb = $('viewbtn');
      if (vb) { vb.textContent = '第一人称视角'; vb.classList.remove('on'); }
      $('hint').innerHTML = '拖拽平移 · 滚轮缩放 · <a href="#" id="fp-enter">TA第一人称</a> · <a href="/2d">回到 2D 平面图</a>';
      $('hint').style.bottom = '';
      bindFpEnter();
      const sub = $('subhint');
      if (sub) sub.textContent = '拖拽平移 · 滚轮缩放 · 遮挡自动透明';
      // 先隐藏一帧，等相机/遮罩切回俯瞰后再显示，避免拿第一人称的旧遮罩画她
      // 仍然不用 display:none，只切 opacity/visibility，避免 WebGL 画布裁头
      liveCanvas.style.display = '';
      liveCanvas.style.opacity = '0';
      liveCanvas.style.visibility = 'hidden';
      if (herRing) herRing.visible = true;
      if (herShadow) herShadow.visible = true;
      if (herGlow) herGlow.visible = true;
      roomLabels.forEach(s => { s.visible = true; });
      holeU.uRadius.value = 0.5;
      camera.fov = fp.oldFov || 42;
      camera.updateProjectionMatrix();
      if (fp.savedTarget) {
        panGoal.copy(fp.savedTarget);
        panSmooth.copy(fp.savedTarget);
        view.target.copy(fp.savedTarget);
        view.dist = fp.savedDist;
        view.az = fp.savedAz;
        view.el = fp.savedEl;
      } else {
        panGoal.set(6.3, 0, 4.85);
        panSmooth.copy(panGoal);
        view.dist = 20;
      }
      applyCamera();
      liveCanvas.style.opacity = '0';
      requestAnimationFrame(() => {
        liveCanvas.style.display = '';
        liveCanvas.style.visibility = 'visible';
        liveCanvas.style.opacity = '1';
        placeLive2D();
        if (liveApp) {
          liveApp.renderer.resize(window.innerWidth, window.innerHeight);
          liveApp.render();
        }
      });
    }
  }

  function bindGalleryBar() {
    const bar = document.getElementById('gallerybar');
    if (!bar) return;
    bar.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-gview]');
      if (!b) return;
      fpGallery(b.dataset.gview);
    });
  }

  function bindFpBar() {
    const bar = $('fpbar');
    if (!bar) return;
    bar.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.gview) { fpGallery(b.dataset.gview); return; }
      if (b.dataset.fp === 'exit') { setFP(false); return; }
      if (b.dataset.fp === 'her') {
        const rid = (state && state.her && state.her.room) || fp.room || 'her_room';
        fpJump(rid, true);
        return;
      }
      if (b.dataset.room) fpJump(b.dataset.room, false);
    });
  }

  let dragging = false;
  let lastX = 0, lastY = 0;
  let pinch = 0;
  let touchLast = null;
  const panGoal = view.target.clone();
  const panSmooth = view.target.clone();

  function screenToGround(cx, cy) {
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((cx - rect.left) / rect.width) * 2 - 1,
      -((cy - rect.top) / rect.height) * 2 + 1);
    const rc = new THREE.Raycaster();
    rc.setFromCamera(ndc, camera);
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const p = new THREE.Vector3();
    return rc.ray.intersectPlane(plane, p) ? p : null;
  }

  function onDown(e) {
    if (e.button !== 0) return;
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
    canvas.style.cursor = 'grabbing';
    canvas.setPointerCapture(e.pointerId);
  }

  function onMove(e) {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    if (fp.on) {
      fp.yaw -= dx * 0.0032;
      fp.pitch = clamp(fp.pitch - dy * 0.0026, -1.15, 1.15);
      return;
    }
    const h = canvas.clientHeight || window.innerHeight || 1;
    const wpp = (2 * view.dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / h;
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    right.y = 0;
    right.normalize();
    const fwd = new THREE.Vector3().subVectors(panGoal, camera.position);
    fwd.y = 0;
    fwd.normalize();
    panGoal.addScaledVector(right, -dx * wpp);
    panGoal.addScaledVector(fwd, dy * wpp);
    panGoal.x = clamp(panGoal.x, 1.0, 11.6);
    panGoal.z = clamp(panGoal.z, 0.3, 9.5);
  }

  function onUp() {
    dragging = false;
    canvas.style.cursor = 'grab';
  }

  function onWheel(e) {
    e.preventDefault();
    if (fp.on) {
      camera.fov = clamp(camera.fov + e.deltaY * 0.03, 32, 78);
      camera.updateProjectionMatrix();
      return;
    }
    const before = screenToGround(e.clientX, e.clientY);
    view.dist = clamp(view.dist * Math.exp(e.deltaY * 0.0012), 6.5, 34);
    view.target.copy(panSmooth);
    applyCamera();
    if (before) {
      const after = screenToGround(e.clientX, e.clientY);
      if (after) {
        panGoal.add(before.sub(after));
        panGoal.x = clamp(panGoal.x, 1.0, 11.6);
        panGoal.z = clamp(panGoal.z, 0.3, 9.5);
        panSmooth.copy(panGoal);
      }
    }
  }

  // 双指缩放
  function onTouchMove(e) {
    if (fp.on) {
      if (e.touches.length === 1) {
        const t = e.touches[0];
        if (touchLast) {
          fp.yaw -= (t.clientX - touchLast.x) * 0.004;
          fp.pitch = clamp(fp.pitch - (t.clientY - touchLast.y) * 0.003, -1.15, 1.15);
        }
        touchLast = { x: t.clientX, y: t.clientY };
        e.preventDefault();
      }
      return;
    }
    if (e.touches.length === 2) {
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY);
      if (pinch) view.dist = clamp(view.dist * (pinch / d), 6.5, 34);
      pinch = d;
      e.preventDefault();
    }
  }

  // ------------------------------------------------------------ 遮挡淡出
  let fadeTimer = 0;
  const tmpBox = new THREE.Box3();
  const tmpV = new THREE.Vector3();

  function updateFade() {
    if (fp.on) {
      // 第一人称镜头就在她身上：关闭"挖洞看TA"的透明孔，否则墙会被挖出一个圆
      holeU.uRadius.value = 0.0;
      holeU.uCamPos.value.copy(camera.position);
      return;
    }
    holeU.uRadius.value = 0.5;
    const [hx, hz] = herPos(now());
    holeU.uHerPos.value.set(hx, 0.95, hz);
    holeU.uCamPos.value.copy(camera.position);
  }

  // ------------------------------------------------------------ 光照
  function updateLight(t) {
    const h = HOUR_LOCK != null ? HOUR_LOCK : hourOf(t);
    let sunColor, sunI, ambI, lampI;
    if (h < 5 || h >= 22) {
      sunColor = 0x7fa8e0; sunI = 0.15; ambI = 0.55; lampI = 1.0;
    } else if (h < 7) {
      sunColor = 0xffb07a; sunI = 0.5; ambI = 0.6; lampI = 0.5;
    } else if (h < 10) {
      sunColor = 0xd8ecff; sunI = 0.8; ambI = 0.55; lampI = 0;
    } else if (h < 15) {
      sunColor = 0xeaf6ff; sunI = 0.9; ambI = 0.6; lampI = 0;
    } else if (h < 18) {
      sunColor = 0xfff0dc; sunI = 0.8; ambI = 0.55; lampI = 0;
    } else if (h < 20) {
      sunColor = 0xff9a6a; sunI = 0.6; ambI = 0.6; lampI = 0.8;
    } else {
      sunColor = 0x8fb8f0; sunI = 0.18; ambI = 0.55; lampI = 1.0;
    }
    sun.color.setHex(sunColor);
    sun.intensity = sunI;
    // 2026-11-05：她睡着了就把灯关掉（数据来自 /api/house 的 her.asleep）。
    // 以前夜里灯一直亮着，"家里有人"的感觉是假的。
    const sheAsleep = !!(state && state.her && state.her.asleep);
    if (sheAsleep) lampI = 0;
    const ang = (h / 24) * Math.PI * 2;
    sun.position.set(6 + Math.cos(ang) * 10, 8 + Math.sin(ang) * 6, 4 + Math.sin(ang) * 8);
    amb.intensity = ambI * 0.32;
    hemi.intensity = 0.14 + ambI * 0.1;
    const day = h >= 7 && h < 18;
    for (const l of lamps) l.intensity = lampI * 1.2;
    for (const l of roomLights) {
      l.intensity = 0.06 + lampI * 0.32;
      l.color.setHex(day ? 0xfff0dc : 0xffd7a8);
    }
    keySpot.intensity = 0.7 + lampI * 0.7;
    for (const s of windowSpots) s.intensity = day ? 2.2 : 2.6;
    if (SHADOW_TEST) {
      amb.intensity = 0;
      hemi.intensity = 0;
      sun.intensity = 0;
      keySpot.intensity = 3;
      roomSpot.intensity = 3;
      for (const l of roomLights) l.intensity = 0;
      for (const l of lamps) l.intensity = 0;
    }
    if (day !== lastWindowDay) {
      lastWindowDay = day;
      renderer.shadowMap.needsUpdate = true;
      for (const w of windowMats) {
        w.mat.map = day ? w.day : w.night;
        w.mat.needsUpdate = true;
      }
      for (const c of cityMats) {
        c.mat.map = day ? c.day : c.night;
        c.mat.needsUpdate = true;
      }
    }
    if (scene.background && scene.background.setHex) {
      scene.background.setHex(h >= 20 || h < 6 ? 0x04070b : 0x0a1018);
    }
  }

  // ------------------------------------------------------------ 数据 / 面板
  function modeName(h) {
    if (h < 5) return '深夜';
    if (h < 7) return '清晨';
    if (h < 11) return '上午';
    if (h < 14) return '中午';
    if (h < 17) return '下午';
    if (h < 20) return '傍晚';
    return '夜里';
  }

  function updateHud() {
    if (!state) return;
    $('where').textContent = state.her.room_name || '——';
    $('activity').textContent = state.her.activity || '——';
    $('emotion').textContent = state.mood.emotion || '平静';
    if ($('fridge')) {
      const n = Number(state.mood && state.mood.fridge || 0);
      $('fridge').textContent = n > 0 ? `${n} 份` : '空';
    }
    const d = new Date(now() * 1000);
    $('clock').textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    $('mode').textContent = modeName(hourOf(now()));
  }


  // ---------------- 2026-11-12 房间动作 / 点哪去哪 / 电视 / 画质
  async function postHouse(path, body) {
    try {
      const r = await fetch(path, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) });
      return await r.json();
    } catch (e) { return { ok: false }; }
  }

  function say(text, ms) {
    const el = document.getElementById('bubble');
    if (!el) return;
    el.textContent = text;
    el.style.display = 'block';
    if (houseSayTimer) clearTimeout(houseSayTimer);
    houseSayTimer = setTimeout(() => { el.style.display = 'none'; }, ms || 3200);
  }
  let houseSayTimer = null;

  const ACT_TEXT = {
    pet: '摸头', feed: '喂饭', water: '倒水', play: '陪玩', wake: '叫醒',
  };

  document.querySelectorAll('#actbar [data-act]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'lamp') {
        const cur = state && state.env ? state.env.lamp : true;
        const d = await postHouse('/api/house/action', { type: cur ? 'lamp_off' : 'lamp_on' });
        btn.classList.toggle('on', !cur);
        say(!cur ? '灯打开了' : '灯关上了');
        if (d && d.house) state = d.house;
        return;
      }
      const d = await postHouse('/api/house/action', { type: act });
      if (d && d.msg) say(d.msg);
      if (d && d.house) state = d.house;
    });
  });

  // 点地面 = 让她走过去
  const _ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const _hit = new THREE.Vector3();
  const _ray = new THREE.Raycaster();
  let _downX = 0, _downY = 0, _dragged = false;
  canvas.addEventListener('pointerdown', (e) => { _downX = e.clientX; _downY = e.clientY; _dragged = false; });
  canvas.addEventListener('pointermove', (e) => {
    if (Math.abs(e.clientX - _downX) + Math.abs(e.clientY - _downY) > 6) _dragged = true;
  });
  canvas.addEventListener('pointerup', async (e) => {
    if (_dragged || (typeof fp !== 'undefined' && fp.on)) return;
    const rect = canvas.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    _ray.setFromCamera({ x: nx, y: ny }, camera);
    if (!_ray.ray.intersectPlane(_ground, _hit)) return;
    const d = await postHouse('/api/house/move', { x: _hit.x, z: _hit.z, note: '你点到哪，我走到哪' });
    if (d && d.house) { state = d.house; say('我过去啦'); }
  });

  // 电视：把浏览器标签页投到房间
  const tvBtn = document.getElementById('tvbtn');
  const tvModal = document.getElementById('tvmodal');
  const tvVideo = document.getElementById('tvvideo');
  let tvStream = null;
  if (tvBtn) {
    tvBtn.addEventListener('click', async () => {
      if (tvStream) { tvModal.classList.add('show'); return; }
      try {
        tvStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
        tvVideo.srcObject = tvStream;
        tvModal.classList.add('show');
        tvBtn.classList.add('on');
        tvStream.getVideoTracks()[0].addEventListener('ended', () => {
          tvStream = null; tvVideo.srcObject = null; tvModal.classList.remove('show'); tvBtn.classList.remove('on');
          if (tvAutoTimer) { clearInterval(tvAutoTimer); tvAutoTimer = null; }
        });
        postHouse('/api/house/action', { type: 'tv_on' });
        say('一起看');
        if (tvAutoTimer) clearInterval(tvAutoTimer);
        tvAutoTimer = setInterval(() => lookAtTV(false), 45000);
      } catch (e) { say('没有选屏幕'); }
    });
  }
  const tvLook = document.getElementById('tvlook');
  const tvCanvas = document.createElement('canvas');
  async function lookAtTV(manual) {
    if (!tvStream || !tvVideo.videoWidth) { if (manual) say('电视还没画面'); return; }
    try {
      tvCanvas.width = Math.min(960, tvVideo.videoWidth);
      tvCanvas.height = Math.round(tvCanvas.width * tvVideo.videoHeight / tvVideo.videoWidth);
      tvCanvas.getContext('2d').drawImage(tvVideo, 0, 0, tvCanvas.width, tvCanvas.height);
      const blob = await new Promise((res) => tvCanvas.toBlob(res, 'image/jpeg', 0.72));
      if (!blob) return;
      const r = await fetch('/api/house/tvframe', { method: 'POST', body: blob,
        headers: { 'Content-Type': 'image/jpeg' } });
      const d = await r.json();
      if (d && d.desc) { say(d.desc.slice(0, 80), 6000); if (d.house) state = d.house; }
      else if (manual) say('这次没看清');
    } catch (e) { if (manual) say('看一眼失败'); }
  }
  let tvAutoTimer = null;
  if (tvLook) tvLook.addEventListener('click', () => lookAtTV(true));
  const tvClose = document.getElementById('tvclose');
  if (tvClose) {
    tvClose.addEventListener('click', () => {
      if (tvStream) tvStream.getTracks().forEach((t) => t.stop());
      tvStream = null; tvVideo.srcObject = null;
      tvModal.classList.remove('show'); tvBtn.classList.remove('on');
      if (tvAutoTimer) { clearInterval(tvAutoTimer); tvAutoTimer = null; }
      postHouse('/api/house/action', { type: 'tv_off' });
    });
  }

  // 画质三档
  const qBtn = document.getElementById('qbtn');
  const QLEVELS = [
    { name: '低', dpr: 0.8, ssao: false, bloom: false },
    { name: '中', dpr: 1.15, ssao: false, bloom: false },
    { name: '高', dpr: 1.5, ssao: true, bloom: true },
  ];
  let qIdx = 1;
  function applyQLevel() {
    const q = QLEVELS[qIdx];
    QUALITY.dprCap = q.dpr;
    QUALITY.dpr = Math.min(q.dpr, window.devicePixelRatio || 1);
    QUALITY.ssao = q.ssao;
    QUALITY.bloom = q.bloom;
    applyQuality();
    if (qBtn) qBtn.textContent = '画质：' + q.name;
  }
  if (qBtn) qBtn.addEventListener('click', () => { qIdx = (qIdx + 1) % QLEVELS.length; applyQLevel(); });
  applyQLevel();

  async function poll() {
    try {
      const r = await fetch('/api/house', { cache: 'no-store' });
      const data = await r.json();
      state = data;
      skew = data.now - Date.now() / 1000;
      updateHud();
      applyExpression();
    } catch (e) { /* keep last */ }
  }

  // ------------------------------------------------------------ resize / 主循环
  function resize() {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    resizePost();
    if (liveApp) liveApp.renderer.resize(w, h);
  }

  let last = performance.now();
  let hudTimer = 0;
  let lastShadowHour = -1;
  let qTime = 0;
  let qFrames = 0;
  let goodWin = 0;
  let maskKey = '';

  function adaptQuality(dt) {
    qTime += dt;
    qFrames++;
    if (qTime < 1.5) return;
    const fps = qFrames / qTime;
    qTime = 0;
    qFrames = 0;
    if (fps < 44 && QUALITY.dpr > 0.9) {
      QUALITY.dpr = Math.max(0.9, QUALITY.dpr - 0.15);
      applyQuality();
    } else if (fps < 36 && QUALITY.ssao) {
      QUALITY.ssao = false;
      applyQuality();
    } else if (fps < 30 && QUALITY.bloom) {
      QUALITY.bloom = false;
      applyQuality();
    }
    // 2026-11-05：降下去要能升回来。以前只会往下调，一次卡顿之后永远糊在 0.9。
    if (fps > 55) { goodWin++; } else { goodWin = 0; }
    if (goodWin >= 4 && QUALITY.dpr < QUALITY.dprCap - 0.01) {
      QUALITY.dpr = Math.min(QUALITY.dprCap, QUALITY.dpr + 0.1);
      applyQuality();
      goodWin = 0;
    }
  }

  function frame(ts) {
    const dt = Math.min(0.05, (ts - last) / 1000);
    last = ts;
    const damp = 1 - Math.pow(0.0004, dt);
    panSmooth.lerp(panGoal, damp);
    view.target.copy(panSmooth);
    applyCamera();
    // 2026-11-05：去掉每帧手动的 scene.updateMatrixWorld()——renderer.render() 内部会做一遍，
    // 手动再跑一次等于整个场景图每帧遍历两趟。camera 手动更新保留（下面 project3/raycast 要用）。
    camera.updateMatrixWorld();
    updateFade(dt);
    const hNow = hourOf(now());
    updateLight(now());
    // 阴影只在太阳真的转过一段时才重画：0.01h ≈ 36 秒的太阳移动，肉眼完全看不出。
    // 以前是每 5 秒无条件重画 4 张阴影图（2048²+1024²+512²+512²），等于每 5 秒一次 GPU 尖峰。
    if (renderer.shadowMap.enabled &&
        (lastShadowHour < 0 || Math.abs(hNow - lastShadowHour) > 0.01)) {
      renderer.shadowMap.needsUpdate = true;
      lastShadowHour = hNow;
    }
    if (composer) composer.render(); else renderer.render(scene, camera);
    placeLive2D();
    if (liveApp) liveApp.render();
    adaptQuality(dt);
    hudTimer += dt;
    if (hudTimer > 0.5) {
      hudTimer = 0;
      updateHud();
    }
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------ init
  async function init() {
    if (qs.get('noshadow') === '1') renderer.shadowMap.enabled = false;
    plan = await fetch('/plan.json', { cache: 'no-store' }).then(r => r.json());
    buildFloors();
    buildWalls();
    buildWindowViews();
    buildWindowLights();
    buildWindows();
    buildDoors();
    buildFurniture();
    loadFurnitureModels();
    buildProps();
    buildDetails();
    buildFineDetails();
    buildBathroomFix();
    buildRoomLabels();
    addGalleryFrame(4.55, 1.62, 0.28, 0.86, 0.86, 0, '/static/art/qq_avatar.jpg');
    addArt(1.7, 1.7, 0.28, 0.9, 0.62, 0);
    addArt(8.32, 1.7, 4.12, 0.9, 0.62, Math.PI / 2);
    await buildGallery();
    resize();
    applyCamera();
    if (qs.get('post') === '1') {
      QUALITY.ssao = true;
      QUALITY.bloom = true;
      initPostprocessing();
    }
    applyQuality();
    renderer.shadowMap.needsUpdate = true;

    window.addEventListener('resize', resize);
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.style.cursor = 'grab';
    canvas.addEventListener('dblclick', () => {
      if (fp.on) { fp.pitch = 0; return; }
      panGoal.set(6.3, 0, 4.45);
      panSmooth.copy(panGoal);
      view.dist = 18;
    });
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('touchmove', onTouchMove, { passive: false });
    canvas.addEventListener('touchend', () => { pinch = 0; touchLast = null; });

    bindFpEnter();
    bindFpBar();
    bindGalleryBar();
    const vb = $('viewbtn');
    if (vb) vb.onclick = () => setFP(!fp.on);
    window.addEventListener('keydown', (e) => {
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        setFP(!fp.on);
      } else if (e.key === 'Escape' && fp.on) {
        setFP(false);
      }
    });

    await poll();
    setInterval(poll, 2000);
    setInterval(() => { $('clock').textContent = new Date(now() * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }, 1000);

    await initLive2D();
    if (qs.get('fp') === '1' || qs.get('view') === 'first') {
      const rid = qs.get('room') || null;
      setFP(true, rid, !rid);
    }
    if (qs.get('autox') === '1') {
      // 调试用：进第一人称 2.5 秒后自动退回俯瞰，方便截图检查
      setTimeout(() => { if (fp.on) setFP(false); }, 2500);
    }
    $('loading').classList.add('hide');
    requestAnimationFrame(frame);
  }

  init().catch(err => {
    console.error(err);
    $('loading').textContent = '3D 初始化失败：' + err.message;
  });
})();
