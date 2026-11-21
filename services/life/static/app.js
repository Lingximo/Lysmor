/* 生命面板 · 骨架逻辑（只读展示） */
(function () {
  "use strict";

  var token = new URLSearchParams(location.search).get("t") || "";
  var cardsBox = document.getElementById("cards");
  var clockEl = document.getElementById("clock");
  var canvas = document.getElementById("chart");
  var ctx = canvas.getContext("2d");

  var COLORS = ["#ffb454", "#5ad67a", "#4da3ff", "#b58cff", "#ff7a9e", "#ffd94d"];
  var trend = [];
  var LABELS = {};

  function api(path) {
    return fetch(path, { headers: { "X-Gate-Token": token } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      });
  }

  function renderCards(state) {
    cardsBox.innerHTML = "";
    var keys = Object.keys(state.vitals);
    keys.forEach(function (k, i) {
      var v = state.vitals[k];
      var card = document.createElement("div");
      card.className = "card";
      card.title = state.notes[k] || "";
      var pct = Math.round(v * 100);
      card.innerHTML =
        '<div class="label">' + state.labels[k] + "</div>" +
        '<div class="value">' + pct + "%</div>" +
        '<div class="bar"><div></div></div>';
      var fill = card.querySelector(".bar > div");
      fill.style.width = pct + "%";
      fill.style.background = COLORS[i % COLORS.length];
      cardsBox.appendChild(card);
    });
  }

  function renderChart() {
    var w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (trend.length < 2) { return; }
    var keys = Object.keys(trend[0].v);
    var pad = 34;
    var plotW = w - pad, plotH = h - pad;
    var t0 = trend[0].t, t1 = trend[trend.length - 1].t || t0 + 1;
    keys.forEach(function (k, i) {
      ctx.strokeStyle = COLORS[i % COLORS.length];
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      trend.forEach(function (p, j) {
        var x = pad + (p.t - t0) / (t1 - t0) * (plotW - 8);
        var y = pad + (1 - p.v[k]) * (plotH - 8);
        if (j === 0) { ctx.moveTo(x, y); } else { ctx.lineTo(x, y); }
      });
      ctx.stroke();
    });
    // 图例
    ctx.font = "12px system-ui";
    keys.forEach(function (k, i) {
      ctx.fillStyle = COLORS[i % COLORS.length];
      ctx.fillText(LABELS[k] || k, pad + i * 64, 14);
    });
  }

  function refresh() {
    api("/api/state").then(function (state) {
      renderCards(state);
      LABELS = state.labels || {};
      clockEl.textContent = new Date(state.t * 1000).toLocaleTimeString();
    }).catch(function (e) {
      clockEl.textContent = "连接失败：" + e.message;
    }).then(function () {
      return api("/api/trend");
    }).then(function (d) {
      trend = d.trend || [];
      renderChart();
    }).catch(function () {});
  }

  refresh();
  setInterval(refresh, 3000);
})();
