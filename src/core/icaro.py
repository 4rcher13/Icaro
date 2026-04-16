import time
import logging

from ..config.settings import WAKE_WORD
from .memory_manager import MemoryManager
from .command_processor import CommandProcessor
from ..services.audio_service import AudioService
from ..services.action_service import ActionService
from ..services.ai_service import AIService

logger = logging.getLogger(__name__)

class Icaro:
    """Orquestador principal del asistente. Maneja el ciclo de vida Unidireccional."""
    
    def __init__(self):
        logger.info("Iniciando subsistemas en arquitectura limpia...")
        # 1. Capa de Datos (Memoria)
        self.memory = MemoryManager()
        
        # 2. Servicios Base (Audio, IA, Acciones)
        self.audio = AudioService()
        self.action = ActionService()
        self.ai = AIService(self.memory) # IA se alimenta de memoria
        
        # 3. Router Lógico
        self.processor = CommandProcessor(self.ai, self.action)
        
        self.alias_despertar = WAKE_WORD
        self.dormido = True
        self.running = True

    def detener(self):
        """Detiene el bucle principal de forma segura."""
        self.running = False

    def iniciar(self):
        """Mantiene activo el asistente escuchando y decidiendo."""
        self.audio.hablar("Sistemas inicializados en modo nativo.")
        
        try:
            while self.running:
                try:
                    # Mostrar estado y escuchar
                    if self.dormido:
                        logger.debug("Modo de espera. (Di 'Icaro' para despertarme)...")
                    else:
                        logger.info("Ícaro escuchando activamente...")

                    comando = self.audio.escuchar()

                    # Manejo de silencios e inactividad
                    if not comando:
                        time.sleep(0.1)
                        if not self.dormido and (time.time() - self.audio.ultima_interaccion > 15):
                            self.audio.hablar("Entrando en reposo.")
                            self.dormido = True
                        continue

                    self.audio.ultima_interaccion = time.time()

                    # Comandos de Salida Directos (Cableados por seguridad)
                    if any(p in comando for p in ("salir por completo", "apagar asistente", "terminar", "salir")):
                        self.audio.hablar("Apagando módulos. Hasta la próxima.")
                        self.detener()
                        break

                    # Comportamiento según estado Dormido/Despierto
                    if self.dormido:
                        if any(alias in comando for alias in self.alias_despertar):
                            self.dormido = False
                            # Limpiar el nombre de Icaro del comando si se dijo en la misma frase
                            resto = comando
                            for al in self.alias_despertar:
                                resto = resto.replace(al, "")
                            resto = resto.strip()
                            
                            if len(resto) > 3:
                                self._ciclo_procesamiento(resto)
                            else:
                                self.audio.hablar("A tu servicio.")
                        continue
                    else:
                        self._ciclo_procesamiento(comando)

                except Exception as e:
                    logger.critical(f"Error Crítico Icaro Engine: {e}")
                    self.audio.hablar("Ocurrió un error grave en la secuencia principal.")
                    
        except KeyboardInterrupt:
            logger.info("Apagado forzado por el usuario (Ctrl+C).")
            self.detener()
            
        logger.info("Sistemas fuera de línea.")

    def _ciclo_procesamiento(self, comando: str):
        """Ejecuta un ciclo completo de: Guardar -> Procesar -> Hablar."""
        # 1. Guardar prompt usuario
        self.memory.guardar("user", comando)
        
        # 2. Procesar y ejecutar acción
        respuesta = self.processor.process(comando)
        
        # 3. Hablar y guardar respuesta modelo
        if respuesta:
            self.audio.hablar(respuesta)
            self.memory.guardar("model", respuesta)
