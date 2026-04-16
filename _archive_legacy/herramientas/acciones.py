"""
herramientas/acciones.py — Acciones del Sistema de Ícaro
Funciones puras: ejecutan una acción y retornan un string con el resultado.
Ninguna llama a hablar(). La IA usa el resultado para generar respuesta natural.
"""

import os
import sys
import time
import platform
import webbrowser
import datetime

try:
    import pyautogui
    import pyperclip
    import pygetwindow as gw
except ImportError as e:
    print(f"[ERROR] Dependencia faltante: {e.name}")
    print("Instala con: pip install pyautogui pyperclip pygetwindow")
    raise SystemExit(1)


# ===================== APLICACIONES =====================

def abrir_aplicacion(nombre_app):
    """Abre una aplicación por nombre. Retorna string con resultado."""
    sistema = platform.system()
    # Mapeo de nombres comunes a comandos
    apps = {
        "word": ("winword", "Microsoft Word"),
        "excel": ("excel", "Microsoft Excel"),
        "powerpoint": ("powerpnt", "PowerPoint"),
        "notepad": ("notepad", "Bloc de Notas"),
        "calculadora": ("calc", "Calculadora"),
        "explorador": ("explorer", "Explorador de Archivos"),
        "paint": ("mspaint", "Paint"),
        "cmd": ("cmd", "Símbolo del Sistema"),
        "terminal": ("wt", "Terminal de Windows"),
        "code": ("code", "Visual Studio Code"),
        "vscode": ("code", "Visual Studio Code"),
        "visual studio": ("code", "Visual Studio Code"),
        "visual studio code": ("code", "Visual Studio Code"),
    }

    nombre_lower = nombre_app.lower().strip()
    comando, nombre_real = apps.get(nombre_lower, (nombre_lower, nombre_app))

    try:
        if sistema == "Windows":
            os.system(f"start {comando}")
        elif sistema == "Darwin":
            import subprocess
            subprocess.Popen(["open", "-a", nombre_real])
        else:
            import subprocess
            subprocess.Popen(comando.split())
        return f"Se abrió {nombre_real} correctamente."
    except Exception as e:
        return f"No pude abrir {nombre_real}: {e}"


def cerrar_ventana(nombre_ventana):
    """Cierra una ventana visible que coincida con el nombre."""
    objetivo = nombre_ventana.lower().strip()
    encontrada = next(
        (v for v in gw.getAllWindows() if objetivo and objetivo in v.title.lower() and v.visible),
        None
    )

    if encontrada:
        try:
            encontrada.activate()
            time.sleep(0.2)
            # Pestaña de navegador → Ctrl+W, aplicación → Alt+F4
            es_navegador = any(k in encontrada.title.lower() for k in ("youtube", "edge", "chrome", "firefox"))
            if es_navegador:
                pyautogui.hotkey('ctrl', 'w')
            else:
                pyautogui.hotkey('alt', 'f4')
            return f"Se cerró {objetivo} correctamente."
        except Exception:
            return f"Problema al interactuar con la ventana de {objetivo}."
    else:
        # Intento especial para Word
        if platform.system() == "Windows" and "word" in objetivo:
            os.system("taskkill /f /im winword.exe")
            return "Se forzó el cierre de Word."
        return f"No encontré ninguna ventana de {objetivo}."


# ===================== VOLUMEN =====================

def control_volumen(accion):
    """Controla el volumen del sistema. accion: 'subir', 'bajar', 'silenciar'."""
    if platform.system() != "Windows":
        return "Control de volumen no disponible en este sistema."

    acciones_map = {
        "subir": ("volumeup", 5),
        "bajar": ("volumedown", 5),
        "silenciar": ("volumemute", 1),
    }

    tecla, repeticiones = acciones_map.get(accion.lower(), (None, 0))
    if tecla:
        for _ in range(repeticiones):
            pyautogui.press(tecla)
        return f"Volumen: acción '{accion}' ejecutada."
    return f"Acción de volumen '{accion}' no reconocida."


# ===================== WEB =====================

def buscar_google(query):
    """Busca algo en Google y abre el navegador."""
    if query.strip():
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return f"Se abrió la búsqueda de Google para: {query}"
    return "No se proporcionó texto para buscar."


