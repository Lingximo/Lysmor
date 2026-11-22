/* 控制台 · 骨架逻辑：只读聚合展示 */
(function () {
  "use strict";

  var i18n = window.LysmorI18n;
  var t = i18n.t;
  i18n.applyText(document);

  var token = new URLSearchParams(location.search).get("t") || "";
  var svcBox = document.getElementById("services");
  var summaryEl = document.getElementById("summary");
  var actEl = document.getElementById("activities");
  var clockEl = document.getElementById("clock");

  function refresh() {
    fetch("/api/overview", { headers: { "X-Gate-Token": token, "Accept-Language": i18n.language() } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        clockEl.textContent = new Date(d.t * 1000).toLocaleTimeString(i18n.language());
        renderServices(d.services || []);
        renderSummary(d);
        renderActivities(d.activities || []);
      })
      .catch(function (e) {
        clockEl.textContent = t("services.loadFailed", { error: e.message });
      });
  }

  function renderServices(services) {
    svcBox.innerHTML = "";
    services.forEach(function (s) {
      var a = document.createElement("a");
      a.className = "svc";
      var url = new URL((s.url || "") + (s.page || "/"), location.href);
      url.searchParams.set("t", token);
      url.searchParams.set("lang", i18n.language());
      a.href = url.href;
      a.target = "_blank";
      var row = document.createElement("div");
      row.className = "row";
      var dot = document.createElement("span");
      dot.className = "dot " + (s.up ? "up" : "down");
      var name = document.createElement("span");
      name.className = "name";
      name.textContent = s.name || "";
      row.appendChild(dot);
      row.appendChild(name);
      var state = document.createElement("div");
      state.className = "state";
      state.textContent = s.up ? t("services.console.running") : t("services.console.stopped");
      a.appendChild(row);
      a.appendChild(state);
      svcBox.appendChild(a);
    });
  }

  function renderSummary(d) {
    summaryEl.textContent = "";
    if (d.life && d.life.vitals) {
      var labels = d.life.labels || {};
      Object.keys(d.life.vitals).forEach(function (k) {
        summaryEl.appendChild(document.createTextNode((t("services.vitals." + k) === "services.vitals." + k ? (labels[k] || k) : t("services.vitals." + k)) + " " + Math.round(d.life.vitals[k] * 100) + "%"));
        summaryEl.appendChild(document.createElement("br"));
      });
    } else {
      var empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = t("services.console.lifeOffline");
      summaryEl.appendChild(empty);
    }
    if (d.memory_count !== null) {
      summaryEl.appendChild(document.createElement("br"));
      summaryEl.appendChild(document.createTextNode(t("services.console.memories", { count: d.memory_count })));
    }
  }

  function renderActivities(acts) {
    actEl.innerHTML = "";
    if (!acts.length) {
      actEl.innerHTML = '<li class="muted">' + t("services.console.noActivity") + '</li>';
      return;
    }
    acts.forEach(function (a) {
      var li = document.createElement("li");
      var time = document.createElement("span");
      time.className = "t";
      time.textContent = a.t || "";
      li.appendChild(time);
      li.appendChild(document.createTextNode(a.text || ""));
      actEl.appendChild(li);
    });
  }

  addEventListener("lysmor:languagechange", refresh);
  refresh();
  setInterval(refresh, 5000);
})();
