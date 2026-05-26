/**
 * ui-components.js — Sistema de componentes reutilizables
 * Proporciona constructores para cards, modales, formularios, etc.
 */

class UIComponent {
  /**
   * Componente base para UI reutilizable
   */
  constructor(selector) {
    this.container = typeof selector === 'string' 
      ? document.querySelector(selector) 
      : selector;
    if (!this.container) throw new Error(`Selector no encontrado: ${selector}`);
  }

  clear() {
    this.container.innerHTML = '';
    return this;
  }

  append(element) {
    if (typeof element === 'string') {
      this.container.insertAdjacentHTML('beforeend', element);
    } else {
      this.container.appendChild(element);
    }
    return this;
  }

  html(content) {
    this.container.innerHTML = content;
    return this;
  }

  show() {
    this.container.style.display = '';
    return this;
  }

  hide() {
    this.container.style.display = 'none';
    return this;
  }

  on(event, selector, callback) {
    this.container.addEventListener(event, (e) => {
      if (e.target.matches(selector)) {
        callback.call(e.target, e);
      }
    });
    return this;
  }

  addClass(cls) {
    this.container.classList.add(cls);
    return this;
  }

  removeClass(cls) {
    this.container.classList.remove(cls);
    return this;
  }
}

class CardComponent extends UIComponent {
  /**
   * Card reutilizable con header, contenido y footer opcionales
   */
  constructor(selector) {
    super(selector);
    this.cardHTML = '';
  }

  title(text) {
    this.title_text = text;
    return this;
  }

  subtitle(text) {
    this.subtitle_text = text;
    return this;
  }

  content(html) {
    this.content_html = html;
    return this;
  }

  footer(html) {
    this.footer_html = html;
    return this;
  }

  render() {
    let html = `<div class="card">`;
    
    if (this.title_text) {
      html += `<div class="card-header">
        <h3 class="card-title">${escHTML(this.title_text)}</h3>
        ${this.subtitle_text ? `<p class="card-subtitle">${escHTML(this.subtitle_text)}</p>` : ''}
      </div>`;
    }

    if (this.content_html) {
      html += `<div class="card-content">${this.content_html}</div>`;
    }

    if (this.footer_html) {
      html += `<div class="card-footer">${this.footer_html}</div>`;
    }

    html += `</div>`;
    return this.html(html);
  }
}

class FormComponent extends UIComponent {
  /**
   * Formulario dinámico a partir de campos
   */
  constructor(selector) {
    super(selector);
    this.fields = [];
  }

  addField(name, label, type = 'text', value = '', options = {}) {
    this.fields.push({ name, label, type, value, options });
    return this;
  }

  render() {
    let html = '<form class="form">';
    
    for (const f of this.fields) {
      const id = `field-${f.name}`;
      html += `<div class="form-group">
        <label for="${id}" class="form-label">${escHTML(f.label)}</label>`;

      if (f.type === 'text' || f.type === 'email' || f.type === 'number') {
        html += `<input type="${f.type}" id="${id}" name="${f.name}" 
                  value="${escHTML(f.value)}" class="form-input" 
                  placeholder="${escHTML(f.options.placeholder || '')}">`;
      } else if (f.type === 'select') {
        html += `<select id="${id}" name="${f.name}" class="form-select">`;
        for (const [val, label] of Object.entries(f.options.choices || {})) {
          const sel = val === f.value ? 'selected' : '';
          html += `<option value="${escHTML(val)}" ${sel}>${escHTML(label)}</option>`;
        }
        html += `</select>`;
      } else if (f.type === 'checkbox') {
        const chk = f.value ? 'checked' : '';
        html += `<input type="checkbox" id="${id}" name="${f.name}" ${chk} class="form-checkbox">`;
      } else if (f.type === 'textarea') {
        html += `<textarea id="${id}" name="${f.name}" class="form-textarea" 
                  rows="${f.options.rows || 4}">${escHTML(f.value)}</textarea>`;
      }

      html += `</div>`;
    }

    html += '</form>';
    return this.html(html);
  }

  getValues() {
    const form = this.container.querySelector('form');
    const data = {};
    for (const f of this.fields) {
      const input = form.elements[f.name];
      if (input) {
        data[f.name] = input.type === 'checkbox' ? input.checked : input.value;
      }
    }
    return data;
  }
}

class ModalComponent extends UIComponent {
  /**
   * Modal reutilizable con backdrop y contenido
   */
  constructor(containerId = null) {
    const id = containerId || `modal-${Math.random().toString(36).substr(2, 9)}`;
    let container = document.getElementById(id);
    
    if (!container) {
      container = document.createElement('div');
      container.id = id;
      container.className = 'modal-backdrop';
      container.innerHTML = '<div class="modal-content"></div>';
      document.body.appendChild(container);
    }
    
    super(container);
    this.contentEl = container.querySelector('.modal-content');
  }

  title(text) {
    this.title_text = text;
    return this;
  }

  content(html) {
    this.content_html = html;
    return this;
  }

  buttons(btns) {
    this.buttons_list = btns;
    return this;
  }

  render() {
    let html = `<div class="modal">
      ${this.title_text ? `<div class="modal-header"><h2>${escHTML(this.title_text)}</h2></div>` : ''}
      <div class="modal-body">${this.content_html || ''}</div>`;

    if (this.buttons_list) {
      html += `<div class="modal-footer">`;
      for (const btn of this.buttons_list) {
        html += `<button class="btn btn-${btn.variant || 'secondary'}" 
                  data-action="${btn.action}">${escHTML(btn.label)}</button>`;
      }
      html += `</div>`;
    }

    html += `</div>`;
    this.contentEl.innerHTML = html;
    return this;
  }

  show() {
    this.container.style.display = 'flex';
    return this;
  }

  hide() {
    this.container.style.display = 'none';
    return this;
  }

  onButton(action, callback) {
    const btn = this.contentEl.querySelector(`[data-action="${action}"]`);
    if (btn) btn.addEventListener('click', callback);
    return this;
  }
}

class LoaderComponent extends UIComponent {
  /**
   * Indicador de carga
   */
  constructor(selector) {
    super(selector);
  }

  show(message = 'Cargando...') {
    this.container.innerHTML = `
      <div class="loader-wrapper">
        <div class="loader-spinner"></div>
        <p>${escHTML(message)}</p>
      </div>
    `;
    return this;
  }

  hide() {
    this.container.innerHTML = '';
    return this;
  }
}

class AlertComponent extends UIComponent {
  /**
   * Alerta/notificación
   */
  constructor(type = 'info', message = '') {
    const id = `alert-${Math.random().toString(36).substr(2, 9)}`;
    let container = document.getElementById(id);
    
    if (!container) {
      container = document.createElement('div');
      container.id = id;
      document.body.appendChild(container);
    }
    
    super(container);
    this.type = type;
    this.message = message;
  }

  show(duration = 5000) {
    const html = `
      <div class="alert alert-${this.type}">
        <span>${escHTML(this.message)}</span>
        <button class="alert-close">&times;</button>
      </div>
    `;
    this.container.innerHTML = html;
    this.container.style.display = 'block';

    const closeBtn = this.container.querySelector('.alert-close');
    closeBtn?.addEventListener('click', () => this.hide());

    if (duration > 0) {
      setTimeout(() => this.hide(), duration);
    }

    return this;
  }

  hide() {
    this.container.innerHTML = '';
    this.container.style.display = 'none';
    return this;
  }
}

// Funciones auxiliares
function escHTML(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escJS(s) {
  return String(s)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n');
}
