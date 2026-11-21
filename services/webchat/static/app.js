/* 聊天页 · 骨架逻辑 */
(function () {
  "use strict";

  // 口令从 URL 的 ?t= 取（部署时改成你自己的口令）
  var token = new URLSearchParams(location.search).get("t") || "";
  var flow = document.getElementById("chat-flow");
  var input = document.getElementById("input");
  var send = document.getElementById("send");
  var statusDot = document.getElementById("status-dot");
  var statusText = document.getElementById("status-text");
  var composing = false;      // 输入法组词期间不发送

  function setStatus(ok, text) {
    statusDot.className = ok ? "online" : "";
    statusText.textContent = text;
  }

  function addMsg(role, text) {
    var el = document.createElement("div");
    el.className = "msg " + role;
    el.textContent = text;
    flow.appendChild(el);
    flow.scrollTop = flow.scrollHeight;
  }

  async function sendMsg() {
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    addMsg("user", text);
    send.disabled = true;
    try {
      var resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Gate-Token": token },
        body: JSON.stringify({ text: text })
      });
      var data = await resp.json();
      if (resp.ok) {
        addMsg("bot", data.reply);
        setStatus(true, "在线");
      } else {
        addMsg("bot", "出错了：" + (data.error || resp.status));
        setStatus(false, "口令或接口有问题");
      }
    } catch (e) {
      addMsg("bot", "连不上服务：" + e.message);
      setStatus(false, "离线");
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  input.addEventListener("compositionstart", function () { composing = true; });
  input.addEventListener("compositionend", function () { composing = false; });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !composing) {
      e.preventDefault();
      sendMsg();
    }
  });
  send.addEventListener("click", sendMsg);

  // 载入最近历史（如果有）
  fetch("/api/history", { headers: { "X-Gate-Token": token } })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (d) {
      (d.history || []).forEach(function (m) { addMsg(m.role, m.text); });
      setStatus(true, "在线");
    })
    .catch(function () { setStatus(false, "口令不对或服务未启动"); });

  input.focus();
})();
