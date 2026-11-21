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
  });

  let model = null;
  let holder = null;
  let fitScale = 1;

  window.setGaze = (x, y) => {
    window.__gazeX = Math.max(-1, Math.min(1, Number(x) || 0));
    window.__gazeY = Math.max(-1, Math.min(1, Number(y) || 0));
    window.__gazeTime = performance.now();
  };

  function fit() {
    if (!model || !holder) return;
    const w = app.renderer.width / app.renderer.resolution;
    const h = app.renderer.height / app.renderer.resolution;
    if (compact) {
      fitScale = Math.min(w / model.width, h / model.height) * 2.0;
      holder.scale.set(fitScale);
      holder.x = (w - model.width * fitScale) / 2;
      holder.y = -model.height * fitScale * 0.02;
    } else {
      fitScale = Math.min((w * 0.92) / model.width, (h * 0.90) / model.height);
      holder.scale.set(fitScale);
      holder.x = (w - model.width * fitScale) / 2;
      holder.y = h - model.height * fitScale - h * 0.04;
    }
  }

  (async () => {
    try {
      model = await PIXI.live2d.Live2DModel.from('/static/live2d/companion/model3.json', {
        autoInteract: !compact,
      });
      holder = new PIXI.Container();
      holder.addChild(model);
      app.stage.addChild(holder);

      fit();
      window.addEventListener('resize', fit);
      window.__live2dReady = true;
      document.getElementById('avatar-picker')?.style.setProperty('display', 'none');
      const core = model.internalModel?.coreModel;
      window.__companionRegisterCore?.(core);
      app.ticker.add(() => {
        const t = performance.now() / 1000;
        try {
          let gx = Number(window.__gazeX || 0);
          let gy = Number(window.__gazeY || 0);
          if (performance.now() - Number(window.__gazeTime || 0) > 450) {
            gx += (0 - gx) * 0.24;
            gy += (0 - gy) * 0.24;
            window.__gazeX = gx;
            window.__gazeY = gy;
          }
          core?.setParameterValueById('ParamEyeBallX', gx * 0.95);
          core?.setParameterValueById('ParamEyeBallY', -gy * 0.85);
          core?.setParameterValueById('ParamAngleX', Math.sin(t * 0.7) * 2 + gx * 9);
          core?.setParameterValueById('ParamAngleY', Math.sin(t * 0.9 + 0.7) * 2 - gy * 7);
          core?.setParameterValueById('ParamBodyAngleX', Math.sin(t * 0.45) * 1.5 + gx * 2.5);
          core?.setParameterValueById('ParamBreath', (Math.sin(t * 1.25) + 1) * 0.5);
        } catch (e) {}
      });
      console.log('Live2D ready', model.width, model.height);
    } catch (e) {
      console.error('Live2D load failed', e);
    }
  })();
})();





