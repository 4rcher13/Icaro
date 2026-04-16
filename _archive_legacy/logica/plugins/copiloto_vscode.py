"""
logica/plugins/copiloto_vscode.py — Copiloto IA para VS Code
Maneja la detección de archivos, lectura y modificación directa mediante portapapeles.
Usa a Gemini como cerebro para el análisis profundo.
"""

import os
import time

try:
    import pyperclip
    import pyautogui
    import pygetwindow as gw
except ImportError as e:
    print(f"[ERROR] Dependencia Copiloto faltante: {e.name}")
    print("Instala: pip install pyperclip pyautogui pygetwindow")
    raise SystemExit(1)


# Estado global del copiloto en esta sesión
_archivo_pendiente = None
_codigo_pendiente = None
_ventana_vscode = None


def _detectar_archivo_vscode():
    """Identifica el archivo activo en VS Code limpiando el título de la ventana y buscando en el workspace."""
    ventanas = [v for v in gw.getWindowsWithTitle('Visual Studio Code') if v.visible]
    if not ventanas:
        return None, None
        
    for v in ventanas:
        if " - " in v.title:
            # Limpiar el título: Quitar la bolita de "sucio" (●), " (Working Tree)", etc.
            limpio = v.title.replace("●", "").split(" - ")[0].strip()
            if " (" in limpio:
                limpio = limpio.split(" (")[0].strip()
            
            nombre_archivo = limpio
            
            # 1. Intento rápido: ¿Está en la raíz del proyecto actual?
            path_directo = os.path.join(os.getcwd(), nombre_archivo)
            if os.path.exists(path_directo):
                return path_directo, v
            
            # 2. Búsqueda profunda (con poda de carpetas pesadas)
            carpetas_ignorar = {"venv", ".git", "__pycache__", "node_modules", "data", "dist"}
            for root, dirs, files in os.walk(os.getcwd()):
                dirs[:] = [d for d in dirs if d not in carpetas_ignorar]
                if nombre_archivo in files:
                    return os.path.join(root, nombre_archivo), v
    return None, None


def copiloto_vscode_plugin(cerebro):
    """
    Flujo de Copiloto: Detecta -> Analiza -> Pide a Gemini sugerencias.
    Retorna el resumen (lo que hablará el asistente).
    """
    global _archivo_pendiente, _codigo_pendiente, _ventana_vscode
    
    ruta, ventana = _detectar_archivo_vscode()
    
    if not ruta:
        return "No logré detectar ningún archivo abierto en Visual Studio Code."

    nombre = os.path.basename(ruta)
    
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Obtener resumen y código mejorado de Gemini
        resumen, codigo_nuevo = cerebro.preparar_mejora_copiloto(nombre, contenido)
        
        if not codigo_nuevo:
            return resumen # Solo era un análisis (sin código nuevo)

        # Guardar en estado global para cuando el usuario confirme
        _archivo_pendiente = ruta
        _codigo_pendiente = codigo_nuevo
        _ventana_vscode = ventana
        
        return resumen + " ¿Desea que aplique estos cambios ahora mismo?"
        
    except Exception as e:
        print(f"[ERROR Copiloto] {e}")
        return "Tuve un fallo al intentar leer su entorno de desarrollo."


def aplicar_cambios_vscode_plugin(confirmado: bool):
    """
    Se invoca cuando el usuario dice 'hazlo' (confirmado=True) o 'cancela' (confirmado=False).
    Retorna lo que el asistente debe decir.
    """
    global _archivo_pendiente, _codigo_pendiente, _ventana_vscode
    
    if not _codigo_pendiente:
        return "" # Nada pendiente
        
    if not confirmado:
        _codigo_pendiente = None
        _archivo_pendiente = None
        return "Entendido. No aplicaré los cambios."
        
    try:
        # 1. Preparar portapapeles
        pyperclip.copy(_codigo_pendiente)
        
        # 2. Activar ventana de VS Code
        if _ventana_vscode:
            _ventana_vscode.activate()
            time.sleep(0.5)
            
            # 3. Simular sobreescritura (Seleccionar todo -> Pegar)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            # Opcional: Guardar el archivo
            pyautogui.hotkey('ctrl', 's')
            
            return "Cambios aplicados con éxito."
        else:
            return "Perdí el enlace con la ventana de VS Code."
            
    except Exception as e:
        print(f"[ERROR al sobreescribir] {e}")
        return "Hubo un error de automatización al inyectar el código."
    finally:
        _codigo_pendiente = None
        _archivo_pendiente = None
