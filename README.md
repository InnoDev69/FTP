El usuario está pidiendo que cree un README para el proyecto FTP Dahua basado en el código que veo en el repositorio `InnoDev69/FTP`. 

## README del Proyecto FTP Dahua

Este es un sistema completo de gestión de videos para equipos DVR Dahua que incluye un servidor FTP personalizado y una interfaz web de administración. [1](#0-0) 

### Descripción

El sistema maneja automáticamente la recepción, organización y administración de archivos de video desde cámaras DVR Dahua a través de FTP. [2](#0-1)  Incluye dos componentes principales:

1. **Servidor FTP** (`server.py`) - Recibe videos de los DVR y los organiza automáticamente
2. **Interfaz Web** (`app.py`) - Panel de administración para gestionar y monitorear el sistema

### Características Principales

- **Organización Automática**: Los videos se organizan por fecha en estructura `organized/YYYY/MM/DD/` [3](#0-2) 
- **Base de Datos de Videos**: Mantiene registro de todos los videos con metadatos [4](#0-3) 
- **Interfaz Web**: Dashboard con estadísticas, gestión de videos y logs [5](#0-4) 
- **Limpieza Automática**: Elimina archivos antiguos según configuración [6](#0-5) 
- **Autenticación**: Sistema de login integrado con credenciales FTP [7](#0-6) 

### Instalación

1. **Instalar dependencias**:
   ```bash
   python dependencias.py
   ``` [8](#0-7) 

2. **Configurar credenciales** (por defecto):
   - Usuario: `dahua`
   - Contraseña: `dahua123` [9](#0-8) 

### Uso

#### Iniciar el Servidor FTP
```bash
python server.py [opciones]
```

**Opciones disponibles**:
- `--host`: IP para escuchar (default: 0.0.0.0)
- `--port`: Puerto FTP (default: 60000)
- `--user`: Usuario FTP (default: dahua)
- `--password`: Contraseña FTP (default: dahua123)
- `--keep-days`: Días de retención (default: 3) [10](#0-9) 

#### Iniciar la Interfaz Web
```bash
python app.py
```
Acceder a: http://localhost:5000 [11](#0-10) 

### Configuración DVR

Configurar el DVR Dahua para subir videos a:
- **Servidor**: IP del servidor
- **Puerto**: 60000 (o el configurado)
- **Usuario**: dahua
- **Contraseña**: dahua123

### Estructura de Archivos

```
dahua_videos/
├── organized/
│   └── YYYY/MM/DD/          # Videos organizados por fecha
├── video_database.txt       # Base de datos de videos
└── logs/
    └── ftp_server.log      # Logs del servidor
```

### Diagnóstico

Para solucionar problemas de conectividad:
```bash
python test.py --host <ip_servidor> --port <puerto>
``` [12](#0-11) 

### Dependencias

- `pyftpdlib`: Servidor FTP
- `flask`: Interfaz web
- `psutil`: Monitoreo del sistema [8](#0-7) 

### API Web

La interfaz web incluye endpoints REST:
- `/api/stats`: Estadísticas del sistema
- `/api/logs`: Logs recientes [13](#0-12) 

## Notes

El proyecto fue desarrollado por InnoDev69 según el historial de git blame visible en los archivos. El sistema está diseñado específicamente para equipos DVR Dahua pero puede adaptarse para otros sistemas que soporten FTP. La extracción de fechas de nombres de archivo utiliza el patrón regex específico de Dahua `(\d{8})(\d{6})` para archivos como `Casa_ch1_main_20250624010000_20250624020000.dav`.

Wiki pages you might want to explore:
- [Overview (InnoDev69/FTP)](/wiki/InnoDev69/FTP#1)