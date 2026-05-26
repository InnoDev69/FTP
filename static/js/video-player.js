/**
 * video-player.js — Gestor de 6 slots de reproducción
 * 
 * Estados:
 *  - Slot vacío: ningún video cargado
 *  - Slot activo: seleccionado para recibir el próximo archivo (borde azul)
 *  - Slot playing: reproduciendo un video
 */

let activeSlot = 0;           // Slot actualmente seleccionado
const SLOT_COUNT = 6;
const slots = Array(SLOT_COUNT).fill(null);  // null = vacío, o metadatos del archivo

const ACCENT_COLOR = '#0f9eff';  // Azul
const GREEN_COLOR  = '#0fc067';  // Verde

/**
 * Seleccionar qué slot va a recibir el próximo archivo
 */
function activateSlot(i) {
  document.querySelectorAll('.video-slot').forEach(el => el.classList.remove('active'));
  const slot = document.getElementById(`slot-${i}`);
  if (slot) slot.classList.add('active');
  activeSlot = i;
  const activeLabel = document.getElementById('active-slot-label');
  if (activeLabel) activeLabel.textContent = String(i + 1);
}

function updateSlotControls(i) {
  const slot = document.getElementById(`slot-${i}`);
  const video = document.getElementById(`player-${i}`);
  if (!slot || !video) return;

  const playBtn = slot.querySelector('.slot-play');
  const muteBtn = slot.querySelector('.slot-mute');

  if (playBtn) {
    playBtn.textContent = video.paused ? 'Play' : 'Pause';
  }

  if (muteBtn) {
    muteBtn.textContent = video.muted ? 'Unmute' : 'Mute';
  }

  slot.classList.toggle('paused', video.paused);
  slot.classList.toggle('muted', video.muted);
}

function togglePlay(event, i) {
  event.stopPropagation();
  const video = document.getElementById(`player-${i}`);
  if (!video || !video.src) return;

  if (video.paused) {
    video.play().catch(err => console.warn('Auto-play bloqueado:', err));
  } else {
    video.pause();
  }

  updateSlotControls(i);
}

function toggleMute(event, i) {
  event.stopPropagation();
  const video = document.getElementById(`player-${i}`);
  if (!video) return;
  video.muted = !video.muted;
  updateSlotControls(i);
}

/**
 * Wrapper que extrae data del elemento y llama assignFile
 */
function assignFileFromElement(element) {
  const videoId = element.dataset.videoId;
  const deviceId = element.dataset.deviceId;
  const channelId = element.dataset.channelId;
  const path = element.dataset.path;
  
  assignFile(element, videoId, deviceId, channelId, path);
}

/**
 * Cargar y reproducir un archivo en el slot activo
 * Se llama cuando el usuario hace clic en un archivo del sidebar
 * @param {Element} element - El elemento del archivo (opcional)
 * @param {number} videoId - ID del video (no usado actualmente)
 * @param {string} deviceId - ID del dispositivo
 * @param {string} channelId - ID del canal
 * @param {string} path - Path relativo del archivo (ej: "192.168.0.33/archivo.dav")
 */
