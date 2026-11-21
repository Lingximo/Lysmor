/* 画廊 · 骨架逻辑：网格陈列 + 详情 */
(function () {
  "use strict";

  var token = new URLSearchParams(location.search).get("t") || "";
  var grid = document.getElementById("grid");
  var countEl = document.getElementById("count");
  var detail = document.getElementById("detail");

  function load() {
    fetch("/api/works", { headers: { "X-Gate-Token": token } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        var works = d.works || [];
        countEl.textContent = works.length + " 件作品";
        grid.innerHTML = "";
        if (!works.length) {
          grid.innerHTML = '<div class="empty">还没有作品。画出来的东西会出现在这里。</div>';
          return;
        }
        works.forEach(function (w) {
          var card = document.createElement("div");
          card.className = "work";
          card.innerHTML =
            '<img src="/media/' + w.image + '" alt="" loading="lazy">' +
            '<div class="meta"><div class="title">' + w.title + '</div>' +
            '<div class="date">' + (w.t || "") + "</div></div>";
          card.addEventListener("click", function () { open(w); });
          grid.appendChild(card);
        });
      })
      .catch(function (e) {
        countEl.textContent = "加载失败：" + e.message;
      });
  }

  function open(w) {
    document.getElementById("detail-img").src = "/media/" + w.image;
    document.getElementById("detail-title").textContent = w.title;
    document.getElementById("detail-note").textContent = w.note || "";
    document.getElementById("detail-date").textContent = w.t || "";
    detail.hidden = false;
  }

  document.getElementById("detail-close").addEventListener("click", function () {
    detail.hidden = true;
  });
  detail.addEventListener("click", function (e) {
    if (e.target === detail) { detail.hidden = true; }
  });

  load();
})();
