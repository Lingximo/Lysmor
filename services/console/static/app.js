/* 控制台 · 骨架逻辑：只读聚合展示 */
(function () {
  "use strict";

  var token = new URLSearchParams(location.search).get("t") || "";
  var svcBox = document.getElementById("services");
  var summaryEl = document.getElementById("summary");
  var actEl = document.getElementById("activities");
  var clockEl = document.getElementById("clock");

  function refresh() {
    fetch("/api/overview", { headers: { "X-Gate-Token": token } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        clockEl.textContent = new Date(d.t * 1000).toLocaleTimeString();
        renderServices(d.services || []);
        renderSummary(d);
        renderActivities(d.activities || []);
      })
      .catch(function (e) {
        clockEl.textContent = "加载失败：" + e.message;
      });
  }

  function renderServices(services) {
    svcBox.innerHTML = "";
    services.forEach(function (s) {
      var a = document.createElement("a");
      a.className = "svc";
      a.href = (s.url || "") + (s.page || "/") + "?t=" + encodeURIComponent(token);
      a.target = "_blank";
      a.innerHTML =
        '<div class="row"><span class="dot ' + (s.up ? "up" : "down") + '"></span>' +
        '<span class="name">' + s.name + "</span></div>" +
        '<div class="state">' + (s.up ? "运行中" : "未启动") + "</div>";
      svcBox.appendChild(a);
    });
  }

  function renderSummary(d) {
    var html = "";
    if (d.life && d.life.vitals) {
      var labels = d.life.labels || {};
      Object.keys(d.life.vitals).forEach(function (k) {
        html += (labels[k] || k) + " " + Math.round(d.life.vitals[k] * 100) + "%<br>";
      });
    } else {
      html += '<span class="muted">生命面板未启动</span>';
    }
    if (d.memory_count !== null) {
      html += "<br>最近记忆：" + d.memory_count + " 条";
    }
    summaryEl.innerHTML = html;
  }

  function renderActivities(acts) {
    actEl.innerHTML = "";
    if (!acts.length) {
      actEl.innerHTML = '<li class="muted">暂无动态</li>';
      return;
    }
    acts.forEach(function (a) {
      var li = document.createElement("li");
      li.innerHTML = '<span class="t">' + (a.t || "") + "</span>" + (a.text || "");
      actEl.appendChild(li);
    });
  }

  refresh();
  setInterval(refresh, 5000);
})();