function assignFile(element, videoId, deviceId, channelId, path) {
  const slotIndex = activeSlot;
  const video = document.getElementById(`player-${slotIndex}`);
  if (!video) return;

  // Limpiar path de comillas JSON si vienen de Jinja2
  if (typeof path === 'string') {
    path = path.trim();
  }

  // Normalizar path para URLs
  if (typeof path === 'string') {
    path = path.replace(/\\/g, '/');
  }

  // Guardar metadata
  slots[slotIndex] = {
    videoId,
    deviceId,
    channelId,
    path,
    timestamp: new Date()
  };

  // Construir URL del stream
  const streamUrl = `/stream/${encodeURIComponent(path).replace(/%2F/g, "/")}`;
  console.log(`[Player] Cargar video en slot ${slotIndex}: ${streamUrl}`);

  // Actualizar etiqueta del slot
  const label = document.getElementById(`label-${slotIndex}`);
  if (label) {
    label.textContent = `${deviceId || '?'} ch${channelId || '?'}`;
  }

  // Cambiar estado visual: de vacío a playing
  const slot = document.getElementById(`slot-${slotIndex}`);
  if (slot) {
    slot.classList.remove('empty');
    slot.classList.add('playing');
  }

  // Event listeners para errores
  video.onerror = (e) => {
    if (!video.src) {
      return;
    }
    console.error(`[Player] Error en video slot ${slotIndex}:`, e, video.error?.message);
    const label = document.getElementById(`label-${slotIndex}`);
    if (label) label.textContent = 'Error: ' + (video.error?.message || 'unknown');
    const slot = document.getElementById(`slot-${slotIndex}`);
    if (slot) {
      slot.classList.remove('playing');
      slot.classList.add('empty');
    }
  };

  video.onabort = () => {
    console.warn(`[Player] Carga abortada en slot ${slotIndex}`);
  };

  video.onloadstart = () => {
    console.log(`[Player] Iniciando carga slot ${slotIndex}`);
  };

  video.oncanplay = () => {
    console.log(`[Player] Video listo en slot ${slotIndex}`);
  };

  video.onloadedmetadata = () => {
    console.log(`[Player] Metadata cargada slot ${slotIndex} - duracion: ${video.duration}s`);
  };

  video.onplay = () => updateSlotControls(slotIndex);
  video.onpause = () => updateSlotControls(slotIndex);
  video.onvolumechange = () => updateSlotControls(slotIndex);

  // Cargar video usando la ruta de streaming
  video.src = streamUrl;
  video.load();

  // Auto-play (con manejo de errores)
  video.play().catch(err => {
    console.warn(`[Player] Auto-play bloqueado en slot ${activeSlot}:`, err.message);
  });

  updateSlotControls(slotIndex);

  // Avanzar al siguiente slot vacío automáticamente
  const next = slots.findIndex((s, i) => i > slotIndex && s === null);
  if (next !== -1) {
    activateSlot(next);
  }
}

/**
 * Limpiar un slot individual
 */
function clearSlot(event, i) {
  event.stopPropagation();

  const video = document.getElementById(`player-${i}`);
  const slot = document.getElementById(`slot-${i}`);
  const label = document.getElementById(`label-${i}`);

  if (video) {
    video.pause();
    video.removeAttribute('src');
    video.load();
  }

  slots[i] = null;

  if (slot) {
    slot.classList.remove('playing');
    slot.classList.add('empty');
  }

  if (label) {
    label.textContent = 'Slot vacío';
  }

  updateSlotControls(i);
}

/**
 * Reproducir todos los videos
 */
function playAll() {
  document.querySelectorAll('.video-slot video').forEach(v => {
    v.play().catch(err => console.warn('Auto-play bloqueado:', err));
  });
}

/**
 * Pausar todos los videos
 */
function pauseAll() {
  document.querySelectorAll('.video-slot video').forEach(v => v.pause());
}

/**
 * Mutear/desmutear todos los videos
 */
function muteAll() {
  const videos = document.querySelectorAll('.video-slot video');
  if (videos.length === 0) return;

  const firstMuted = videos[0].muted;
  const newMutedState = !firstMuted;

  videos.forEach(v => v.muted = newMutedState);

  // Feedback visual
  const btn = document.getElementById('btn-mute-all');
  if (btn) {
    btn.style.opacity = newMutedState ? '0.5' : '1';
  }
}

/**
 * Inicialización
 */
document.addEventListener('DOMContentLoaded', () => {
  // Activar el primer slot por defecto
  activateSlot(0);
  initSidebarFilters();
  initSidebarToggle();
  initFullscreenToggle();
  //formatRecordingDates();
});



function initFullscreenToggle() {
  document.addEventListener('fullscreenchange', updateFullscreenButton);
  updateFullscreenButton();
}

function updateFullscreenButton() {
  const btn = document.getElementById('btn-fullscreen');
  if (!btn) return;
  btn.textContent = document.fullscreenElement ? 'Exit Fullscreen' : 'Fullscreen';
}

