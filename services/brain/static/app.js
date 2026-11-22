/* 记忆星图 · 骨架逻辑：螺旋布局 + 主题聚类着色 + 缩放/平移/悬停 */
(function () {
  "use strict";

  var i18n = window.LysmorI18n;
  var t = i18n.t;
  i18n.applyText(document);

  var token = new URLSearchParams(location.search).get("t") || "";
  var canvas = document.getElementById("sky");
  var ctx = canvas.getContext("2d");
  var tip = document.getElementById("tip");
  var countEl = document.getElementById("count");
  var legendEl = document.getElementById("legend");

  var nodes = [], links = [], pos = {};
  var view = { x: 0, y: 0, scale: 1 };
  var dragging = false, lastX = 0, lastY = 0, hoverId = null;

  var PALETTE = ["#4da3ff", "#5ad67a", "#ffb454", "#b58cff", "#ff7a9e",
                 "#ffd94d", "#4dd8d0", "#ff8f5a"];

  function topicColor(topic) {
    var h = 0;
    for (var i = 0; i < topic.length; i++) { h = (h * 31 + topic.charCodeAt(i)) >>> 0; }
    return PALETTE[h % PALETTE.length];
  }

  function layout() {
    pos = {};
    var golden = Math.PI * (3 - Math.sqrt(5));
    nodes.forEach(function (n, i) {
      var r = 40 + Math.sqrt(i) * 26;
      var a = i * golden;
      pos[n.id] = { x: Math.cos(a) * r, y: Math.sin(a) * r };
    });
  }

  function resize() {
    canvas.width = innerWidth * devicePixelRatio;
    canvas.height = innerHeight * devicePixelRatio;
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    draw();
  }

  function toScreen(p) {
    return {
      x: (p.x + view.x) * view.scale + innerWidth / 2,
      y: (p.y + view.y) * view.scale + innerHeight / 2
    };
  }

  function draw() {
    var w = innerWidth, h = innerHeight;
    ctx.clearRect(0, 0, w, h);
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    // 连线
    ctx.lineWidth = 1;
    links.forEach(function (l) {
      var a = pos[l.source], b = pos[l.target];
      if (!a || !b) { return; }
      var sa = toScreen(a), sb = toScreen(b);
      ctx.strokeStyle = "rgba(124,143,168,.25)";
      ctx.beginPath();
      ctx.moveTo(sa.x, sa.y);
      ctx.lineTo(sb.x, sb.y);
      ctx.stroke();
    });

    // 节点
    nodes.forEach(function (n) {
      var p = pos[n.id];
      if (!p) { return; }
      var s = toScreen(p);
      var r = (2.2 + n.importance * 4) * view.scale;
      var color = topicColor(n.topic || "");
      var glow = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r * 3.5);
      glow.addColorStop(0, color + "55");
      glow.addColorStop(1, "transparent");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(s.x, s.y, r * 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
      ctx.fill();
      if (hoverId === n.id) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r + 3, 0, Math.PI * 2);
        ctx.stroke();
      }
    });
  }

  function pick(x, y) {
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var p = pos[n.id];
      if (!p) { continue; }
      var s = toScreen(p);
      var r = (2.2 + n.importance * 4) * view.scale + 4;
      var dx = x - s.x, dy = y - s.y;
      if (dx * dx + dy * dy <= r * r) { return n; }
    }
    return null;
  }

  function renderLegend() {
    var topics = [];
    nodes.forEach(function (n) {
      if (topics.indexOf(n.topic) < 0) { topics.push(n.topic); }
    });
    legendEl.innerHTML = "";
    topics.forEach(function (t) {
      var item = document.createElement("span");
      item.className = "item";
      var dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = topicColor(t || "");
      item.appendChild(dot);
      item.appendChild(document.createTextNode(t || i18n.t("services.brain.other")));
      legendEl.appendChild(item);
    });
  }

  function load() {
    fetch("/api/memories", { headers: { "X-Gate-Token": token, "Accept-Language": i18n.language() } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        nodes = d.nodes || [];
        links = d.links || [];
        layout();
        renderLegend();
        countEl.textContent = t("services.brain.count", { count: nodes.length });
        draw();
      })
      .catch(function (e) {
        countEl.textContent = t("services.loadFailed", { error: e.message });
      });
  }

  canvas.addEventListener("wheel", function (e) {
    e.preventDefault();
    var f = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    view.scale = Math.max(0.3, Math.min(4, view.scale * f));
    draw();
  }, { passive: false });

  canvas.addEventListener("mousedown", function (e) {
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
  });
  addEventListener("mouseup", function () { dragging = false; });
  canvas.addEventListener("mousemove", function (e) {
    if (dragging) {
      view.x += (e.clientX - lastX) / view.scale;
      view.y += (e.clientY - lastY) / view.scale;
      lastX = e.clientX;
      lastY = e.clientY;
      draw();
      return;
    }
    var n = pick(e.clientX, e.clientY);
    hoverId = n ? n.id : null;
    draw();
    if (n) {
      tip.hidden = false;
      tip.textContent = n.summary || "";
      var topic = document.createElement("div");
      topic.className = "topic";
      topic.textContent = (n.topic || t("services.brain.other")) + " · " +
        t("services.brain.importance", { value: Math.round((n.importance || 0) * 100) }) + " · " + (n.t || "");
      tip.appendChild(topic);
      tip.style.left = Math.min(e.clientX + 14, innerWidth - 280) + "px";
      tip.style.top = Math.min(e.clientY + 14, innerHeight - 90) + "px";
    } else {
      tip.hidden = true;
    }
  });

  addEventListener("lysmor:languagechange", function () {
    countEl.textContent = t("services.brain.count", { count: nodes.length });
    renderLegend();
    tip.hidden = true;
    draw();
  });
  addEventListener("resize", resize);
  resize();
  load();
})();
