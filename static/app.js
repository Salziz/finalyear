const cameraGrid = document.getElementById("cameraGrid");
const cameraCount = document.getElementById("cameraCount");
const connectionStatus = document.getElementById("connectionStatus");
const healthStatus = document.getElementById("healthStatus");

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function createCameraCard(camera) {
  const card = document.createElement("article");
  card.className = "camera-card";

  const title = document.createElement("h3");
  title.textContent = camera.name ?? "Unnamed Camera";

  const meta = document.createElement("div");
  meta.className = "camera-meta";
  const location = document.createElement("span");
  location.textContent = camera.location ?? "Unknown sector";
  const type = document.createElement("span");
  type.textContent = (camera.type ?? "unknown").toUpperCase();
  meta.append(location, type);

  const feedWrapper = document.createElement("div");
  feedWrapper.className = "feed-wrapper";

  const feed = renderFeed(camera, feedWrapper);
  feedWrapper.append(feed);

  card.append(title, meta, feedWrapper);
  return card;
}

function renderFeed(camera, container) {
  const type = camera.type ?? "unknown";

  if (type === "hls") {
    const video = document.createElement("video");
    video.controls = true;
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;

    if (window.Hls && Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(camera.url);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, () => {
        container.innerHTML = "";
        container.append(renderPlaceholder("HLS stream unavailable."));
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = camera.url;
    } else {
      return renderPlaceholder("HLS playback not supported on this device.");
    }

    return video;
  }

  if (type === "mjpeg") {
    const img = document.createElement("img");
    img.alt = `MJPEG stream for ${camera.name ?? "camera"}`;
    img.src = camera.url;
    img.loading = "lazy";
    return img;
  }

  if (type === "snapshot") {
    const img = document.createElement("img");
    img.alt = `Snapshot for ${camera.name ?? "camera"}`;
    img.src = camera.url;
    img.loading = "lazy";
    return img;
  }

  if (type === "webrtc") {
    return renderPlaceholder("WebRTC feed: open the operator app to connect.");
  }

  if (type === "webcam") {
    const placeholder = renderPlaceholder("Awaiting webcam permission...");

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      placeholder.textContent = "Webcam access not supported on this device.";
      return placeholder;
    }

    navigator.mediaDevices
      .getUserMedia({ video: true, audio: false })
      .then((stream) => {
        const video = document.createElement("video");
        video.autoplay = true;
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        placeholder.replaceWith(video);
      })
      .catch(() => {
        placeholder.textContent = "Webcam permission denied or unavailable.";
      });

    return placeholder;
  }

  return renderPlaceholder("Unsupported feed type.");
}

function renderPlaceholder(message) {
  const placeholder = document.createElement("div");
  placeholder.className = "feed-placeholder";
  placeholder.textContent = message;
  return placeholder;
}

async function loadCameras() {
  try {
    const [cameraResponse, health] = await Promise.all([
      fetchJson("/api/cameras"),
      fetchJson("/api/health"),
    ]);
    const cameras = cameraResponse.cameras ?? [];

    cameraGrid.innerHTML = "";
    if (cameras.length === 0) {
      cameraGrid.append(renderPlaceholder("No cameras configured yet."));
    } else {
      cameras.forEach((camera) => cameraGrid.append(createCameraCard(camera)));
    }

    cameraCount.textContent = cameras.length.toString();
    connectionStatus.textContent = "Online";
    healthStatus.textContent = health.status === "ok" ? "Operational" : "Degraded";
    document.querySelector(".status-dot").style.background = "#3ddc84";
    document.querySelector(".status-dot").style.boxShadow = "0 0 10px rgba(61, 220, 132, 0.8)";
  } catch (error) {
    cameraGrid.innerHTML = "";
    cameraGrid.append(renderPlaceholder("Unable to load camera feeds."));
    connectionStatus.textContent = "Offline";
    healthStatus.textContent = "Unavailable";
  }
}

loadCameras();