function toggleGridFullscreen() {
  const grid = document.querySelector('.video-grid');
  if (!grid) return;

  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }

  grid.requestFullscreen().catch(() => {});
}

function initSidebarToggle() {
  const layout = document.getElementById('player-layout');
  const toggle = document.getElementById('sidebar-toggle');
  if (!layout || !toggle) return;

  const setState = (collapsed) => {
    layout.classList.toggle('sidebar-collapsed', collapsed);
    toggle.textContent = collapsed ? '>>' : 'Ocultar';
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  };

  toggle.addEventListener('click', () => {
    const collapsed = layout.classList.contains('sidebar-collapsed');
    setState(!collapsed);
  });
}

function initSidebarFilters() {
  const list = document.querySelector('.file-list');
  if (!list) return;

  const items = Array.from(list.querySelectorAll('.file-item'));
  const deviceSel = document.getElementById('filter-device');
  const channelSel = document.getElementById('filter-channel');
  const daySel = document.getElementById('filter-day');
  const hourSel = document.getElementById('filter-hour');
  const clearBtn = document.getElementById('filter-clear');

  if (!deviceSel || !channelSel || !daySel || !hourSel || !clearBtn) return;

  const devices = new Map();
  const channels = new Set();
  const days = new Set();
  const hours = new Set();

  items.forEach(item => {
    const deviceId = item.dataset.deviceId || '';
    const deviceAlias = item.dataset.deviceAlias || '';
    const channelId = item.dataset.channelId || '';
    const tsRaw = item.dataset.recordingTs || '';

    if (deviceId) {
      const label = deviceAlias && deviceAlias !== deviceId
        ? `${deviceAlias} (${deviceId})`
        : deviceId;
      devices.set(deviceId, label);
    }
    if (channelId) channels.add(channelId);

    const ts = parseFloat(tsRaw);
    if (!Number.isNaN(ts) && ts > 0) {
      const d = new Date(ts * 1000);
      const day = d.toISOString().slice(0, 10);
      const hour = String(d.getHours()).padStart(2, '0');
      item.dataset.day = day;
      item.dataset.hour = hour;
      days.add(day);
      hours.add(hour);
    }
  });

  fillSelectMap(deviceSel, devices);
  fillSelect(channelSel, channels, (v) => `ch${v}`);
  fillSelect(daySel, days, (v) => v, true);
  fillSelect(hourSel, hours, (v) => `${v}:00`, true);

  const applyFilters = () => {
    const deviceVal = deviceSel.value;
    const channelVal = channelSel.value;
    const dayVal = daySel.value;
    const hourVal = hourSel.value;

    items.forEach(item => {
      const matchDevice = !deviceVal || item.dataset.deviceId === deviceVal;
      const matchChannel = !channelVal || item.dataset.channelId === channelVal;
      const matchDay = !dayVal || item.dataset.day === dayVal;
      const matchHour = !hourVal || item.dataset.hour === hourVal;
      const visible = matchDevice && matchChannel && matchDay && matchHour;
      item.classList.toggle('is-hidden', !visible);
    });
  };

  deviceSel.addEventListener('change', applyFilters);
  channelSel.addEventListener('change', applyFilters);
  daySel.addEventListener('change', applyFilters);
  hourSel.addEventListener('change', applyFilters);

  clearBtn.addEventListener('click', () => {
    deviceSel.value = '';
    channelSel.value = '';
    daySel.value = '';
    hourSel.value = '';
    applyFilters();
  });
}

function fillSelect(selectEl, values, labelFn, sortAsc = false) {
  const sorted = Array.from(values);
  sorted.sort((a, b) => {
    if (sortAsc) return String(a).localeCompare(String(b));
    return String(a).localeCompare(String(b));
  });

  sorted.forEach(val => {
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = labelFn(val);
    selectEl.appendChild(opt);
  });
}

function fillSelectMap(selectEl, mapValues) {
  const entries = Array.from(mapValues.entries())
    .sort((a, b) => a[1].localeCompare(b[1]));

  entries.forEach(([value, label]) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    selectEl.appendChild(opt);
  });
}
