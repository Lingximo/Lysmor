(() => {
  const canvas = document.getElementById('live2d');
  const wrap = canvas && canvas.parentElement;
  if (!canvas || !wrap || !window.PIXI || !PIXI.live2d) return;

  const app = new PIXI.Application({
    view: canvas,
    transparent: true,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
  });

  let model = null;
  let holder = null;
  let gazeX = 0;
  let gazeY = 0;
  let gazeTime = 0;

  function fit() {
    if (!model || !holder) return;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    if (!w || !h) return;
    app.renderer.resize(w, h);
    const scale = Math.min((w * 0.98) / model.width, (h * 0.98) / model.height);
    holder.scale.set(scale);
    holder.x = (w - model.width * scale) / 2;
    holder.y = h - model.height * scale - h * 0.01;
  }

  window.addEventListener('mousemove', e => {
    const r = canvas.getBoundingClientRect();
    gazeX = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 0.55)));
    gazeY = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height * 0.55)));
    gazeTime = performance.now();
  });

  (async () => {
    try {
      model = await PIXI.live2d.Live2DModel.from('/live2d/companion/model3.json', {
        autoInteract: true,
      });
      holder = new PIXI.Container();
      holder.addChild(model);
      app.stage.addChild(holder);
      fit();
      window.addEventListener('resize', fit);
      const core = model.internalModel?.coreModel;
      window.__companionRegisterCore?.(core);
      app.ticker.add(() => {
        const t = performance.now() / 1000;
        try {
          if (performance.now() - gazeTime > 450) {
            gazeX += (0 - gazeX) * 0.24;
            gazeY += (0 - gazeY) * 0.24;
          }
          core?.setParameterValueById('ParamEyeBallX', gazeX * 0.95);
          core?.setParameterValueById('ParamEyeBallY', -gazeY * 0.85);
          core?.setParameterValueById('ParamAngleX', Math.sin(t * 0.7) * 2 + gazeX * 9);
          core?.setParameterValueById('ParamAngleY', Math.sin(t * 0.9 + 0.7) * 2 - gazeY * 7);
          core?.setParameterValueById('ParamBodyAngleX', Math.sin(t * 0.45) * 1.5 + gazeX * 2.5);
          core?.setParameterValueById('ParamBreath', (Math.sin(t * 1.25) + 1) * 0.5);
        } catch (e) {}
      });
    } catch (e) {
      console.error('dashboard Live2D failed', e);
    }
  })();
})();

