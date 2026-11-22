/* 大平层 · 骨架逻辑：等距投影 3D 房间（Canvas 2D，无第三方库） */
(function () {
  "use strict";

  var i18n = window.LysmorI18n;
  var t = i18n.t;
  i18n.applyText(document);

  var token = new URLSearchParams(location.search).get("t") || "";
  var canvas = document.getElementById("room");
  var ctx = canvas.getContext("2d");
  var tip = document.getElementById("tip");

  var house = null;
  var view = { angle: 0.9, zoom: 46, cx: 0, cy: 0 };
  var dragging = false, lastX = 0, lastY = 0;
  var furniture = [];

  function project(x, y, z) {
    var cx = house ? house.room.w / 2 : 4;
    var cy = house ? house.room.d / 2 : 3;
    var dx = x - cx, dy = y - cy;
    var cos = Math.cos(view.angle), sin = Math.sin(view.angle);
    var rx = dx * cos - dy * sin;
    var ry = dx * sin + dy * cos;
    return {
      x: innerWidth / 2 + (rx - ry) * 0.866 * view.zoom,
      y: innerHeight / 2 + (rx + ry) * 0.5 * view.zoom - z * view.zoom
    };
  }

  function shade(hex, f) {
    var n = parseInt(hex.slice(1), 16);
    var r = Math.min(255, Math.round(((n >> 16) & 255) * f));
    var g = Math.min(255, Math.round(((n >> 8) & 255) * f));
    var b = Math.min(255, Math.round((n & 255) * f));
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function box(x, y, w, d, h, color) {
    var p0 = project(x, y, 0), p1 = project(x + w, y, 0),
        p2 = project(x + w, y + d, 0), p3 = project(x, y + d, 0);
    var t0 = project(x, y, h), t1 = project(x + w, y, h),
        t2 = project(x + w, y + d, h), t3 = project(x, y + d, h);

    // 顶面
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(t0.x, t0.y); ctx.lineTo(t1.x, t1.y);
    ctx.lineTo(t2.x, t2.y); ctx.lineTo(t3.x, t3.y);
    ctx.closePath(); ctx.fill();
    // 两个可见侧面（用暗一点的色调）
    ctx.fillStyle = shade(color, 0.62);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y); ctx.lineTo(t1.x, t1.y);
    ctx.lineTo(t2.x, t2.y); ctx.lineTo(p2.x, p2.y);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = shade(color, 0.45);
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y); ctx.lineTo(t0.x, t0.y);
    ctx.lineTo(t3.x, t3.y); ctx.lineTo(p3.x, p3.y);
    ctx.closePath(); ctx.fill();
  }

  function draw() {
    var w = innerWidth, h = innerHeight;
    ctx.clearRect(0, 0, w, h);
    if (!house) { return; }

    var rw = house.room.w, rd = house.room.d;
    // 地板
    var f = [project(0, 0, 0), project(rw, 0, 0), project(rw, rd, 0), project(0, rd, 0)];
    ctx.fillStyle = "#111a2c";
    ctx.beginPath();
    ctx.moveTo(f[0].x, f[0].y); ctx.lineTo(f[1].x, f[1].y);
    ctx.lineTo(f[2].x, f[2].y); ctx.lineTo(f[3].x, f[3].y);
    ctx.closePath(); ctx.fill();
    // 地板网格
    ctx.strokeStyle = "rgba(124,143,168,.12)";
    ctx.lineWidth = 1;
    for (var gx = 0; gx <= rw; gx++) {
      var a = project(gx, 0, 0), b = project(gx, rd, 0);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (var gy = 0; gy <= rd; gy++) {
      var c = project(0, gy, 0), d2 = project(rw, gy, 0);
      ctx.beginPath(); ctx.moveTo(c.x, c.y); ctx.lineTo(d2.x, d2.y); ctx.stroke();
    }
    // 家具（按离视角远近排序再画，避免遮挡顺序错乱）
    furniture.slice().sort(function (a, b) {
      return (a.x + a.y) - (b.x + b.y);
    }).forEach(function (it) {
      box(it.x, it.y, it.w, it.d, it.h, it.color || "#4da3ff");
    });
    // 居住者（通用光点占位，形象素材由使用者自备）
    var oc = house.occupant || {};
    var op = project(oc.x || 4, oc.y || 3, 0.9);
    var glow = ctx.createRadialGradient(op.x, op.y, 0, op.x, op.y, 22);
    glow.addColorStop(0, "#ffd94dcc");
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(op.x, op.y, 22, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#ffd94d";
    ctx.beginPath(); ctx.arc(op.x, op.y, 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#7c8fa8";
    ctx.font = "12px system-ui";
    ctx.fillText(oc.name || t("services.house.occupant"), op.x - 8, op.y - 12);
  }

  function pickFurniture(mx, my) {
    for (var i = furniture.length - 1; i >= 0; i--) {
      var it = furniture[i];
      var c = project(it.x + it.w / 2, it.y + it.d / 2, 0);
      var dx = mx - c.x, dy = my - c.y;
      if (dx * dx + dy * dy < 30 * 30) { return it; }
    }
    return null;
  }

  function load() {
    fetch("/api/house", { headers: { "X-Gate-Token": token, "Accept-Language": i18n.language() } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        house = d;
        furniture = d.furniture || [];
        draw();
      })
      .catch(function (e) {
        document.getElementById("title").textContent = t("services.loadFailed", { error: e.message });
      });
  }

  canvas.addEventListener("wheel", function (e) {
    e.preventDefault();
    view.zoom = Math.max(20, Math.min(120, view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    draw();
  }, { passive: false });

  canvas.addEventListener("mousedown", function (e) {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
  });
  addEventListener("mouseup", function () { dragging = false; });
  canvas.addEventListener("mousemove", function (e) {
    if (dragging) {
      view.angle += (e.clientX - lastX) * 0.008;
      lastX = e.clientX;
      lastY = e.clientY;
      draw();
      tip.hidden = true;
      return;
    }
    var it = pickFurniture(e.clientX, e.clientY);
    if (it) {
      tip.hidden = false;
      tip.textContent = it.name || "";
      var note = document.createElement("div");
      note.className = "note";
      note.textContent = it.note || "";
      tip.appendChild(note);
      tip.style.left = Math.min(e.clientX + 14, innerWidth - 260) + "px";
      tip.style.top = Math.min(e.clientY + 14, innerHeight - 80) + "px";
    } else {
      tip.hidden = true;
    }
  });

  addEventListener("lysmor:languagechange", function () { tip.hidden = true; draw(); });
  addEventListener("resize", draw);
  load();
})();
