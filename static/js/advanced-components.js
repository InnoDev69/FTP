/**
 * Module: HeaderComponent
 * Reusable header component for pages with title, subtitle, and actions.
 */
class HeaderComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container);
    this.title = options.title || "Page";
    this.subtitle = options.subtitle || "";
    this.actions = options.actions || [];
    this.render();
  }

  render() {
    const actionsHTML = this.actions
      .map(action => {
        if (action.type === "button") {
          return `<button class="btn-${action.variant || 'secondary'}" onclick="${action.onclick}">${action.label}</button>`;
        }
        if (action.type === "link") {
          return `<a href="${action.href}" class="btn-${action.variant || 'secondary'}">${action.label}</a>`;
        }
        return "";
      })
      .join("");

    const html = `
      <div class="page-header">
        <div class="header-content">
          <h1 class="header-title">${escHTML(this.title)}</h1>
          ${this.subtitle ? `<p class="header-subtitle">${escHTML(this.subtitle)}</p>` : ""}
        </div>
        ${this.actions.length > 0 ? `<div class="header-actions">${actionsHTML}</div>` : ""}
      </div>
    `;
    this.element.innerHTML = html;
  }
}

/**
 * Module: StatsComponent
 * Grid of statistics cards with icons and values.
 */
class StatsComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container);
    this.stats = options.stats || [];
    this.render();
  }

  addStat(label, value, icon = "S", highlighted = false) {
    this.stats.push({ label, value, icon, highlighted });
    this.render();
  }

  render() {
    const statsHTML = this.stats
      .map(stat => `
        <div class="stat-card ${stat.highlighted ? "highlight" : ""}">
          <div class="stat-icon">${stat.icon}</div>
          <div class="stat-value">${escHTML(String(stat.value))}</div>
          <div class="stat-label">${escHTML(stat.label)}</div>
        </div>
      `)
      .join("");

    const html = `<div class="stats-grid">${statsHTML}</div>`;
    this.element.innerHTML = html;
  }
}

/**
 * Module: TableComponent
 * Dynamic table with sortable columns and pagination.
 */
class TableComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container);
    this.columns = options.columns || [];
    this.rows = options.rows || [];
    this.sortColumn = null;
    this.sortAsc = true;
    this.currentPage = 1;
    this.itemsPerPage = options.itemsPerPage || 10;
    this.render();
  }

  setData(rows) {
    this.rows = rows;
    this.currentPage = 1;
    this.render();
  }

  sortBy(columnKey) {
    if (this.sortColumn === columnKey) {
      this.sortAsc = !this.sortAsc;
    } else {
      this.sortColumn = columnKey;
      this.sortAsc = true;
    }
    this.render();
  }

  render() {
    // Sort data
    let sortedRows = [...this.rows];
    if (this.sortColumn) {
      sortedRows.sort((a, b) => {
        const aVal = a[this.sortColumn];
        const bVal = b[this.sortColumn];
        if (aVal < bVal) return this.sortAsc ? -1 : 1;
        if (aVal > bVal) return this.sortAsc ? 1 : -1;
        return 0;
      });
    }

    // Paginate
    const totalPages = Math.ceil(sortedRows.length / this.itemsPerPage);
    const start = (this.currentPage - 1) * this.itemsPerPage;
    const pageRows = sortedRows.slice(start, start + this.itemsPerPage);

    // Headers
    const headerHTML = this.columns
      .map(col => `
        <th onclick="tableSort('${col.key}')" style="cursor:pointer;">
          ${col.label}
          ${this.sortColumn === col.key ? (this.sortAsc ? "^" : "v") : ""}
        </th>
      `)
      .join("");

    // Rows
    const bodyHTML = pageRows
      .map(row => `
        <tr>
          ${this.columns.map(col => `<td>${escHTML(String(row[col.key] || "—"))}</td>`).join("")}
        </tr>
      `)
      .join("");

    // Pagination
    const paginationHTML =
      totalPages > 1
        ? `
      <div class="pagination">
        <button ${this.currentPage === 1 ? "disabled" : ""} onclick="prevPage()">Previous</button>
        <span>Page ${this.currentPage} of ${totalPages}</span>
        <button ${this.currentPage === totalPages ? "disabled" : ""} onclick="nextPage()">Next</button>
      </div>
    `
        : "";

    const html = `
      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr>${headerHTML}</tr></thead>
          <tbody>${bodyHTML}</tbody>
        </table>
        ${paginationHTML}
      </div>
    `;

    this.element.innerHTML = html;
  }
}

/**
 * Module: NavComponent
 * Sidebar/topbar navigation menu.
 */
class NavComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container);
    this.items = options.items || [];
    this.activeItem = options.activeItem || null;
    this.render();
  }

  addItem(label, href, icon = "", active = false) {
    this.items.push({ label, href, icon, active });
    if (active) this.activeItem = label;
    this.render();
  }

  setActive(label) {
    this.activeItem = label;
    this.render();
  }

  render() {
    const itemsHTML = this.items
      .map(
        item => `
      <a href="${item.href}" class="nav-item ${item.active || item.label === this.activeItem ? "active" : ""}">
        ${item.icon ? `<span class="nav-icon">${item.icon}</span>` : ""}
        <span>${escHTML(item.label)}</span>
      </a>
    `
      )
      .join("");

    const html = `<nav class="navigation">${itemsHTML}</nav>`;
    this.element.innerHTML = html;
  }
}

/**
 * Module: GridComponent
 * Responsive grid layout for cards or content.
 */
class GridComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container);
    this.items = options.items || [];
    this.columns = options.columns || 3;
    this.gap = options.gap || "16px";
    this.render();
  }

  addItem(content) {
    this.items.push(content);
    this.render();
  }

  setItems(items) {
    this.items = items;
    this.render();
  }

  render() {
    const itemsHTML = this.items.map(item => `<div class="grid-item">${item}</div>`).join("");

    const html = `
      <div class="grid-container" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: ${this.gap};">
        ${itemsHTML}
      </div>
    `;

    this.element.innerHTML = html;
  }
}

/**
 * Module: NotificationComponent
 * Toast notifications with auto-dismiss.
 */
class NotificationComponent extends UIComponent {
  constructor(options = {}) {
    super(options.container || document.body);
    this.position = options.position || "top-right";
    this.duration = options.duration || 4000;
  }

  show(message, type = "info") {
    const id = `notif-${Date.now()}`;
    const notif = document.createElement("div");
    notif.id = id;
    notif.className = `notification notification-${type} notification-${this.position}`;
    notif.innerHTML = `
      <div class="notification-content">
        <span class="notification-message">${escHTML(message)}</span>
        <button class="notification-close" onclick="this.parentElement.parentElement.remove()">x</button>
      </div>
    `;

    if (!document.getElementById("notifications-container")) {
      const container = document.createElement("div");
      container.id = "notifications-container";
      document.body.appendChild(container);
    }

    document.getElementById("notifications-container").appendChild(notif);

    if (this.duration > 0) {
      setTimeout(() => {
        const el = document.getElementById(id);
        if (el) el.remove();
      }, this.duration);
    }
  }

  success(msg) { this.show(msg, "success"); }
  error(msg) { this.show(msg, "error"); }
  warning(msg) { this.show(msg, "warning"); }
  info(msg) { this.show(msg, "info"); }
}

/**
 * Helper: escHTML
 */
function escHTML(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
