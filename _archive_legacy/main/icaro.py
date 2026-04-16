"""
main/icaro.py — Orquestador Ligero de Ícaro
Controla el ciclo vital (escuchar, pensar, hablar/actuar).
"""

import os
import sys
import time
import subprocess

# 1. Configurar rutas para permitir ejecución directa
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from herramientas.audio import AudioManager
from logica.memorias import CerebroIcaro
from main.cerebro import Cerebro
from logica.plugins.copiloto_vscode import aplicar_cambios_vscode_plugin


class Icaro:
    def __init__(self):
        print("\n--- INICIALIZANDO ÍCARO ---")
        
        # 1. Componente de Audio (Micrófono, TTS, UI)
        self.audio = AudioManager()
        
        # 2. Componente Lógico (Memoria e IA)
        print("[Logica] Cargando motor de memoria...")
        self.memoria = CerebroIcaro()
        self.ia_habilitada = self.memoria.ia_habilitada
        
        # 3. Componente Enrutador Inteligente (El cerebro propiamente)
        print("[Logica] Configurando enrutador inteligente...")
        self.cerebro = Cerebro(self.memoria)
        
        # 4. Alias fonéticos para despertar al asistente
        self._alias_despertar = {"icaro", "si claro", "vicaro", "y creo", "y claro", "y caro", "claro", "y quiero"}
        
        # 5. Proceso UI Widget
        self.widget_process = None
        print("--- ÍCARO LISTO ---\n")

    def arrancar(self):
        """Mantiene activo el asistente escuchando y decidiendo."""
        # --- Lanzamiento de la Interfaz Visual (Garantizado al inicio) ---
        if self.widget_process is None or self.widget_process.poll() is not None:
            try:
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                ui_path = os.path.join(base_path, "ui", "widget.py")
                self.widget_process = subprocess.Popen([sys.executable, ui_path])
                print("[OK] Interfaz visual activada.")
            except Exception as e:
                print(f"[WARN] No se pudo lanzar la interfaz: {e}")

        self.audio.hablar("Sistemas inicializados. Motor cognitivo activado.")
        dormido = True
        activo = True

        while activo:
            try:
                if dormido:
                    self.audio.cambiar_estado_ui("sleeping")
                    print("\n[zzz] Modo de espera. (Di 'Icaro' para despertarme)...")
                else:
                    self.audio.cambiar_estado_ui("listening")
                    print("\n[INFO] Icaro te está escuchando...")

                comando = self.audio.escuchar(timeout_silencio=1.5, limite_segundo=15)

                # --- Silencio ---
                if not comando:
                    if not dormido:
                        # Se duerme si pasan 15s de inactividad
                        if time.time() - self.audio.ultima_interaccion > 15:
                            self.audio.hablar("Modo reposo.")
                            dormido = True
                    continue

                # El usuario dijo algo, actualizo inactividad
                self.audio.ultima_interaccion = time.time()

                # --- Verifica Copiloto Confirmaciones (Flujo Rápido, no pasa por IA) ---
                if any(p in comando for p in ("aplica", "hazlo", "acepto", "dale", "si claro", "si")):
                    res = aplicar_cambios_vscode_plugin(confirmado=True)
                    if res:
                        self.audio.hablar(res)
                        continue
                elif any(p in comando for p in ("cancela", "no", "detente", "abortar")):
                    res = aplicar_cambios_vscode_plugin(confirmado=False)
                    if res:
                        self.audio.hablar(res)
                        continue

                # --- Comando de Salida Rápida ---
                if any(p in comando for p in ("salir por completo", "apagar asistente", "terminar programa")):
                    self.audio.hablar("Entendido, apagando mis sistemas. Hasta la próxima.")
                    break

                # --- Evaluación modo Dormido ---
                if dormido:
                    if any(alias in comando for alias in self._alias_despertar):
                        self.audio.hablar("A tu servicio.")
                        dormido = False
                        self.audio.ultima_interaccion = time.time()

                        # Levantar widget si no existe
                        # Permite inline command: "icaro sube el volumen"
                        resto = comando
                        for alias in self._alias_despertar:
                            resto = resto.replace(alias, "")
                        resto = resto.strip()
                        
                        if len(resto) > 3:
                            self.audio.cambiar_estado_ui("thinking") # Visualizar procesamiento
                            respuesta = self.cerebro.procesar_comando(resto)
                            if respuesta:
                                self.audio.hablar(respuesta)
                    continue

                # --- Evaluación modo Despierto ---
                self.audio.cambiar_estado_ui("thinking") # Visualizar procesamiento
                respuesta = self.cerebro.procesar_comando(comando)
                if respuesta:
                    self.audio.hablar(respuesta)

            except KeyboardInterrupt:
                print("\n[INFO] Apagado forzado por el usuario (Ctrl+C).")
                break
                
        # Fin de ciclo
        print("\nDesconectando...")
        if self.widget_process:
            self.widget_process.terminate()
            print("[INFO] Interfaz visual cerrada.")
