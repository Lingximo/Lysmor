(function () {
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

    $("sick-tag").textContent = s.sick_state || "—";
    $("sick-state").textContent = !sick ? "健康" : (recovering ? "恢复中" : "生病中");
    $("sick-cause").textContent = sick ? (s.sick_cause_label || "") : "";

    $("sick-temp").textContent = (Number(s.core_temp) || 0).toFixed(1) + "℃";
    $("sick-pain").textContent = pct(s.pain);
    $("sick-cyt").textContent = pct(s.cytokines);

    const rec = Math.round((Number(s.sick_recovery) || 0) * 100);
    $("sick-bar").style.width = rec + "%";
    $("sick-recovery").textContent = sick ? "恢复 " + rec + "%" : "";

    const list = $("sick-plan");
    list.innerHTML = "";
    const plan = Array.isArray(s.sick_plan) ? s.sick_plan : [];
    if (!sick) {
      const li = document.createElement("li");
      li.textContent = "没有生病，正常吃饭睡觉就好。";
      list.appendChild(li);
    } else if (!plan.length) {
      const li = document.createElement("li");
      li.textContent = "先休息、多喝水，观察一下。";
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
      hint.textContent = "发烧 / 疼痛 / 吃坏肚子都会在这里显示。";
    } else if (s.sick_treatment_label) {
      hint.textContent = "正在" + s.sick_treatment_label +
        "；治疗中恢复会明显加快，撑不住就去医院。";
    } else {
      hint.textContent = "还没有开始治疗。可以说“吃药 / 喝热水 / 睡一觉 / 去医院”，她就会按这个养病。";
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
