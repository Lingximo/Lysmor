(function () {
  const tr = (key, vars) => window.LysmorI18n.t(key, vars);
  const $ = (id) => document.getElementById(id);

  function pct(v) {
    v = Number(v) || 0;
    return Math.round(Math.max(0, Math.min(1, v)) * 100) + "%";
  }

  function render(s) {
    const panel = $("sick-panel");
    if (!panel) return;
    const sick = !!s.sick;
    const recovering = s.sick_state === "恢复中";
    panel.classList.toggle("sick-on", sick && !recovering);
    panel.classList.toggle("sick-recover", recovering);

    $("sick-tag").textContent = s.sick_state === "恢复中" ? tr("panels.recovering") : (s.sick_state || "—");
    $("sick-state").textContent = !sick ? tr("panels.healthy") : (recovering ? tr("panels.recovering") : tr("panels.sick"));
    $("sick-cause").textContent = sick ? (s.sick_cause_label || "") : "";

    $("sick-temp").textContent = (Number(s.core_temp) || 0).toFixed(1) + "℃";
    $("sick-pain").textContent = pct(s.pain);
    $("sick-cyt").textContent = pct(s.cytokines);

    const rec = Math.round((Number(s.sick_recovery) || 0) * 100);
    $("sick-bar").style.width = rec + "%";
    $("sick-recovery").textContent = sick ? tr("panels.recovery_prefix") + rec + "%" : "";

    const list = $("sick-plan");
    list.innerHTML = "";
    const plan = Array.isArray(s.sick_plan) ? s.sick_plan : [];
    if (!sick) {
      const li = document.createElement("li");
      li.textContent = tr("panels.healthy_plan");
      list.appendChild(li);
    } else if (!plan.length) {
      const li = document.createElement("li");
      li.textContent = tr("panels.rest_plan");
      list.appendChild(li);
    } else {
      plan.forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        list.appendChild(li);
      });
    }

    const hint = $("sick-hint");
    if (!sick) {
      hint.textContent = tr("panels.sick_hint");
    } else if (s.sick_treatment_label) {
      hint.textContent = tr("panels.activity_prefix") + s.sick_treatment_label +
        tr("panels.treatment_suffix");
    } else {
      hint.textContent = tr("panels.no_treatment");
    }
  }

  function refresh() {
    fetch("/api/state", { cache: "no-store" })
      .then((r) => r.json())
      .then(render)
      .catch(() => {});
  }

  refresh();
  setInterval(refresh, 3000);
})();
