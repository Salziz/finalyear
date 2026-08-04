/**
 * main.js — UI wiring: status bar, recording, ID card, alerts, modal.
 */

(function () {
  const els = {
    camera: document.getElementById("status-camera"),
    recording: document.getElementById("status-recording"),
    db: document.getElementById("status-db"),
    session: document.getElementById("status-session"),
    recIndicator: document.getElementById("rec-indicator"),
    btnRecord: document.getElementById("btn-record"),
    btnScan: document.getElementById("btn-scan"),
    alertBanner: document.getElementById("alert-banner"),
    alertText: document.getElementById("alert-text"),
    alertDismiss: document.getElementById("alert-dismiss"),
    idCard: document.getElementById("id-card"),
    idPhoto: document.getElementById("id-photo"),
    idName: document.getElementById("id-name"),
    idNumber: document.getElementById("id-number"),
    idClearance: document.getElementById("id-clearance"),
    idRole: document.getElementById("id-role"),
    idTime: document.getElementById("id-time"),
    modal: document.getElementById("id-modal"),
    modalPhoto: document.getElementById("modal-photo"),
    modalName: document.getElementById("modal-name"),
    modalId: document.getElementById("modal-id"),
    modalClearance: document.getElementById("modal-clearance"),
    modalRole: document.getElementById("modal-role"),
    modalTime: document.getElementById("modal-time"),
    modalResult: document.getElementById("modal-result"),
  };

  let isRecording = false;
  let lastDetection = null;
  let alertVisible = false;

  function formatSessionDuration(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
  }

  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      els.camera.textContent = data.camera;
      els.db.textContent = data.database;
      els.recording.textContent = data.recording ? "RECORDING" : "IDLE";
      els.session.textContent = data.recording
        ? formatSessionDuration(data.session_duration_seconds)
        : "00:00:00";
      if (els.btnScan) {
        els.btnScan.classList.toggle("hidden", !data.dev_mode);
      }
    } catch (e) {
      els.db.textContent = "ERROR";
    }
  }

  async function triggerScan() {
    if (!els.btnScan || els.btnScan.classList.contains("hidden")) return;
    els.btnScan.disabled = true;
    els.btnScan.textContent = "Scanning…";
    try {
      const res = await fetch("/api/scan", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        console.warn("[Scan]", data.error || res.statusText);
        return;
      }
      // WebSocket usually updates UI first; fallback if socket missed
      if (data.primary) {
        updateIdCard(data.primary);
        if (data.primary.clearance_result === "NOT CLEARED") {
          showAlert({
            message: `UNCLEARED INDIVIDUAL DETECTED — ${data.primary.detected_at || ""}`,
          });
        }
      }
    } catch (err) {
      console.error("[Scan]", err);
    } finally {
      els.btnScan.disabled = false;
      els.btnScan.textContent = "Scan Now";
    }
  }

  function setRecordingUI(on) {
    isRecording = on;
    els.recIndicator.classList.toggle("hidden", !on);
    els.btnRecord.textContent = on ? "Stop Recording" : "Start Recording";
    els.btnRecord.classList.toggle("recording", on);
  }

  async function toggleRecording() {
    const url = isRecording ? "/api/recording/stop" : "/api/recording/start";
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();
    if (data.ok !== false) {
      setRecordingUI(!isRecording);
      if (!isRecording && data.session) {
        Timeline.refresh();
      }
    }
  }

  function updateIdCard(payload) {
    lastDetection = payload;
    const photo = payload.captured_image_url || payload.profile_photo_url || "";
    els.idPhoto.src = photo;
    els.idName.textContent = payload.full_name || "UNKNOWN";
    els.idNumber.innerHTML = `<span>ID:</span> ${payload.id_number || "N/A"}`;

    const cleared = payload.clearance_result === "CLEARED";
    els.idClearance.textContent = payload.clearance_result;
    els.idClearance.className = "id-clearance " + (cleared ? "cleared" : "not-cleared");

    els.idRole.innerHTML = `<span>Role:</span> ${payload.role || "—"}`;
    els.idTime.textContent = payload.detected_at || "—";

    // Modal fields
    els.modalPhoto.src = photo;
    els.modalName.textContent = payload.full_name || "UNKNOWN";
    els.modalId.textContent = payload.id_number || "N/A";
    els.modalClearance.textContent = payload.clearance_result;
    els.modalClearance.style.color = cleared ? "var(--cleared)" : "var(--not-cleared)";
    els.modalRole.textContent = payload.role || "—";
    els.modalTime.textContent = payload.detected_at || "—";
    els.modalResult.textContent = payload.clearance_result;
  }

  function showAlert(payload) {
    alertVisible = true;
    document.body.classList.add("alert-active");
    els.alertBanner.classList.remove("hidden");
    els.alertText.textContent = "⚠ " + (payload.message || "UNCLEARED INDIVIDUAL DETECTED");
  }

  function hideAlert() {
    alertVisible = false;
    document.body.classList.remove("alert-active");
    els.alertBanner.classList.add("hidden");
    SurveillanceSocket.dismissAlert();
  }

  function openModal() {
    if (!lastDetection) return;
    els.modal.classList.remove("hidden");
    els.modal.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    els.modal.classList.add("hidden");
    els.modal.setAttribute("aria-hidden", "true");
  }

  // Event bindings
  els.btnRecord.addEventListener("click", toggleRecording);
  if (els.btnScan) {
    els.btnScan.addEventListener("click", triggerScan);
  }
  els.alertDismiss.addEventListener("click", hideAlert);
  els.idCard.addEventListener("click", openModal);
  els.idCard.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openModal();
    }
  });
  document.querySelectorAll("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  // Socket handlers
  SurveillanceSocket.connect();
  SurveillanceSocket.on("detection", (payload) => {
    updateIdCard(payload);
    // Next cleared detection can clear alert per spec ("or next frame clears it")
    if (payload.clearance_result === "CLEARED" && alertVisible) {
      hideAlert();
    }
  });
  SurveillanceSocket.on("alert", showAlert);
  SurveillanceSocket.on("recording_status", (payload) => {
    setRecordingUI(!!payload.recording);
    if (!payload.recording && payload.session) {
      Timeline.refresh();
    }
  });
  SurveillanceSocket.on("alert_dismissed", hideAlert);

  // Init
  Timeline.loadSessions();
  pollStatus();
  setInterval(pollStatus, 2000);

  fetch("/api/detections/latest")
    .then((r) => r.json())
    .then((data) => {
      if (data) updateIdCard(data);
    })
    .catch(() => {});
})();
