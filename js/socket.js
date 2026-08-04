/**
 * socket.js — Flask-SocketIO client for real-time detection and alerts.
 */

const SurveillanceSocket = (function () {
  let socket = null;
  const listeners = {
    detection: [],
    alert: [],
    recording_status: [],
    alert_dismissed: [],
  };

  function connect() {
    socket = io({ transports: ["websocket", "polling"] });

    socket.on("connect", () => {
      console.log("[Socket] Connected");
    });

    socket.on("detection", (payload) => {
      listeners.detection.forEach((fn) => fn(payload));
    });

    socket.on("alert", (payload) => {
      listeners.alert.forEach((fn) => fn(payload));
    });

    socket.on("recording_status", (payload) => {
      listeners.recording_status.forEach((fn) => fn(payload));
    });

    socket.on("alert_dismissed", () => {
      listeners.alert_dismissed.forEach((fn) => fn());
    });
  }

  function on(event, callback) {
    if (listeners[event]) {
      listeners[event].push(callback);
    }
  }

  function dismissAlert() {
    if (socket) {
      socket.emit("dismiss_alert");
    }
  }

  return { connect, on, dismissAlert };
})();