def reproducir_youtube(query):
    """Busca y abre el primer video/música en YouTube directamente."""
    import urllib.request
    import re
    if query.strip():
        try:
            search_keyword = query.replace(' ', '+')
            html = urllib.request.urlopen("https://www.youtube.com/results?search_query=" + search_keyword)
            video_ids = re.findall(r"watch\?v=(\S{11})", html.read().decode())
            if video_ids:
                webbrowser.open("https://www.youtube.com/watch?v=" + video_ids[0])
                time.sleep(2) # Esperar a que abra
                return f"Reproduciendo el primer resultado de YouTube para: {query}"
            else:
                webbrowser.open(f"https://www.youtube.com/results?search_query={search_keyword}")
                return f"Se abrió la búsqueda de YouTube para: {query}"
        except Exception as e:
            webbrowser.open(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
            return f"Se abrió la búsqueda de YouTube para: {query} (no pude extraer el video directo)"
    else:
        webbrowser.open("https://www.youtube.com/")
        return "Se abrió YouTube en la página principal."


# ===================== ARCHIVOS Y CARPETAS =====================

def crear_carpeta(nombre):
    """Crea una carpeta en el escritorio."""
    if not nombre or not nombre.strip():
        nombre = "Nueva Carpeta"
    try:
        ruta = os.path.join(os.path.expanduser("~"), "Desktop", nombre.strip().title())
        os.makedirs(ruta, exist_ok=True)
        return f"Carpeta '{nombre}' creada en el escritorio."
    except Exception:
        return f"No tengo permisos para crear la carpeta '{nombre}'."


# ===================== TEXTO =====================

def escribir_texto(texto):
    """Escribe texto donde esté el cursor actualmente."""
    if texto.strip():
        time.sleep(0.4)
        try:
            pyperclip.copy(texto)
            pyautogui.hotkey('ctrl', 'v')
        except Exception:
            pyautogui.write(texto, interval=0.015)
        return f"Se escribió el texto: '{texto[:50]}...'" if len(texto) > 50 else f"Se escribió: '{texto}'"
    return "No se proporcionó texto para escribir."


# ===================== HORA Y FECHA =====================

def dar_hora_fecha(tipo):
    """Retorna la hora o fecha actual en español."""
    ahora = datetime.datetime.now()
    if tipo.lower() == "hora":
        h = ahora.strftime("%I:%M %p").replace("AM", "de la mañana").replace("PM", "de la tarde")
        return f"Son las {h}."
    else:
        dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        return f"Hoy es {dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]} del {ahora.year}."


# ===================== CONTROL MOUSE/TECLADO =====================

def hacer_click():
    """Hace un clic izquierdo donde esté el cursor."""
    try:
        pyautogui.click()
        return "Se hizo un click en la pantalla."
    except Exception as e:
        return f"Error al hacer click: {e}"

# ===================== ENERGÍA =====================

def suspender_equipo():
    """Suspende el equipo (Windows)."""
    if platform.system() == "Windows":
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "Equipo suspendido."
    return "Suspensión no disponible en este sistema."


# ===================== EJECUCIÓN DE COMANDOS DEL SISTEMA =====================

def ejecutar_comando_sistema(comando_os):
    """Ejecuta un comando de PowerShell/CMD en background."""
    import subprocess
    print(f"[EXEC] Ejecutando: {comando_os}")
    try:
        subprocess.Popen(
            ["powershell", "-Command", comando_os],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return f"Comando ejecutado: {comando_os}"
    except Exception as e:
        print(f"[ERROR Exec] {e}")
        return f"Fallo al ejecutar el comando: {e}"


def evaluar_peligro(comando_os):
    """Filtro de sensibilidad para acciones críticas. Retorna (es_peligroso, motivo)."""
    c = comando_os.lower()
    if any(p in c for p in ("rm ", "del ", "rd ", "rmdir ", "erase ", "format ")):
        return True, "eliminar archivos o directorios"
    if any(p in c for p in ("net user", "reg add", "net localgroup")):
        return True, "modificar configuraciones de usuario o sistema"
    if any(p in c for p in ("shutdown", "restart")):
        return True, "apagar o reiniciar el equipo"
    return False, ""


# ===================== ANÁLISIS DE CÓDIGO =====================

def analizar_archivo(nombre, cerebro):
    """Busca un archivo por nombre y lo analiza con el motor LOCAL de IA."""
    carpetas_ignorar = {"__pycache__", ".git", "venv", "node_modules", "data"}
    archivos = []
    for root, dirs, files in os.walk(os.getcwd()):
        dirs[:] = [d for d in dirs if d not in carpetas_ignorar]
        archivos.extend(os.path.join(root, f) for f in files if nombre.lower() in f.lower())

    if not archivos:
        return f"No encontré '{nombre}' en este proyecto."

    ruta = archivos[0]
    nombre_archivo = os.path.basename(ruta)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()
        return cerebro.inyectar_contexto_archivo(nombre_archivo, contenido)
    except Exception as e:
        print(f"[ERROR al leer archivo] {e}")
        return f"No pude leer {nombre_archivo}."


def escanear_proyecto(carpeta, cerebro):
    """Busca una carpeta de proyecto y la analiza con IA."""
    # Buscar la carpeta en ubicaciones comunes del usuario
    rutas_busqueda = [
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        os.getcwd(),
    ]

    carpeta_encontrada = None
    if carpeta and carpeta.strip():
        for ruta_base in rutas_busqueda:
            if not os.path.exists(ruta_base):
                continue
            for nombre_dir in os.listdir(ruta_base):
                ruta_completa = os.path.join(ruta_base, nombre_dir)
                if os.path.isdir(ruta_completa) and carpeta.lower() in nombre_dir.lower():
                    carpeta_encontrada = ruta_completa
                    break
            if carpeta_encontrada:
                break

    if not carpeta_encontrada:
        if not carpeta or not carpeta.strip():
            carpeta_encontrada = os.getcwd()
        else:
            return f"No encontré ninguna carpeta llamada '{carpeta}' en documentos o escritorio."

    return cerebro.escanear_proyecto(carpeta_encontrada)
