// Funciones JavaScript para el cliente FTP Admin

// Auto-ocultar alertas después de 5 segundos
document.addEventListener("DOMContentLoaded", () => {
  const alerts = document.querySelectorAll(".alert")
  alerts.forEach((alert) => {
    setTimeout(() => {
      alert.style.opacity = "0"
      setTimeout(() => {
        alert.remove()
      }, 300)
    }, 5000)
  })
})

// Función para formatear bytes
function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return "0 Bytes"

  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"]

  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return Number.parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i]
}

// Función para formatear fecha
function formatDate(dateString) {
  const date = new Date(dateString)
  return date.toLocaleString("es-ES")
}

// Función para mostrar notificaciones
function showNotification(message, type = "info") {
  const notification = document.createElement("div")
  notification.className = `alert alert-${type}`
  notification.textContent = message

  const container = document.querySelector(".main-content")
  container.insertBefore(notification, container.firstChild)

  setTimeout(() => {
    notification.style.opacity = "0"
    setTimeout(() => {
      notification.remove()
    }, 300)
  }, 3000)
}

// Función para confirmar acciones
function confirmAction(message, callback) {
  if (confirm(message)) {
    callback()
  }
}

// Función para copiar texto al portapapeles
function copyToClipboard(text) {
  navigator.clipboard
    .writeText(text)
    .then(() => {
      showNotification("Copiado al portapapeles", "success")
    })
    .catch(() => {
      showNotification("Error al copiar", "error")
    })
}

// Función para actualizar timestamp
function updateTimestamps() {
  const timestamps = document.querySelectorAll("[data-timestamp]")
  timestamps.forEach((element) => {
    const timestamp = Number.parseInt(element.dataset.timestamp)
    const date = new Date(timestamp * 1000)
    element.textContent = formatDate(date)
  })
}

// Actualizar timestamps cada minuto
setInterval(updateTimestamps, 60000)

// Función para manejar errores de red
function handleNetworkError(error) {
  console.error("Error de red:", error)
  showNotification("Error de conexión con el servidor", "error")
}

// Función para hacer peticiones AJAX con manejo de errores
function fetchWithErrorHandling(url, options = {}) {
  return fetch(url, options)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      return response.json()
    })
    .catch(handleNetworkError)
}
