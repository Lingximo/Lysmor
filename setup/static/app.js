/* 配置向导 · 逻辑 */
(function () {
  "use strict";

  var i18n = window.LysmorI18n;
  var t = i18n.t;
  function apiFetch(url, options) {
    options = options || {};
    options.headers = Object.assign({}, options.headers || {}, { "Accept-Language": i18n.language() });
    return fetch(url, options);
  }
  function esc(value) { return String(value).replace(/[&<>"']/g, function (c) { return {"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]; }); }

  var $ = function (id) { return document.getElementById(id); };
  var PORT_NAMES = [
    ["chat", t("setup.dynamic.1")], ["gallery", t("setup.dynamic.2")], ["video", t("setup.dynamic.3")], ["video_https", t("setup.dynamic.4")],
    ["life", t("setup.dynamic.5")], ["brain", t("setup.dynamic.6")], ["house", t("setup.dynamic.7")], ["qr", t("setup.dynamic.8")],
    ["hub", t("setup.dynamic.9")], ["hands", t("setup.dynamic.10")], ["bot", t("setup.dynamic.11")], ["panel", t("setup.dynamic.12")],
    ["napcat", t("setup.dynamic.13")]
  ];

  var VOICE_SLOTS = [t("setup.voice.first"), t("setup.voice.second"), t("setup.voice.third"), t("setup.voice.fourth"), t("setup.voice.fifth")];
  var FACE_SLOTS = [["up", t("setup.face.up")], ["down", t("setup.face.down")], ["left", t("setup.face.left")], ["right", t("setup.face.right")], ["front", t("setup.face.front")]];

  // ---------- 声纹：浏览器录音 ----------
  var voiceData = {};
  var recorder = null, currentSlot = null;

  function buildEnroll() {
    var vb = $("voice_slots");
    vb.innerHTML = "";
    VOICE_SLOTS.forEach(function (label, i) {
      var slot = "v" + (i + 1);
      var div = document.createElement("div");
      div.className = "slot";
      div.innerHTML = "<span class='slot-name' data-i18n='setup.voice." + ["first", "second", "third", "fourth", "fifth"][i] + "'>" + label + "</span>" +
        "<button class='mini-btn' data-act='rec' data-slot='" + slot + "'>" + t("setup.record") + "</button>" +
        "<button class='mini-btn' data-act='play' data-slot='" + slot + "'>" + t("setup.play") + "</button>" +
        "<span class='slot-st' data-slot='" + slot + "'></span>";
      vb.appendChild(div);
    });
    var fb = $("face_slots");
    fb.innerHTML = "";
    FACE_SLOTS.forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var div = document.createElement("div");
      div.className = "slot";
      div.innerHTML = "<span class='slot-name' data-i18n='setup.face." + key + "'>" + label + "</span>" +
        "<input type='file' accept='image/*' class='face-input' data-slot='" + key + "'>" +
        "<span class='slot-st' data-slot='" + key + "'></span>";
      fb.appendChild(div);
    });
  }

  function setSlotState(slot, text) {
    document.querySelectorAll(".slot-st[data-slot='" + slot + "']").forEach(function (el) {
      el.textContent = text;
    });
  }

  function startRec(slot) {
    if (recorder) { return; }
    currentSlot = slot;
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      recorder = new MediaRecorder(stream);
      var chunks = [];
      recorder.ondataavailable = function (e) { chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        recorder = null;
        var blob = new Blob(chunks, { type: "audio/webm" });
        var reader = new FileReader();
        reader.onload = function () {
          voiceData[slot] = reader.result;
          setSlotState(slot, t("setup.recorded"));
        };
        reader.readAsDataURL(blob);
      };
      recorder.start();
      setSlotState(slot, t("setup.recording"));
      var recBtn = document.querySelector("[data-act='rec'][data-slot='" + slot + "']");
      recBtn.textContent = t("setup.stop");
    }).catch(function (e) {
      setSlotState(slot, t("setup.dynamic.14") + e.message);
    });
  }

  function stopRec() {
    if (recorder) { recorder.stop(); }
  }

  function playSlot(slot) {
    var d = voiceData[slot];
    if (!d) { return; }
    var a = new Audio(d);
    a.play();
  }

  document.addEventListener("click", function (e) {
    var target = e.target;
    if (target.dataset && target.dataset.act === "rec") {
      if (recorder && currentSlot === target.dataset.slot) { stopRec(); }
      else { startRec(target.dataset.slot); }
    } else if (target.dataset && target.dataset.act === "play") {
      playSlot(target.dataset.slot);
    }
  });

  document.addEventListener("change", function (e) {
    if (e.target.classList && e.target.classList.contains("face-input")) {
      var slot = e.target.dataset.slot;
      var f = e.target.files[0];
      if (!f) { return; }
      var reader = new FileReader();
      reader.onload = function () {
        faceData[slot] = reader.result;
        setSlotState(slot, t("setup.selected"));
      };
      reader.readAsDataURL(f);
    }
  });
  var faceData = {};

  // ---------- 表单 ----------
  function buildPortInputs(defaults) {
    var box = $("ports");
    box.innerHTML = "";
    PORT_NAMES.forEach(function (pair) {
      var key = pair[0], name = pair[1];
      var lab = document.createElement("label");
      lab.innerHTML = name + " <input type='number' data-key='" + key + "' value='" + (defaults.ports[key] || "") + "'>";
      box.appendChild(lab);
    });
  }

  function refreshDefaults() {
    apiFetch("/api/defaults").then(function (r) { return r.json(); }).then(function (d) {
      $("data_dir").value = d.data_dir || "";
      $("user_dir").value = d.user_dir || "";
      $("user_qq").value = d.qq || "";
      $("bot_instance").value = d.bot_instance || "";
      $("bot_panel").value = d.bot_panel || 8012;
      $("base_url").value = (d.llm && d.llm.base_url) || "";
      $("model").value = (d.llm && d.llm.model) || "deepseek-chat";
      buildPortInputs(d);
      // 自动探测 AstrBot
      apiFetch("/api/autodetect").then(function (r2) { return r2.json(); }).then(function (det) {
        if (det.bot_instance) {
          $("bot_instance").value = det.bot_instance;
          $("bot_panel").value = det.bot_panel;
        }
      }).catch(function () {});
    }).catch(function (e) {
      $("quick_result").hidden = false;
      $("quick_result").innerHTML = t("setup.dynamic.15") + esc(e.message);
    });
  }

  function runCheck(done) {
    var box = $("checkresult");
    box.hidden = false;
    box.innerHTML = t("setup.checking");
    apiFetch("/api/check").then(function (r) { return r.json(); }).then(function (d) {
      var items = d.checks || [];
      var html = "";
      var fail = 0, warn = 0;
      items.forEach(function (c) {
        var label = { ok: t("setup.check.pass"), warn: t("setup.check.warn"), fail: t("setup.check.fail"), info: t("setup.check.info") }[c.level] || c.level;
        if (c.level === "fail") { fail++; }
        if (c.level === "warn") { warn++; }
        html += '<div class="item"><span class="mark ' + esc(c.level) + '">' + label + "</span>" +
          "<span><b>" + esc(c.name) + "</b> <span class='detail'>" + esc(c.detail) + "</span></span></div>";
        if (esc(c.hint)) { html += '<div class="hint">→ ' + esc(c.hint) + "</div>"; }
      });
      if (fail === 0 && warn === 0) {
        html = t("setup.dynamic.18") + html;
      }
      box.innerHTML = html;
      if (done) { done(fail, warn); }
    }).catch(function (e) {
      box.innerHTML = t("setup.dynamic.16") + esc(e.message);
      if (done) { done(1, 0); }
    });
  }

  function autoCheckOnOpen() {
    var auto = new URLSearchParams(location.search).get("auto");
    if (auto !== "check") { return; }
    runCheck(function (fail, warn) {
      if (fail === 0 && warn === 0) {
        apiFetch("/api/huburl").then(function (r) { return r.json(); }).then(function (d) {
          if (!d.url) { return; }
          $("checkresult").innerHTML += t("setup.dynamic.19");
          setTimeout(function () { location.href = d.url; }, 1500);
        });
      }
    });
  }

  // ---------- 自动装机 ----------
  $("envsetup").addEventListener("click", function () {
    var box = $("env_result");
    box.hidden = false;
    box.innerHTML = t("setup.installing");
    apiFetch("/api/envsetup", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      var html = "";
      (d.results || []).forEach(function (it) {
        html += "<div class='item'><span class='mark " + (it.ok ? "ok" : "fail") + "'>" +
          (it.ok ? "✅" : "❌") + "</span><span><b>" + esc(it.name) + "</b> <span class='detail'>" + esc(it.detail) + "</span></span></div>";
      });
      box.innerHTML = html;
    }).catch(function (e) {
      box.innerHTML = t("setup.dynamic.17") + esc(e.message);
    });
  });

  // ---------- 一键自动配置（账号匹配） ----------
  $("autoconfig").addEventListener("click", function () {
    var btn = $("autoconfig");
    btn.disabled = true;
    btn.textContent = t("setup.configuring");
    apiFetch("/api/autoconfig", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: i18n.language(),
        fish_qq: $("fish_qq").value,
        user_qq: $("user_qq").value,
        api_key: $("api_key").value,
        voice: voiceData,
        faces: faceData
      })
    }).then(function (r) { return r.json(); }).then(function (d) {
      var box = $("quick_result");
      box.hidden = false;
      if (d.ok) {
        var det = d.detected || {};
        var en = d.enroll || {};
        box.className = "";
        box.innerHTML =
          t("setup.dynamic.20") +
          t("setup.dynamic.21") + d.files + t("setup.dynamic.22") + d.repl + t("setup.dynamic.23") +
          (esc(det.bot_instance) ? t("setup.dynamic.24") + esc(det.bot_instance) + "<br>" : "") +
          t("setup.dynamic.25") + esc(d.astrbot || "") + "<br>" +
          t("setup.dynamic.26") + esc(en.note || t("setup.no_samples")) + "<br><br>" +
          t("setup.dynamic.27");
      } else {
        box.className = "err";
        box.innerHTML = t("setup.dynamic.28") + esc(d.error || t("setup.unknown_error"));
      }
      runCheck();
    }).catch(function (e) {
      var box = $("quick_result");
      box.hidden = false;
      box.className = "err";
      box.innerHTML = t("setup.dynamic.29") + esc(e.message);
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = t("setup.text.14");
    });
  });

  // ---------- 素材导入 ----------
  var IMP_INPUTS = { live2d: "imp_live2d", stickers: "imp_stickers", background: "imp_background", pet: "imp_pet" };

  function readAll(files) {
    return Promise.all(Array.prototype.map.call(files, function (f) {
      return new Promise(function (resolve) {
        var reader = new FileReader();
        reader.onload = function () {
          resolve({ name: f.webkitRelativePath || f.name, data: reader.result });
        };
        reader.onerror = function () { resolve(null); };
        reader.readAsDataURL(f);
      });
    })).then(function (list) { return list.filter(Boolean); });
  }

  document.querySelectorAll("[data-imp]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var kind = btn.dataset.imp;
      var input = document.getElementById(IMP_INPUTS[kind]);
      var st = document.getElementById("st_" + kind);
      var files = input.files;
      if (!files || !files.length) { st.textContent = t("setup.select_files"); return; }
      st.textContent = t("setup.reading");
      readAll(files).then(function (list) {
        st.textContent = t("setup.dynamic.30") + list.length + t("setup.dynamic.31");
        return apiFetch("/api/import_asset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: kind, files: list })
        });
      }).then(function (r) { return r.json(); }).then(function (d) {
        st.textContent = d.ok ? t("setup.dynamic.32") + d.count + t("setup.dynamic.33") : "❌ " + (d.error || t("setup.failed"));
      }).catch(function (e) {
        st.textContent = "❌ " + e.message;
      });
    });
  });

  // ---------- 详细设置 ----------
  $("adv-toggle").addEventListener("click", function () {
    var adv = $("advanced");
    var show = adv.hidden;
    adv.hidden = !show;
    $("adv-toggle").textContent = show ? t("setup.advanced.collapse") : t("setup.text.30");
  });

  $("gen").addEventListener("click", function () {
    var chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    var s = "";
    for (var i = 0; i < 18; i++) { s += chars[Math.floor(Math.random() * chars.length)]; }
    $("gate_token").value = s;
  });

  document.getElementById("check").addEventListener("click", function () { runCheck(); });

  document.getElementById("open-panel").addEventListener("click", function () {
    var port = parseInt($("bot_panel").value, 10) || 8012;
    window.open("http://127.0.0.1:" + port + "/", "_blank");
  });

  $("apply").addEventListener("click", function () {
    var ports = {};
    document.querySelectorAll("#ports input").forEach(function (el) {
      ports[el.dataset.key] = parseInt(el.value, 10) || 0;
    });
    var payload = {
      language: i18n.language(),
      data_dir: $("data_dir").value,
      user_dir: $("user_dir").value,
      qq: $("user_qq").value,
      qq2: $("user_qq").value,
      language: i18n.language(),
        fish_qq: $("fish_qq").value,
      bot_instance: $("bot_instance").value,
      bot_panel: $("bot_panel").value,
      gate_token: $("gate_token").value,
      llm: { provider: "deepseek", api_key: $("api_key").value, base_url: $("base_url").value, model: $("model").value },
      ports: ports
    };
    var btn = $("apply");
    btn.disabled = true;
    btn.textContent = t("setup.applying");
    apiFetch("/api/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (d) {
      var box = $("result");
      box.hidden = false;
      if (d.ok) {
        box.className = "";
        box.innerHTML = t("setup.dynamic.34") + d.files + t("setup.dynamic.22") + d.repl + t("setup.dynamic.35") +
          t("setup.dynamic.25") + esc(d.astrbot || "") + t("setup.dynamic.36");
        runCheck();
      } else {
        box.className = "err";
        box.innerHTML = t("setup.dynamic.28") + esc(d.error || t("setup.unknown_error"));
      }
    }).catch(function (e) {
      var box = $("result");
      box.hidden = false;
      box.className = "err";
      box.innerHTML = t("setup.dynamic.29") + esc(e.message);
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = t("setup.text.47");
    });
  });

  // ---------- 身份词 / 人格提示词优化 ----------
  function loadIdentity() {
    apiFetch("/api/identity").then(function (r) { return r.json(); }).then(function (d) {
      if (d.identity) { $("identity").value = d.identity; }
      if (d.persona) { $("persona").value = d.persona; }
    }).catch(function () {});
  }

  $("opt_identity").addEventListener("click", function () {
    var btn = $("opt_identity");
    var st = $("identity_st");
    if (!$("identity").value.trim()) { st.textContent = t("setup.identity.required"); return; }
    btn.disabled = true;
    btn.textContent = t("setup.identity.optimizing");
    st.textContent = t("setup.identity.generating");
    apiFetch("/api/optimize_identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identity: $("identity").value,
        api_key: $("api_key").value,
        base_url: $("base_url").value,
        model: $("model").value
      })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) {
        $("persona").value = d.persona;
        st.textContent = t("setup.identity.generated");
      } else {
        st.textContent = "❌ " + (d.error || t("setup.identity.failed"));
      }
    }).catch(function (e) {
      st.textContent = t("setup.dynamic.37") + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = t("setup.text.10");
    });
  });

  $("save_identity").addEventListener("click", function () {
    var btn = $("save_identity");
    var st = $("identity_st");
    btn.disabled = true;
    btn.textContent = t("setup.saving");
    apiFetch("/api/save_identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity: $("identity").value, persona: $("persona").value })
    }).then(function (r) { return r.json(); }).then(function (d) {
      st.textContent = d.ok ? t("setup.identity.saved") : "❌ " + (d.error || t("setup.save_failed"));
    }).catch(function (e) {
      st.textContent = t("setup.dynamic.37") + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = t("setup.text.11");
    });
  });

  i18n.mountLanguageSelector(document.getElementById("language-selector"));
  i18n.applyText(document);
  window.addEventListener("languagechange", function () {
    i18n.applyText(document);
    PORT_NAMES.forEach(function (pair) {
      var input = document.querySelector("#ports input[data-key='" + pair[0] + "']");
      if (input && input.previousSibling) input.previousSibling.textContent = t("setup.dynamic." + (PORT_NAMES.indexOf(pair) + 1)) + " ";
    });
    document.querySelectorAll("[data-act='rec']").forEach(function (button) {
      button.textContent = recorder && currentSlot === button.dataset.slot ? t("setup.stop") : t("setup.record");
    });
    document.querySelectorAll("[data-act='play']").forEach(function (button) { button.textContent = t("setup.play"); });
    $("adv-toggle").textContent = $("advanced").hidden ? t("setup.text.30") : t("setup.advanced.collapse");
  });
  buildEnroll();
  refreshDefaults();
  loadIdentity();
  autoCheckOnOpen();
})();
