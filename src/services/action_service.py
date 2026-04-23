import os
import platform
import webbrowser
import time
import datetime
import subprocess
from typing import Dict, Any, Optional

pyautogui = None
pyperclip = None
gw = None

try:
    import pyautogui
    import pyperclip
    import pygetwindow as gw
except ImportError:
    print("[ActionService] Advertencia: Módulos de automatización GUI no instalados. (pip install pyautogui pyperclip pygetwindow)")


# Whitelist de aplicaciones permitidas por seguridad
ALLOWED_APPS: Dict[str, str] = {
    "word": "winword",
    "excel": "excel",
    "notepad": "notepad",
    "calculadora": "calc",
    "code": "code",
    "vscode": "code",
    "chrome": "chrome",
    "edge": "msedge",
    "spotify": "spotify",
}

class ActionService:
    """Ejecuta acciones en el sistema operativo sin lógica de cerebro ni audio."""
    
    def execute(self, config: Dict[str, Any]) -> str:
        """
        Recibe un diccionario con intent y los argumentos necesarios,
        y ejecuta la acción. Retorna el resultado string (si es necesario).
        """
        intent = config.get("intent")
        
        if not intent:
            return ""
            
        if intent == "buscar_google":
            return self._buscar_google(config.get("target", ""))
        elif intent == "control_volumen":
            return self._control_volumen(config.get("target", ""))
        elif intent == "reproducir_youtube":
            return self._reproducir_youtube(config.get("target", ""))
        elif intent == "cerrar_ventana":
            return self._cerrar_ventana(config.get("target", ""))
        elif intent in ("abrir_aplicacion", "open_app"):
            return self._abrir_aplicacion(config.get("target", ""))
        elif intent == "crear_carpeta":
            return self._crear_carpeta(config.get("target", ""))
        elif intent == "escribir_texto":
            return self._escribir_texto(config.get("target", ""))
        elif intent == "dar_hora_fecha":
            return self._dar_hora_fecha(config.get("target", "hora"))
        elif intent == "suspender_equipo":
            return self._suspender_equipo()
        elif intent == "hacer_click":
            return self._hacer_click()
            
        return f"Acción desconocida: {intent}"

    def _abrir_aplicacion(self, nombre_app: Optional[str]) -> str:
        """Abre una aplicación de forma segura usando una whitelist."""
        if not nombre_app: 
            return "Sin aplicación destino."
            
        nombre_lower = nombre_app.lower().strip()
        
        # Validación contra whitelist
        if nombre_lower not in ALLOWED_APPS:
            return f"Acceso denegado: '{nombre_app}' no está en la lista blanca de seguridad."
            
        comando = ALLOWED_APPS[nombre_lower]
        sistema = platform.system()
        
        try:
            if sistema == "Windows":
                # Usamos shell=True solo porque los comandos vienen de una whitelist controlada
                # 'start' es un comando interno de cmd.exe
                subprocess.run(["cmd", "/c", "start", comando], shell=False)
            elif sistema == "Darwin":
                subprocess.run(["open", "-a", comando], check=True)
            else:
                subprocess.run([comando], check=True, start_new_session=True)
            return f"Se abrió {nombre_app}"
        except Exception as e:
            return f"Error al abrir {nombre_app}: {str(e)}"

    def _cerrar_ventana(self, nombre_ventana: str) -> str:
        objetivo = nombre_ventana.lower().strip()
        try:
            if gw:
                encontrada = next((v for v in gw.getAllWindows() if objetivo and objetivo in v.title.lower() and v.visible), None)
            else:
                encontrada = None
                
            if encontrada and pyautogui:
                encontrada.activate()
                time.sleep(0.2)
                es_navegador = any(k in encontrada.title.lower() for k in ("youtube", "edge", "chrome", "firefox"))
                if es_navegador: pyautogui.hotkey('ctrl', 'w')
                else: pyautogui.hotkey('alt', 'f4')
                return f"Se cerró {objetivo}."
            return f"No encontré ventana {objetivo}."
        except Exception as e:
            return f"Error al cerrar ventana: {str(e)}"

    def _control_volumen(self, accion: str) -> str:
        if platform.system() != "Windows": return "No disponible"
        mapa = {"subir": ("volumeup", 5), "bajar": ("volumedown", 5), "silenciar": ("volumemute", 1)}
        tecla, rep = mapa.get(accion.lower(), (None, 0))
        if tecla and pyautogui:
            try:
                for _ in range(rep): pyautogui.press(tecla)
                return "listo"
            except Exception:
                pass
        return "error de volumen"

    def _buscar_google(self, query: str) -> str:
        if query:
            # Sanitización básica de URL
            query_sanitizada = query.replace(' ', '+').replace('"', '').replace("'", "")
            webbrowser.open(f"https://www.google.com/search?q={query_sanitizada}")
        return "búsqueda abierta"

    def _reproducir_youtube(self, query: str) -> str:
        if query:
            import urllib.request
            import re
            try:
                keyword = query.replace(' ', '+').replace('"', '')
                html = urllib.request.urlopen("https://www.youtube.com/results?search_query=" + keyword)
                video_ids = re.findall(r"watch\?v=(\S{11})", html.read().decode())
                if video_ids:
                    webbrowser.open("https://www.youtube.com/watch?v=" + video_ids[0])
                else:
                    webbrowser.open(f"https://www.youtube.com/results?search_query={keyword}")
            except Exception:
                webbrowser.open(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
        else:
            webbrowser.open("https://www.youtube.com/")
        return "youtube abierto"

    def _crear_carpeta(self, nombre: str) -> str:
        if not nombre: nombre = "Nueva Carpeta"
        # Sanitizar nombre para evitar path traversal
        nombre_seguro = "".join(c for c in nombre if c.isalnum() or c in (' ', '-', '_')).strip()
        ruta = os.path.join(os.path.expanduser("~"), "Desktop", nombre_seguro.title())
        os.makedirs(ruta, exist_ok=True)
        return f"Carpeta '{nombre_seguro}' creada en el escritorio."

    def _escribir_texto(self, texto: str) -> str:
        if texto and pyperclip and pyautogui:
            time.sleep(0.4)
            try:
                pyperclip.copy(texto)
                pyautogui.hotkey('ctrl', 'v')
            except Exception:
                pyautogui.write(texto, interval=0.015)
        return "escrito"

    def _dar_hora_fecha(self, tipo: str) -> str:
        ahora = datetime.datetime.now()
        if tipo.lower() == "hora":
            return f"Son las {ahora.strftime('%I:%M %p')}."
        return f"Hoy es {ahora.day} del {ahora.month} del {ahora.year}."

    def _hacer_click(self) -> str:
        try: 
            if pyautogui: pyautogui.click()
        except Exception: 
            pass
        return "click"
    
    def _suspender_equipo(self) -> str:
        if platform.system() == "Windows":
            # Comando de sistema seguro
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], shell=False)
        return "equipo suspendido"
