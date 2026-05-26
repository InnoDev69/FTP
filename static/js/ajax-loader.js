/**
 * ajax-loader.js — Gestor centralizado de peticiones AJAX
 * Maneja requests/responses, errores y estados de carga
 */

class AjaxManager {
  static async fetch(url, options = {}) {
    const {
      method = 'GET',
      data = null,
      headers = {},
      onLoading = null,
      onSuccess = null,
      onError = null,
    } = options;

    const finalHeaders = {
      'Content-Type': 'application/json',
      ...headers,
    };

    const config = {
      method,
      headers: finalHeaders,
    };

    if (data && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
      config.body = JSON.stringify(data);
    }

    try {
      if (onLoading) onLoading();

      const response = await fetch(url, config);
      const json = await response.json();

      if (!response.ok) {
        const error = json.error || `Error ${response.status}`;
        if (onError) onError(error);
        throw new Error(error);
      }

      if (onSuccess) onSuccess(json);
      return json;
    } catch (err) {
      if (onError) onError(err.message);
      throw err;
    }
  }

  static async get(url, options = {}) {
    return this.fetch(url, { method: 'GET', ...options });
  }

  static async post(url, data, options = {}) {
    return this.fetch(url, { method: 'POST', data, ...options });
  }

  static async put(url, data, options = {}) {
    return this.fetch(url, { method: 'PUT', data, ...options });
  }

  static async patch(url, data, options = {}) {
    return this.fetch(url, { method: 'PATCH', data, ...options });
  }

  static async delete(url, options = {}) {
    return this.fetch(url, { method: 'DELETE', ...options });
  }
}

/**
 * PageLoader — Cargador AJAX de páginas dinámicas
 */
class PageLoader {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.currentPage = null;
    this.loader = new LoaderComponent(this.container);
  }

  async load(url, callback = null) {
    try {
      this.loader.show('Cargando...');
      
      const response = await fetch(url);
      const html = await response.text();
      
      this.container.innerHTML = html;
      this.currentPage = url;
      
      // Re-ejecutar scripts inline
      for (const script of this.container.querySelectorAll('script')) {
        if (!script.src) {
          eval(script.textContent);
        }
      }
      
      if (callback) callback();
    } catch (err) {
      this.loader.hide();
      new AlertComponent('error', `Error cargando ${url}: ${err.message}`).show();
    }
  }

  reload() {
    if (this.currentPage) {
      return this.load(this.currentPage);
    }
  }
}

/**
 * DataGrid — Tabla dinámica con AJAX
 */
class DataGrid {
  constructor(selector, options = {}) {
    this.container = document.querySelector(selector);
    this.columns = options.columns || [];
    this.data = [];
    this.apiUrl = options.apiUrl || '';
    this.onRowClick = options.onRowClick || null;
  }

  async loadData() {
    try {
      const response = await AjaxManager.get(this.apiUrl);
      this.data = response.data || [];
      this.render();
    } catch (err) {
      new AlertComponent('error', `Error cargando datos: ${err.message}`).show();
    }
  }

  render() {
    let html = '<table class="data-grid"><thead><tr>';
    
    for (const col of this.columns) {
      html += `<th>${escHTML(col.label)}</th>`;
    }
    
    html += '</tr></thead><tbody>';

    for (const row of this.data) {
      html += '<tr class="data-grid-row">';
      for (const col of this.columns) {
        const value = this._getNestedValue(row, col.field);
        html += `<td>${escHTML(String(value || '-'))}</td>`;
      }
      html += '</tr>';
    }

    html += '</tbody></table>';
    this.container.innerHTML = html;

    if (this.onRowClick) {
      this.container.querySelectorAll('.data-grid-row').forEach((row, idx) => {
        row.addEventListener('click', () => this.onRowClick(this.data[idx]));
      });
    }
  }

  _getNestedValue(obj, path) {
    return path.split('.').reduce((curr, prop) => curr?.[prop], obj);
  }
}

/**
 * TabSystem — Sistema de tabs reutilizable
 */
class TabSystem {
  constructor(selector) {
    this.container = document.querySelector(selector);
    this.tabs = [];
    this.activeTab = null;
  }

  addTab(id, label, content) {
    this.tabs.push({ id, label, content });
    return this;
  }

  render() {
    let html = '<div class="tab-system">';
    
    html += '<div class="tab-buttons">';
    for (const tab of this.tabs) {
      html += `<button class="tab-btn" data-tab="${tab.id}">${escHTML(tab.label)}</button>`;
    }
    html += '</div>';

    html += '<div class="tab-contents">';
    for (const tab of this.tabs) {
      html += `<div class="tab-content" id="tab-${tab.id}">${tab.content}</div>`;
    }
    html += '</div>';

    html += '</div>';
    this.container.innerHTML = html;

    // Event listeners
    this.container.querySelectorAll('.tab-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const tabId = e.target.dataset.tab;
        this.activate(tabId);
      });
    });

    if (this.tabs.length > 0) {
      this.activate(this.tabs[0].id);
    }

    return this;
  }

  activate(tabId) {
    this.container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    this.container.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    this.container.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');
    this.container.querySelector(`#tab-${tabId}`)?.classList.add('active');

    this.activeTab = tabId;
  }
}
