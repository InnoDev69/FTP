#!/usr/bin/env python3
"""
Herramienta de diagnóstico para problemas de conexión FTP Dahua
Identifica y soluciona problemas comunes de conectividad
"""

import socket
import ftplib
import sys
import time
import subprocess
import platform
from pathlib import Path
import argparse

class FTPDiagnostic:
    """Herramienta de diagnóstico FTP"""
    
    def __init__(self, host, port=2000, username="dahua", password="dahua123"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.results = []
    
    def log_result(self, test_name, status, message):
        """Registra resultado de prueba"""
        self.results.append({
            'test': test_name,
            'status': status,
            'message': message
        })
        
        status_icon = "✓" if status == "PASS" else "✗" if status == "FAIL" else "⚠"
        print(f"{status_icon} {test_name}: {message}")
    
    def test_network_connectivity(self):
        """Prueba conectividad de red básica"""
        print("\n=== PRUEBAS DE CONECTIVIDAD ===")
        
        # Test 1: Ping
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(['ping', '-n', '4', self.host], 
                                      capture_output=True, text=True, timeout=10)
            else:
                result = subprocess.run(['ping', '-c', '4', self.host], 
                                      capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.log_result("Ping", "PASS", f"Host {self.host} responde")
            else:
                self.log_result("Ping", "FAIL", f"Host {self.host} no responde")
                return False
        except Exception as e:
            self.log_result("Ping", "WARN", f"No se pudo hacer ping: {e}")
        
        # Test 2: Socket connection
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            
            if result == 0:
                self.log_result("Puerto TCP", "PASS", f"Puerto {self.port} abierto")
                return True
            else:
                self.log_result("Puerto TCP", "FAIL", f"Puerto {self.port} cerrado o filtrado")
                return False
        except Exception as e:
            self.log_result("Puerto TCP", "FAIL", f"Error conectando: {e}")
            return False
    
    def test_ftp_banner(self):
        """Prueba banner FTP"""
        print("\n=== PRUEBAS FTP BÁSICAS ===")
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((self.host, self.port))
            
            # Leer banner
            banner = sock.recv(1024).decode('utf-8').strip()
            sock.close()
            
            if banner.startswith('220'):
                self.log_result("Banner FTP", "PASS", f"Servidor responde: {banner}")
                return True
            else:
                self.log_result("Banner FTP", "FAIL", f"Banner inválido: {banner}")
                return False
                
        except Exception as e:
            self.log_result("Banner FTP", "FAIL", f"Error obteniendo banner: {e}")
            return False
    
    def test_ftp_login(self):
        """Prueba login FTP"""
        try:
            ftp = ftplib.FTP()
            ftp.set_debuglevel(0)  # Sin debug para prueba limpia
            ftp.connect(self.host, self.port, timeout=10)
            
            # Probar login
            ftp.login(self.username, self.password)
            
            # Obtener directorio actual
            pwd = ftp.pwd()
            
            # Listar archivos
            files = ftp.nlst()
            
            ftp.quit()
            
            self.log_result("Login FTP", "PASS", 
                          f"Login exitoso. Dir: {pwd}, Archivos: {len(files)}")
            return True
            
        except ftplib.error_perm as e:
            if "530" in str(e):
                self.log_result("Login FTP", "FAIL", f"Credenciales inválidas: {e}")
            else:
                self.log_result("Login FTP", "FAIL", f"Error de permisos: {e}")
            return False
        except ftplib.error_temp as e:
            self.log_result("Login FTP", "FAIL", f"Error temporal: {e}")
            return False
        except Exception as e:
            self.log_result("Login FTP", "FAIL", f"Error de conexión: {e}")
            return False
    
    def test_passive_mode(self):
        """Prueba modo pasivo FTP"""
        print("\n=== PRUEBAS DE MODO FTP ===")
        
        # Probar modo pasivo
        try:
            ftp = ftplib.FTP()
            ftp.connect(self.host, self.port, timeout=10)
            ftp.login(self.username, self.password)
            ftp.set_pasv(True)  # Modo pasivo
            
            files = ftp.nlst()
            ftp.quit()
            
            self.log_result("Modo Pasivo", "PASS", "Modo pasivo funciona")
        except Exception as e:
            self.log_result("Modo Pasivo", "FAIL", f"Error en modo pasivo: {e}")
        
        # Probar modo activo
        try:
            ftp = ftplib.FTP()
            ftp.connect(self.host, self.port, timeout=10)
            ftp.login(self.username, self.password)
            ftp.set_pasv(False)  # Modo activo
            
            files = ftp.nlst()
            ftp.quit()
            
            self.log_result("Modo Activo", "PASS", "Modo activo funciona")
        except Exception as e:
            self.log_result("Modo Activo", "FAIL", f"Error en modo activo: {e}")
    
    def test_firewall_ports(self):
        """Prueba puertos comunes que pueden estar bloqueados"""
        print("\n=== PRUEBAS DE FIREWALL ===")
        
        # Puertos pasivos comunes
        passive_ports = [20, 2000, 60000, 60001, 65000, 65534]
        
        for port in passive_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((self.host, port))
                sock.close()
                
                if result == 0:
                    self.log_result(f"Puerto {port}", "PASS", "Abierto")
                else:
                    self.log_result(f"Puerto {port}", "FAIL", "Cerrado/Filtrado")
            except:
                self.log_result(f"Puerto {port}", "FAIL", "Error de conexión")
    
    def test_server_running(self):
        """Verifica si hay un servidor FTP ejecutándose localmente"""
        print("\n=== VERIFICACIÓN SERVIDOR LOCAL ===")
        
        if self.host in ['localhost', '127.0.0.1', '0.0.0.0']:
            # Verificar si hay proceso python con servidor FTP
            try:
                if platform.system().lower() == "windows":
                    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                                          capture_output=True, text=True)
                else:
                    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                
                if 'ftp' in result.stdout.lower() or 'dahua' in result.stdout.lower():
                    self.log_result("Servidor Local", "PASS", "Proceso FTP detectado")
                else:
                    self.log_result("Servidor Local", "WARN", "No se detecta servidor FTP")
            except:
                self.log_result("Servidor Local", "WARN", "No se pudo verificar procesos")
    
    def suggest_solutions(self):
        """Sugiere soluciones basadas en los resultados"""
        print("\n=== SOLUCIONES SUGERIDAS ===")
        
        failed_tests = [r for r in self.results if r['status'] == 'FAIL']
        
        if not failed_tests:
            print("✓ Todas las pruebas pasaron. La conexión debería funcionar.")
            return
        
        solutions = []
        
        for test in failed_tests:
            if test['test'] == "Ping":
                solutions.append("• Verificar que la IP del servidor sea correcta")
                solutions.append("• Verificar conectividad de red")
                solutions.append("• Verificar que no haya firewall bloqueando")
            
            elif test['test'] == "Puerto TCP":
                solutions.append("• Verificar que el servidor FTP esté ejecutándose")
                solutions.append("• Verificar que el puerto 2000 esté abierto")
                solutions.append("• Verificar firewall del servidor")
            
            elif test['test'] == "Banner FTP":
                solutions.append("• El servicio en el puerto no es FTP")
                solutions.append("• Verificar configuración del servidor")
            
            elif test['test'] == "Login FTP":
                solutions.append("• Verificar usuario: 'dahua'")
                solutions.append("• Verificar contraseña: 'dahua123'")
                solutions.append("• Verificar configuración de usuarios en servidor")
            
            elif "Modo" in test['test']:
                solutions.append("• Configurar firewall para permitir puertos pasivos")
                solutions.append("• Verificar configuración de NAT/Router")
        
        # Eliminar duplicados
        solutions = list(set(solutions))
        
        for solution in solutions:
            print(solution)
        
        print(f"\n=== COMANDOS PARA SOLUCIONAR ===")
        print("1. Reiniciar servidor FTP:")
        print("   python ftp_server_dahua.py")
        print()
        print("2. Verificar puerto en uso:")
        if platform.system().lower() == "windows":
            print("   netstat -an | findstr :2000")
        else:
            print("   netstat -tulpn | grep :2000")
        print()
        print("3. Probar conexión manual:")
        print(f"   ftp {self.host}")
        print(f"   usuario: {self.username}")
        print(f"   contraseña: {self.password}")
    
    def run_all_tests(self):
        """Ejecuta todas las pruebas de diagnóstico"""
        print("=== DIAGNÓSTICO FTP DAHUA ===")
        print(f"Host: {self.host}:{self.port}")
        print(f"Usuario: {self.username}")
        print("=" * 40)
        
        # Ejecutar pruebas en orden
        self.test_server_running()
        
        if not self.test_network_connectivity():
            print("\n⚠ Problemas de conectividad básica detectados")
        
        if not self.test_ftp_banner():
            print("\n⚠ El servidor no responde como servidor FTP")
        else:
            self.test_ftp_login()
            self.test_passive_mode()
        
        self.test_firewall_ports()
        
        # Mostrar resumen
        print(f"\n=== RESUMEN ===")
        passed = len([r for r in self.results if r['status'] == 'PASS'])
        failed = len([r for r in self.results if r['status'] == 'FAIL'])
        warnings = len([r for r in self.results if r['status'] == 'WARN'])
        
        print(f"Pruebas exitosas: {passed}")
        print(f"Pruebas fallidas: {failed}")
        print(f"Advertencias: {warnings}")
        
        self.suggest_solutions()

def quick_server_test():
    """Prueba rápida para verificar si el servidor local está funcionando"""
    print("=== PRUEBA RÁPIDA SERVIDOR LOCAL ===")
    
    # Intentar iniciar un servidor de prueba
    try:
        import socket
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_socket.bind(('localhost', 2000))
        test_socket.listen(1)
        test_socket.close()
        print("✓ Puerto 2000 está disponible para servidor FTP")
        return True
    except OSError as e:
        if "Address already in use" in str(e):
            print("⚠ Puerto 2000 ya está en uso (posiblemente hay un servidor FTP ejecutándose)")
            return True
        elif "Permission denied" in str(e):
            print("✗ Sin permisos para usar puerto 2000 (ejecutar como administrador)")
            return False
        else:
            print(f"✗ Error verificando puerto 2000: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description='Diagnóstico FTP Dahua')
    parser.add_argument('host', nargs='?', default='localhost', help='IP del servidor FTP')
    parser.add_argument('-p', '--port', type=int, default=2000, help='Puerto FTP')
    parser.add_argument('-u', '--username', default='dahua', help='Usuario FTP')
    parser.add_argument('--password', default='dahua123', help='Contraseña FTP')
    parser.add_argument('--quick', action='store_true', help='Prueba rápida del servidor local')
    
    args = parser.parse_args()
    
    if args.quick:
        quick_server_test()
    else:
        diagnostic = FTPDiagnostic(args.host, args.port, args.username, args.password)
        diagnostic.run_all_tests()

if __name__ == "__main__":
    main()