/* 画廊 · 骨架逻辑：网格陈列 + 详情 */
(function () {
  "use strict";

  var i18n = window.LysmorI18n;
  var t = i18n.t;
  i18n.applyText(document);

  var token = new URLSearchParams(location.search).get("t") || "";
  var grid = document.getElementById("grid");
  var countEl = document.getElementById("count");
  var detail = document.getElementById("detail");

  function load() {
    fetch("/api/works", { headers: { "X-Gate-Token": token, "Accept-Language": i18n.language() } })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (d) {
        var works = d.works || [];
        countEl.textContent = t("services.gallery.count", { count: works.length });
        grid.innerHTML = "";
        if (!works.length) {
          grid.innerHTML = '<div class="empty">' + t("services.gallery.empty") + '</div>';
          return;
        }
        works.forEach(function (w) {
          var card = document.createElement("div");
          card.className = "work";
          var image = document.createElement("img");
          image.src = "/media/" + encodeURIComponent(w.image);
          image.alt = "";
          image.loading = "lazy";
          var meta = document.createElement("div");
          meta.className = "meta";
          var title = document.createElement("div");
          title.className = "title";
          title.textContent = w.title || "";
          var date = document.createElement("div");
          date.className = "date";
          date.textContent = w.t || "";
          meta.appendChild(title);
          meta.appendChild(date);
          card.appendChild(image);
          card.appendChild(meta);
          card.addEventListener("click", function () { open(w); });
          grid.appendChild(card);
        });
      })
      .catch(function (e) {
        countEl.textContent = t("services.loadFailed", { error: e.message });
      });
  }

  function open(w) {
    document.getElementById("detail-img").src = "/media/" + encodeURIComponent(w.image);
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

  addEventListener("lysmor:languagechange", load);
  load();
})();
