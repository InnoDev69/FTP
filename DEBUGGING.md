# Debugging de Errores de Streaming

## Error: "DOMException: The fetching process for the media resource was aborted by the user agent"

Este error indica que el navegador no puede cargar el video desde el endpoint `/stream/<path>`.

## Causas Comunes

### 1. **Archivo no encontrado**
- El path pasado no corresponde a un archivo real
- La ruta tiene caracteres especiales no codificados
- El archivo fue eliminado del servidor

**Solución:** Verificar con `/api/video-check/PATH`

```bash
curl "http://localhost:5000/api/video-check/2026/05/23/archivo.dav"
```

### 2. **Permiso de lectura insuficiente**
- El servidor Flask no tiene permisos para leer el archivo
- El archivo está siendo accedido por otro proceso

**Solución:**
```bash
ls -la dahua_videos/2026/05/23/
chmod 644 dahua_videos/2026/05/23/*.dav
```

### 3. **Ruta con caracteres especiales**
- Espacios, acentos, etc. no están siendo codificados correctamente

**Solución:** El navegador ahora usa `encodeURIComponent()` automáticamente

### 4. **Conversión a MP4 fallando**
- FFmpeg no está instalado o no soporta el codec del video
- No hay espacio en disco para los archivos temporales

**Solución:**
```bash
ffmpeg -version  # Verificar instalacion
df -h /cache     # Verificar espacio disponible
```

## Herramientas de Debugging

### 1. **Consola de Debug en el Navegador**
- Se activa automáticamente cuando hay eventos de reproducción
- Presionar F12 (DevTools) y buscar la esquina inferior derecha
- Muestra logs en tiempo real de [Player]

### 2. **Logs en el Servidor**
```bash
tail -f /var/log/dahua-ftp.log  # Si existe archivo de log
# O revisar la salida estándar del servidor
```

### 3. **Endpoints de Debugging**

#### Verificar archivo
```bash
GET /api/video-check/<path>
```

Retorna:
```json
{
  "filepath": "2026/05/23/archivo.dav",
  "full_path": "/mnt/datos/proyectos/FTP/dahua_videos/2026/05/23/archivo.dav",
  "exists": true,
  "is_file": true,
  "file_size": 1048576000,
  "readable": true,
  "stream_url": "/stream/2026/05/23/archivo.dav"
}
```

#### Descargar configuración
```bash
GET /api/config/current
```

## Pasos para Resolver

### Paso 1: Verificar que el archivo existe
```javascript
// En consola del navegador
const path = "2026/05/23/archivo.dav";
fetch(`/api/video-check/${path}`)
  .then(r => r.json())
  .then(data => console.log(data));
```

### Paso 2: Revisar logs de [Player]
- Abrir DevTools (F12)
- Consola (Console tab)
- Hacer clic en un video para cargar
- Buscar logs que digan "[Player]"

### Paso 3: Verificar permisos en servidor
```bash
ls -la dahua_videos/
ls -la dahua_videos/2026/05/23/
chmod -R 755 dahua_videos/
```

### Paso 4: Reiniciar servidor
```bash
# Detener el servidor actual (Ctrl+C)
# Luego reiniciar
python run.py
```

## Información de Debugging Disponible

En la consola JavaScript ([Player]):
- `[Player] Slot X: device ch Y - path` - Archivo siendo cargado
- `[Player] Cargando: /stream/path` - URL del stream
- `[Player] Error en slot X:` - Error de carga con detalles
- `[Player] Carga abortada` - El usuario abortó o la conexión se cerró
- `[Player] Iniciando carga` - Comenzo a descargar
- `[Player] Video listo` - Se puede reproducir
- `[Player] Metadata cargada` - Se obtuvo duracion, fps, etc.

## Variables Globales en Navegador

```javascript
// Acceder desde consola del navegador
DEBUG_CONSOLE.logs       // Array de logs
DEBUG_CONSOLE.show()     // Mostrar consola
DEBUG_CONSOLE.clear()    // Limpiar logs
activeSlot               // Slot actualmente seleccionado (0-5)
slots                    // Estado de cada slot
```

## Casos de Uso Comunes

### El video carga pero no se reproduce
- Verificar que es un archivo MP4 válido
- Codec H.264 es obligatorio
- Probar descarga directa: `/download/path`

### El endpoint retorna 404
- Revisar que la ruta es correcta
- Verificar que el archivo está en `dahua_videos/`
- Usar `/api/video-check/path` para confirmar

### Conversión lentísima
- Archivos grandes requieren tiempo
- Ver tamaño en `/api/devices`
- Usar modo cache (default) - convierte completo una vez
- O usar `?mode=live` para empezar a reproducir inmediatamente

## Contacto del Desarrollador

Si persiste el error después de estos pasos:
1. Ejecutar `/api/video-check/path` para confirmar acceso
2. Revisar permisos de archivos
3. Verificar que FFmpeg está instalado: `ffmpeg -version`
