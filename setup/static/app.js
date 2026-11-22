/* 配置向导 · 逻辑 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var PORT_NAMES = [
    ["chat", "聊天"], ["gallery", "画廊"], ["video", "视频"], ["video_https", "视频HTTPS"],
    ["life", "生命面板"], ["brain", "记忆星图"], ["house", "大平层"], ["qr", "扫码页"],
    ["hub", "Hub总入口"], ["hands", "手部服务"], ["bot", "机器人消息"], ["panel", "机器人面板"],
    ["napcat", "协议端口"]
  ];

  var VOICE_SLOTS = ["第1句", "第2句", "第3句", "第4句", "第5句"];
  var FACE_SLOTS = [["up", "上"], ["down", "下"], ["left", "左"], ["right", "右"], ["front", "正"]];

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
      div.innerHTML = "<span class='slot-name'>" + label + "</span>" +
        "<button class='mini-btn' data-act='rec' data-slot='" + slot + "'>🎙 录</button>" +
        "<button class='mini-btn' data-act='play' data-slot='" + slot + "'>▶ 听</button>" +
        "<span class='slot-st' data-slot='" + slot + "'></span>";
      vb.appendChild(div);
    });
    var fb = $("face_slots");
    fb.innerHTML = "";
    FACE_SLOTS.forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var div = document.createElement("div");
      div.className = "slot";
      div.innerHTML = "<span class='slot-name'>" + label + "</span>" +
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
          voiceData[currentSlot] = reader.result;
          setSlotState(currentSlot, "✅ 已录");
        };
        reader.readAsDataURL(blob);
      };
      recorder.start();
      setSlotState(slot, "🔴 录音中…再点一下停止");
      var recBtn = document.querySelector("[data-act='rec'][data-slot='" + slot + "']");
      recBtn.textContent = "⏹ 停";
    }).catch(function (e) {
      setSlotState(slot, "录音失败：" + e.message);
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
    var t = e.target;
    if (t.dataset && t.dataset.act === "rec") {
      if (recorder && currentSlot === t.dataset.slot) { stopRec(); }
      else { startRec(t.dataset.slot); }
    } else if (t.dataset && t.dataset.act === "play") {
      playSlot(t.dataset.slot);
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
        setSlotState(slot, "✅ 已选");
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
    fetch("/api/defaults").then(function (r) { return r.json(); }).then(function (d) {
      $("data_dir").value = d.data_dir || "";
      $("user_dir").value = d.user_dir || "";
      $("user_qq").value = d.qq || "";
      $("bot_instance").value = d.bot_instance || "";
      $("bot_panel").value = d.bot_panel || 8012;
      $("base_url").value = (d.llm && d.llm.base_url) || "";
      $("model").value = (d.llm && d.llm.model) || "deepseek-chat";
      buildPortInputs(d);
      // 自动探测 AstrBot
      fetch("/api/autodetect").then(function (r2) { return r2.json(); }).then(function (det) {
        if (det.bot_instance) {
          $("bot_instance").value = det.bot_instance;
          $("bot_panel").value = det.bot_panel;
        }
      }).catch(function () {});
    }).catch(function (e) {
      $("quick_result").hidden = false;
      $("quick_result").innerHTML = "加载默认值失败：" + e.message;
    });
  }

  function runCheck(done) {
    var box = $("checkresult");
    box.hidden = false;
    box.innerHTML = "正在体检…";
    fetch("/api/check").then(function (r) { return r.json(); }).then(function (d) {
      var items = d.checks || [];
      var html = "";
      var fail = 0, warn = 0;
      items.forEach(function (c) {
        var label = { ok: "✅ 通过", warn: "⚠️ 注意", fail: "❌ 要修", info: "💡 提示" }[c.level] || c.level;
        if (c.level === "fail") { fail++; }
        if (c.level === "warn") { warn++; }
        html += '<div class="item"><span class="mark ' + c.level + '">' + label + "</span>" +
          "<span><b>" + c.name + "</b> <span class='detail'>" + c.detail + "</span></span></div>";
        if (c.hint) { html += '<div class="hint">→ ' + c.hint + "</div>"; }
      });
      if (fail === 0 && warn === 0) {
        html = '<div class="allgreen">✅ 全部绿灯，一切就绪！</div>' + html;
      }
      box.innerHTML = html;
      if (done) { done(fail, warn); }
    }).catch(function (e) {
      box.innerHTML = "体检失败：" + e.message;
      if (done) { done(1, 0); }
    });
  }

  function autoCheckOnOpen() {
    var auto = new URLSearchParams(location.search).get("auto");
    if (auto !== "check") { return; }
    runCheck(function (fail, warn) {
      if (fail === 0 && warn === 0) {
        fetch("/api/huburl").then(function (r) { return r.json(); }).then(function (d) {
          if (!d.url) { return; }
          $("checkresult").innerHTML += '<div class="hint">🚀 马上带你进总入口…</div>';
          setTimeout(function () { location.href = d.url; }, 1500);
        });
      }
    });
  }

  // ---------- 自动装机 ----------
  $("envsetup").addEventListener("click", function () {
    var box = $("env_result");
    box.hidden = false;
    box.innerHTML = "正在检查与安装（可能要几分钟）…";
    fetch("/api/envsetup", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      var html = "";
      (d.results || []).forEach(function (it) {
        html += "<div class='item'><span class='mark " + (it.ok ? "ok" : "fail") + "'>" +
          (it.ok ? "✅" : "❌") + "</span><span><b>" + it.name + "</b> <span class='detail'>" + it.detail + "</span></span></div>";
      });
      box.innerHTML = html;
    }).catch(function (e) {
      box.innerHTML = "装机请求失败：" + e.message;
    });
  });

  // ---------- 一键自动配置（账号匹配） ----------
  $("autoconfig").addEventListener("click", function () {
    var btn = $("autoconfig");
    btn.disabled = true;
    btn.textContent = "正在自动配置…";
    fetch("/api/autoconfig", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
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
          "<b>✅ 自动配置完成！</b><br>" +
          "重写 " + d.files + " 个文件 / " + d.repl + " 处；口令已自动生成。<br>" +
          (det.bot_instance ? "自动找到 AstrBot 实例：" + det.bot_instance + "<br>" : "") +
          "<b>大脑</b>：" + (d.astrbot || "") + "<br>" +
          "<b>声纹/脸</b>：" + (en.note || "未提交样本") + "<br><br>" +
          "<b>下一步</b>：双击 打开入口.cmd 开始使用。";
      } else {
        box.className = "err";
        box.innerHTML = "<b>❌ 出错了：</b>" + (d.error || "未知错误");
      }
      runCheck();
    }).catch(function (e) {
      var box = $("quick_result");
      box.hidden = false;
      box.className = "err";
      box.innerHTML = "<b>❌ 连不上配置服务：</b>" + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "⚡ 开始自动配置";
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
      if (!files || !files.length) { st.textContent = "先选文件"; return; }
      st.textContent = "读取中…";
      readAll(files).then(function (list) {
        st.textContent = "上传中（" + list.length + " 个文件）…";
        return fetch("/api/import_asset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: kind, files: list })
        });
      }).then(function (r) { return r.json(); }).then(function (d) {
        st.textContent = d.ok ? "✅ 已导入 " + d.count + " 个文件" : "❌ " + (d.error || "失败");
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
    $("adv-toggle").textContent = show ? "⚙️ 详细设置（手动配置，收起）" : "⚙️ 详细设置（手动配置，点开）";
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
      data_dir: $("data_dir").value,
      user_dir: $("user_dir").value,
      qq: $("user_qq").value,
      qq2: $("user_qq").value,
      fish_qq: $("fish_qq").value,
      bot_instance: $("bot_instance").value,
      bot_panel: $("bot_panel").value,
      gate_token: $("gate_token").value,
      llm: { provider: "deepseek", api_key: $("api_key").value, base_url: $("base_url").value, model: $("model").value },
      ports: ports
    };
    var btn = $("apply");
    btn.disabled = true;
    btn.textContent = "正在应用…";
    fetch("/api/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (d) {
      var box = $("result");
      box.hidden = false;
      if (d.ok) {
        box.className = "";
        box.innerHTML = "<b>✅ 配置完成！</b><br>重写了 " + d.files + " 个文件 / " + d.repl + " 处。<br>" +
          "<b>大脑</b>：" + (d.astrbot || "") + "<br><br><b>下一步</b>：双击 打开入口.cmd 开始使用。";
        runCheck();
      } else {
        box.className = "err";
        box.innerHTML = "<b>❌ 出错了：</b>" + (d.error || "未知错误");
      }
    }).catch(function (e) {
      var box = $("result");
      box.hidden = false;
      box.className = "err";
      box.innerHTML = "<b>❌ 连不上配置服务：</b>" + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "🚀 一键应用";
    });
  });

  // ---------- 身份词 / 人格提示词优化 ----------
  function loadIdentity() {
    fetch("/api/identity").then(function (r) { return r.json(); }).then(function (d) {
      if (d.identity) { $("identity").value = d.identity; }
      if (d.persona) { $("persona").value = d.persona; }
    }).catch(function () {});
  }

  $("opt_identity").addEventListener("click", function () {
    var btn = $("opt_identity");
    var st = $("identity_st");
    if (!$("identity").value.trim()) { st.textContent = "先写一段身份词"; return; }
    btn.disabled = true;
    btn.textContent = "优化中…（调用你的 API）";
    st.textContent = "正在用你的 API 生成人格提示词…";
    fetch("/api/optimize_identity", {
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
        st.textContent = "✅ 已生成，可手动修改后再保存";
      } else {
        st.textContent = "❌ " + (d.error || "优化失败");
      }
    }).catch(function (e) {
      st.textContent = "❌ 连不上配置服务：" + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "✨ 用我的 API 优化成提示词";
    });
  });

  $("save_identity").addEventListener("click", function () {
    var btn = $("save_identity");
    var st = $("identity_st");
    btn.disabled = true;
    btn.textContent = "保存中…";
    fetch("/api/save_identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity: $("identity").value, persona: $("persona").value })
    }).then(function (r) { return r.json(); }).then(function (d) {
      st.textContent = d.ok ? "✅ 已保存为她的身份（video/config.json）" : "❌ " + (d.error || "保存失败");
    }).catch(function (e) {
      st.textContent = "❌ 连不上配置服务：" + e.message;
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "💾 保存为她的身份";
    });
  });

  buildEnroll();
  refreshDefaults();
  loadIdentity();
  autoCheckOnOpen();
})();
