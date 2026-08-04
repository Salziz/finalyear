/**
 * timeline.js — Loads recording sessions and wires playback + scrubber.
 */

const Timeline = (function () {
  const listEl = () => document.getElementById("timeline-list");
  const videoEl = () => document.getElementById("playback-video");
  const scrubberEl = () => document.getElementById("playback-scrubber");
  const metaEl = () => document.getElementById("playback-meta");

  let activeSessionId = null;
  let seeking = false;
  let scrubberReady = false;

  function formatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
  }

  function playbackUrl(session) {
    return session.playback_url || `/recordings/${session.filename}`;
  }

  function initScrubber() {
    if (scrubberReady) return;
    scrubberReady = true;

    const scrubber = scrubberEl();
    const video = videoEl();

    video.addEventListener("loadedmetadata", () => {
      scrubber.max = video.duration || 100;
      scrubber.value = 0;
    });

    video.addEventListener("timeupdate", () => {
      if (!seeking) {
        scrubber.value = video.currentTime;
      }
    });

    scrubber.addEventListener("input", () => {
      seeking = true;
      video.currentTime = parseFloat(scrubber.value);
    });

    scrubber.addEventListener("change", () => {
      seeking = false;
    });

    video.addEventListener("error", () => {
      const src = video.currentSrc || video.querySelector("source")?.src || "";
      const isLegacyAvi = src.toLowerCase().includes(".avi");
      metaEl().textContent = isLegacyAvi
        ? "This .avi recording uses a codec browsers cannot play. Restart the server, then record a new session (saved as .mp4)."
        : "Playback failed — try recording a new session after restarting the server.";
    });
  }

  async function loadSessions() {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderList(sessions);
  }

  function renderList(sessions) {
    const el = listEl();
    if (!sessions.length) {
      el.innerHTML = '<p class="timeline-item">No recordings yet</p>';
      return;
    }

    el.innerHTML = sessions
      .map(
        (s) => `
      <div class="timeline-item" data-id="${s.id}" data-url="${playbackUrl(s)}" data-ext="${(s.filename || '').split('.').pop()}">
        <strong>${s.start_time}</strong>
        <div class="meta">
          ${s.filename} · End: ${s.end_time || "—"} · Duration: ${formatDuration(s.duration_seconds || 0)}
          · Detections: ${s.detection_count}
        </div>
      </div>`
      )
      .join("");

    el.querySelectorAll(".timeline-item[data-id]").forEach((item) => {
      item.addEventListener("click", () => selectSession(item));
    });
  }

  async function selectSession(item) {
    const id = item.dataset.id;
    const url = item.dataset.url;
    activeSessionId = id;

    document.querySelectorAll(".timeline-item").forEach((n) => n.classList.remove("active"));
    item.classList.add("active");

    initScrubber();

    const res = await fetch(`/api/sessions/${id}`);
    const data = await res.json();
    const session = data.session;
    const playUrl = data.playback_url || url;

    const video = videoEl();
    video.pause();
    video.removeAttribute("src");
    video.innerHTML = "";
    video.load();

    const ext = (session.filename || "").split(".").pop().toLowerCase();
    const source = document.createElement("source");
    source.src = playUrl;
    if (ext === "mp4") {
      source.type = "video/mp4";
    } else if (ext === "webm") {
      source.type = "video/webm";
    }
    video.appendChild(source);
    video.load();

    metaEl().textContent = `Loading: ${session.start_time} → ${session.end_time || "—"} (${session.detection_count} detections)`;

    try {
      await video.play();
      metaEl().textContent = `Playing: ${session.start_time} → ${session.end_time || "—"} (${session.detection_count} detections)`;
    } catch (_err) {
      metaEl().textContent = `Loaded — press play: ${session.start_time} → ${session.end_time || "—"}`;
    }
  }

  function refresh() {
    return loadSessions();
  }

  return { loadSessions, refresh, formatDuration };
})();
