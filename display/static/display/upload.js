(function () {
  "use strict";
  var cfg = document.getElementById("upload-config").dataset;
  var $ = function (id) { return document.getElementById(id); };
  var queue = [], xhr = null, cancelled = false, sent = 0, failed = 0, season = "";

  function show(id) {
    ["pick", "progress", "done", "closed"].forEach(function (s) { $(s).hidden = s !== id; });
  }

  function seasonLabel() {
    var input = document.querySelector('input[name="season"]:checked');
    return input && input.value ? input.nextElementSibling.textContent : "";
  }

  function row(file) {
    var li = document.createElement("li");
    li.innerHTML = '<span class="up-name"></span><span class="up-state">Waiting</span>' +
      '<span class="up-bar"><i></i></span>';
    li.querySelector(".up-name").textContent = file.name;
    $("list").appendChild(li);
    return li;
  }

  function finish() {
    xhr = null;
    if (!sent) {
      $("progress-title").textContent = cancelled ? "Cancelled" : "Nothing was added";
      $("cancel").textContent = "Try again";
      $("cancel").onclick = reset;
      return;
    }
    var label = seasonLabel();
    $("done-title").textContent = sent === 1 ? "1 photo added" : sent + " photos added";
    $("done-sub").textContent = (label ? "They're in the " + label + " rotation now." :
      "They're in every season's rotation now.") + " You can hide or retag them in Settings." +
      (failed ? " " + failed + " couldn't be read." : "");
    show("done");
  }

  function next() {
    if (cancelled || !queue.length) { finish(); return; }
    var item = queue.shift(), li = item.li, bar = li.querySelector(".up-bar i"),
      state = li.querySelector(".up-state");
    var body = new FormData();
    body.append("photo", item.file);
    body.append("seasons", season);
    xhr = new XMLHttpRequest();
    xhr.open("POST", cfg.url);
    xhr.setRequestHeader("X-CSRFToken", cfg.csrf);
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        bar.style.width = Math.round(e.loaded / e.total * 100) + "%";
        state.textContent = e.loaded < e.total ? "Sending" : "Processing";
      }
    };
    xhr.onload = function () {
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (err) { /* not JSON */ }
      if (xhr.status === 200) {
        sent += 1; li.className = "ok"; bar.style.width = "100%"; state.textContent = "Added";
      } else {
        failed += 1; li.className = "bad"; state.textContent = data.error || "Failed";
        if (xhr.status === 403 || xhr.status === 404 || xhr.status === 410) cancelled = true;
      }
      next();
    };
    xhr.onerror = function () { failed += 1; li.className = "bad"; state.textContent = "Network error"; next(); };
    xhr.onabort = function () { li.className = "bad"; state.textContent = "Cancelled"; next(); };
    xhr.send(body);
  }

  function reset() {
    $("list").innerHTML = "";
    $("files").value = "";
    $("cancel").textContent = "Cancel remaining";
    $("cancel").onclick = cancel;
    $("cancel").hidden = false;
    queue = []; sent = 0; failed = 0; cancelled = false;
    show("pick");
  }

  function cancel() {
    cancelled = true;
    queue.forEach(function (item) { item.li.className = "bad"; item.li.querySelector(".up-state").textContent = "Cancelled"; });
    queue = [];
    if (xhr) xhr.abort(); else finish();
  }

  $("files").addEventListener("change", function () {
    var files = Array.prototype.slice.call(this.files);
    if (!files.length) return;
    var input = document.querySelector('input[name="season"]:checked');
    season = input ? input.value : "";
    queue = files.map(function (file) { return { file: file, li: row(file) }; });
    $("progress-title").textContent = files.length === 1 ? "Sending 1 photo" : "Sending " + files.length + " photos";
    show("progress");
    next();
  });
  $("cancel").onclick = cancel;
  $("more").addEventListener("click", reset);
  $("finish").addEventListener("click", function () { show("closed"); });
})();
