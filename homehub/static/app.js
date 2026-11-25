/* Home Hub front end. Plain ES2017, no build step, so it runs in Silk and
 * kiosk-browser WebViews on older Fire OS versions. */
(function () {
  "use strict";

  var POLL_MS = 10000;        // device state
  var EVENTS_MS = 20000;      // activity list
  var SNAP_MS = 60000;        // camera thumbnails (battery cameras: keep it slow)

  var state = { devices: [], pinRequired: false, snapStamp: Date.now() };

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "text") n.textContent = attrs[k];
        else if (k === "class") n.className = attrs[k];
        else if (k.indexOf("on") === 0) n.addEventListener(k.slice(2), attrs[k]);
        else n.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }

  function api(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error(data.error || ("HTTP " + r.status));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }

  // ---------- clock ----------
  function tickClock() {
    var d = new Date();
    $("time").textContent = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    $("date").textContent = d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  }

  function ago(ts) {
    if (!ts) return "";
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  // ---------- toast / banner ----------
  var toastTimer = null;
  function toast(msg, isError) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (isError ? " error" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 3500);
  }

  function showErrors(errors) {
    var keys = Object.keys(errors || {});
    var b = $("banner");
    if (!keys.length) { b.hidden = true; return; }
    b.textContent = keys.map(function (k) { return k + ": " + errors[k]; }).join(" • ");
    b.hidden = false;
  }

  // ---------- PIN pad ----------
  function askPin(title) {
    return new Promise(function (resolve) {
      var entered = "";
      var box = $("pin"), dots = $("pin-dots"), pad = $("pin-pad");
      $("pin-title").textContent = title;
      function draw() { dots.textContent = entered.replace(/./g, "●"); }
      function done(val) { box.hidden = true; pad.innerHTML = ""; resolve(val); }
      pad.innerHTML = "";
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "✕", "0", "OK"].forEach(function (k) {
        pad.appendChild(el("button", {
          type: "button",
          class: "btn" + (k === "OK" ? " primary" : ""),
          text: k,
          onclick: function () {
            if (k === "✕") return done(null);
            if (k === "OK") return done(entered);
            if (entered.length < 8) { entered += k; draw(); }
          }
        }));
      });
      draw();
      box.hidden = false;
    });
  }

  // ---------- actions ----------
  function doAction(dev, action, btn) {
    var needsPin = state.pinRequired && (action === "arm" || action === "disarm");
    var pinP = needsPin ? askPin((action === "arm" ? "Arm " : "Disarm ") + dev.name) : Promise.resolve("");
    return pinP.then(function (pin) {
      if (pin === null) return;
      if (btn) btn.disabled = true;
      return api("POST", "/api/devices/" + encodeURIComponent(dev.id) + "/action",
                 { action: action, pin: pin })
        .then(function () {
          if (action === "snapshot") state.snapStamp = Date.now();
          return loadDevices();
        })
        .catch(function (e) { toast(e.message, true); })
        .then(function () { if (btn) btn.disabled = false; });
    });
  }

  function snapUrl(dev) {
    return "/api/snapshot/" + encodeURIComponent(dev.id) + "?t=" + state.snapStamp;
  }

  // ---------- viewer ----------
  var viewerDev = null;
  function openViewer(dev) {
    viewerDev = dev;
    $("viewer-title").textContent = dev.name;
    $("viewer-img").src = snapUrl(dev);
    $("viewer").hidden = false;
  }
  function closeViewer() { $("viewer").hidden = true; viewerDev = null; }

  // ---------- render ----------
  function batteryText(dev) {
    if (typeof dev.battery === "number") {
      return el("span", { class: dev.battery <= 25 ? "low" : "", text: "🔋 " + dev.battery + "%" });
    }
    if (dev.extra && dev.extra.battery_state) {
      var low = String(dev.extra.battery_state).toLowerCase() !== "ok";
      return el("span", { class: low ? "low" : "", text: "Battery " + dev.extra.battery_state });
    }
    return null;
  }

  function renderCamera(dev) {
    var img = el("div", { class: "cam-img", role: "button", "aria-label": "Open " + dev.name });
    if (dev.has_snapshot) img.style.backgroundImage = "url('" + snapUrl(dev) + "')";
    img.addEventListener("click", function () { if (dev.has_snapshot) openViewer(dev); });
    img.appendChild(el("span", { class: "badge", text: dev.provider + (dev.kind === "doorbell" ? " doorbell" : "") }));
    if (!dev.online) img.appendChild(el("div", { class: "offline", text: "Offline" }));

    var metaBits = [];
    if (dev.last_motion) metaBits.push(el("span", { text: "Motion " + ago(dev.last_motion) }));
    var batt = batteryText(dev);
    var meta = el("span", { class: "meta" });
    metaBits.concat(batt ? [batt] : []).forEach(function (m, i) {
      if (i) meta.appendChild(document.createTextNode(" · "));
      meta.appendChild(m);
    });

    var buttons = [];
    function addBtn(label, action, cls) {
      if (dev.actions.indexOf(action) < 0) return;
      var b = el("button", { type: "button", class: "btn" + (cls ? " " + cls : ""), text: label });
      b.addEventListener("click", function () { doAction(dev, action, b); });
      buttons.push(b);
    }
    if (dev.armed !== null && dev.armed !== undefined) {
      if (dev.armed) addBtn("Disarm", "disarm", "danger"); else addBtn("Arm", "arm");
    }
    if (dev.motion_enabled !== null && dev.motion_enabled !== undefined && dev.actions.indexOf("motion_on") >= 0) {
      if (dev.motion_enabled) addBtn("Motion off", "motion_off"); else addBtn("Motion on", "motion_on");
    }
    if (dev.on !== null && dev.on !== undefined) {
      if (dev.on) addBtn("Light off", "light_off"); else addBtn("Light on", "light_on");
    }
    addBtn("Snapshot", "snapshot");

    return el("div", { class: "cam" }, [
      img,
      el("div", { class: "cam-body" }, [
        el("div", { class: "cam-head" }, [el("span", { class: "cam-name", text: dev.name }), meta]),
        el("div", { class: "row" }, buttons)
      ])
    ]);
  }

  function renderAlarm(dev) {
    var armed = !!dev.armed;
    var b = el("button", {
      type: "button",
      class: "btn " + (armed ? "danger" : "primary"),
      text: armed ? "Disarm" : "Arm"
    });
    b.addEventListener("click", function () { doAction(dev, armed ? "disarm" : "arm", b); });
    return el("div", { class: "tile" }, [
      el("div", null, [
        el("div", { class: "tile-name", text: dev.name }),
        el("div", { class: "tile-state" + (armed ? " armed" : ""), text: dev.online ? (armed ? "Armed" : "Disarmed") : "Offline" })
      ]),
      b
    ]);
  }

  function renderLight(dev) {
    var on = !!dev.on;
    var sw = el("button", { type: "button", class: "switch", role: "switch",
                            "aria-checked": on ? "true" : "false", "aria-label": dev.name });
    sw.addEventListener("click", function () { doAction(dev, on ? "light_off" : "light_on", sw); });
    return el("div", { class: "tile" }, [
      el("div", null, [
        el("div", { class: "tile-name", text: dev.name }),
        el("div", { class: "tile-state" + (on ? " on" : ""), text: on ? "On" : "Off" })
      ]),
      sw
    ]);
  }

  function fill(container, nodes, emptyText) {
    container.innerHTML = "";
    if (!nodes.length) { container.appendChild(el("p", { class: "empty", text: emptyText })); return; }
    nodes.forEach(function (n) { container.appendChild(n); });
  }

  function render() {
    var devs = state.devices;
    var cams = devs.filter(function (d) { return d.kind === "camera" || d.kind === "doorbell"; });
    // Doorbells first, then by name.
    cams.sort(function (a, b) {
      if (a.kind !== b.kind) return a.kind === "doorbell" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    var grid = $("camera-grid");
    grid.style.setProperty("--cols", cams.length <= 1 ? 1 : cams.length <= 4 ? 2 : 3);
    fill(grid, cams.map(renderCamera), "No cameras found.");
    fill($("alarms"), devs.filter(function (d) { return d.kind === "alarm"; }).map(renderAlarm), "No alarm systems.");
    // Ring floodlight/spotlight cams also appear here as lights.
    var lights = devs.filter(function (d) { return d.on !== null && d.on !== undefined; });
    fill($("lights"), lights.map(renderLight), "No lights.");
  }

  function renderEvents(events) {
    var ul = $("events");
    ul.innerHTML = "";
    if (!events.length) { ul.appendChild(el("li", { class: "empty", text: "Nothing yet." })); return; }
    events.forEach(function (e) {
      ul.appendChild(el("li", null, [
        el("span", { class: "ev-dot " + e.kind }),
        el("span", null, [
          el("span", { class: "ev-kind", text: e.kind.replace(/_/g, " ") }),
          document.createTextNode(" · " + e.device_name)
        ]),
        el("span", { class: "ev-when", text: ago(e.at) })
      ]));
    });
  }

  // ---------- loading ----------
  function loadDevices(force) {
    return api("GET", "/api/devices" + (force ? "?refresh=1" : ""))
      .then(function (data) {
        state.devices = data.devices || [];
        showErrors(data.errors);
        render();
      })
      .catch(function (e) { showErrors({ hub: "can't reach the hub (" + e.message + ")" }); });
  }

  function loadEvents() {
    return api("GET", "/api/events?limit=25")
      .then(function (data) { renderEvents(data.events || []); })
      .catch(function () { /* banner already shows connection problems */ });
  }

  function init() {
    tickClock();
    setInterval(tickClock, 10000);

    $("refresh").addEventListener("click", function () {
      state.snapStamp = Date.now();
      loadDevices(true);
      loadEvents();
    });
    $("viewer-close").addEventListener("click", closeViewer);
    $("viewer").addEventListener("click", function (e) { if (e.target === $("viewer")) closeViewer(); });
    $("viewer-snap").addEventListener("click", function () {
      if (!viewerDev) return;
      var dev = viewerDev;
      doAction(dev, "snapshot", $("viewer-snap")).then(function () {
        if (viewerDev) $("viewer-img").src = snapUrl(dev);
      });
    });

    api("GET", "/api/status").then(function (s) { state.pinRequired = !!s.pin_required; }).catch(function () {});
    loadDevices();
    loadEvents();
    setInterval(loadDevices, POLL_MS);
    setInterval(loadEvents, EVENTS_MS);
    setInterval(function () { state.snapStamp = Date.now(); render(); }, SNAP_MS);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
