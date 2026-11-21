/* 顶部状态条 + 左下遥测块：纯读 window.__endoState，不额外请求。 */
(() => {
  const t0 = performance.now();
  const $ = id => document.getElementById(id);

  function pad(n) { return String(n).padStart(2, '0'); }

  function tick() {
    const s = window.__endoState || {};
    document.body.classList.toggle('asleep', !!s.asleep);
    document.body.classList.toggle('napping', !!(s.asleep && s.sleep_kind === 'nap'));
    const el = $('hud-emotion');
    if (el) {
      const lvl = s.emotion_level || '—';
      const nap = s.asleep && s.sleep_kind === 'nap';
      el.textContent = s.asleep ? (nap ? '午睡中 · ' + lvl : '睡梦中 · ' + lvl) : '情绪 ' + lvl;
      el.classList.toggle('hot', /峰|恐惧|害怕|哭/.test(lvl));
    }
    const clock = $('hud-time');
    if (clock) {
      const d = new Date();
      clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }
    const up = $('hud-uptime');
    if (up) {
      const sec = Math.floor((performance.now() - t0) / 1000);
      up.textContent = `${pad(Math.floor(sec / 60))}:${pad(sec % 60)}`;
    }
    const ce = $('core-energy');
    if (ce) {
      const e = Number(s.energy), v = Number(s.valence), d = Number(s.dominance);
      ce.textContent = Number.isFinite(e) ? Math.round(e * 100) + '%' : '—';
      const cv = $('core-valence'), cd = $('core-dominance');
      if (cv) cv.textContent = Number.isFinite(v) ? v.toFixed(2) : '—';
      if (cd) cd.textContent = Number.isFinite(d) ? Math.round(d * 100) + '%' : '—';
      const ca = $('core-anger');
      if (ca) {
        const a = Number(s.anger);
        ca.textContent = Number.isFinite(a) ? Math.round(a * 100) + '%' : '—';
      }
    }
    const cyc = $('hud-cycle');
    if (cyc) {
      const names = { menstrual: '经期', follicular: '卵泡期', ovulation: '排卵期', luteal: '黄体期', premenstrual: '经前' };
      const ph = names[s.cycle_phase] || '周期';
      cyc.textContent = s.cycle_day ? `${ph} D${s.cycle_day}` : '周期 —';
      cyc.classList.toggle('hot', s.cycle_phase === 'menstrual' || s.cycle_phase === 'premenstrual');
    }
    const tag = $('cycle-tag');
    if (tag) {
      const names = { menstrual: '经期', follicular: '卵泡期', ovulation: '排卵期', luteal: '黄体期', premenstrual: '经前期' };
      tag.textContent = s.cycle_day ? `${names[s.cycle_phase] || ''} D${s.cycle_day}` : '—';
    }
    const rate = $('hud-rate');
    if (rate) {
      const e = Number(s.energy);
      rate.textContent = Number.isFinite(e) ? `刷新 ${(3 + (1 - e) * 2).toFixed(1)}s` : '刷新 —';
    }
    setTimeout(tick, 900);
  }
  tick();
})();
