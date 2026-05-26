/**
 * debug-console.js
 * 
 * Consola flotante de debugging para la página
 * Captura logs y los muestra en tiempo real
 */

const DEBUG_CONSOLE = {
  enabled: false,
  logs: [],
  maxLogs: 50,

  init() {
    // Crear HTML
    const html = `
      <div id="debug-panel" style="
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 400px;
        max-height: 300px;
        background: #111;
        border: 2px solid #0f9eff;
        border-radius: 8px;
        padding: 12px;
        font-family: monospace;
        font-size: 11px;
        color: #0f9eff;
        z-index: 99999;
        display: none;
        flex-direction: column;
        box-shadow: 0 0 20px rgba(15, 158, 255, 0.3);
      ">
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px solid #0f9eff; padding-bottom: 8px;">
          <span>Debug Console</span>
          <button onclick="DEBUG_CONSOLE.clear()" style="background: none; border: none; color: #0f9eff; cursor: pointer;">Clear</button>
        </div>
        <div id="debug-logs" style="
          flex: 1;
          overflow-y: auto;
          overflow-x: hidden;
          padding: 8px 0;
          border: 1px solid #0f9eff;
          margin-bottom: 8px;
        "></div>
        <button onclick="DEBUG_CONSOLE.toggle()" style="
          background: #0f9eff;
          color: #111;
          border: none;
          padding: 6px;
          border-radius: 4px;
          cursor: pointer;
          font-weight: bold;
          font-size: 10px;
        ">Hide</button>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', html);

    // Override console.log para capturar [Player] logs
    const originalLog = console.log;
    console.log = (...args) => {
      originalLog(...args);
      const msg = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
      if (msg.includes('[Player]')) {
        this.add(msg, 'info');
      }
    };

    // Capturar console.error
    const originalError = console.error;
    console.error = (...args) => {
      originalError(...args);
      const msg = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
      if (msg.includes('[Player]')) {
        this.add(msg, 'error');
      }
    };

    // Capturar console.warn
    const originalWarn = console.warn;
    console.warn = (...args) => {
      originalWarn(...args);
      const msg = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
      if (msg.includes('[Player]')) {
        this.add(msg, 'warning');
      }
    };

    this.enabled = true;
    console.log('[DEBUG] Consola iniciada');
  },

  add(message, type = 'info') {
    const colors = {
      'info': '#0f9eff',
      'error': '#ef4444',
      'warning': '#f59e0b'
    };

    this.logs.push({ message, type, time: new Date().toLocaleTimeString() });
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    this.render();
  },

  render() {
    const logsEl = document.getElementById('debug-logs');
    if (!logsEl) return;

    logsEl.innerHTML = this.logs
      .map(
        log => `
      <div style="color: ${log.type === 'error' ? '#ef4444' : log.type === 'warning' ? '#f59e0b' : '#0f9eff'}; margin: 4px 0; word-break: break-all;">
        <span style="color: #777; margin-right: 8px;">[${log.time}]</span>${log.message}
      </div>
    `
      )
      .join('');

    logsEl.scrollTop = logsEl.scrollHeight;
  },

  clear() {
    this.logs = [];
    this.render();
  },

  toggle() {
    const panel = document.getElementById('debug-panel');
    if (panel) {
      const isVisible = panel.style.display !== 'none';
      panel.style.display = isVisible ? 'none' : 'flex';
      localStorage.setItem('debug-console-visible', !isVisible);
    }
  },

  show() {
    const panel = document.getElementById('debug-panel');
    if (panel) {
      panel.style.display = 'flex';
      localStorage.setItem('debug-console-visible', true);
    }
  }
};

// Inicializar cuando el DOM está listo
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    DEBUG_CONSOLE.init();
    // Mostrar si estaba visible antes
    if (localStorage.getItem('debug-console-visible') === 'true') {
      DEBUG_CONSOLE.show();
    }
  });
} else {
  DEBUG_CONSOLE.init();
}

// Hacer disponible globalmente
window.DEBUG_CONSOLE = DEBUG_CONSOLE;
