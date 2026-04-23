import time
import logging

from typing import Optional
from ..config.settings import WAKE_WORD
from .memory_manager import MemoryManager
from .command_processor import CommandProcessor
from .telemetry import Telemetry
from ..services.audio_service import AudioService
from ..services.action_service import ActionService
from ..services.ai_service import AIService
from ..utils.text_utils import normalize_text
from .protocols import AudioProtocol, AIProtocol, MemoryProtocol, ActionProtocol, TelemetryProtocol

logger = logging.getLogger(__name__)


class Icaro:
    """
    Orquestador principal del asistente Ícaro.

    Máquina de estados explícita con 6 estados:
        initializing → sleeping → listening → thinking → speaking → error

    Cada transición emite telemetría UDP al widget UI.
    """

    def __init__(
        self, 
        silent: bool = False, 
        no_ai: bool = False,
        audio_service: Optional[AudioProtocol] = None,
        ai_service: Optional[AIProtocol] = None,
        memory_manager: Optional[MemoryProtocol] = None,
        action_service: Optional[ActionProtocol] = None,
        telemetry_service: Optional[TelemetryProtocol] = None
    ):
        # 0. Telemetría y Configuración
        self.telemetry = telemetry_service or Telemetry()
        self.telemetry.send("initializing")

        logger.info("Iniciando subsistemas con Inyección de Dependencias...")
        self.silent = silent
        self.no_ai = no_ai

        # 1. Capa de datos
        self.memory = memory_manager or MemoryManager()

        # 2. Servicios base
        self.audio = audio_service or AudioService()
        self.action = action_service or ActionService()
        self.ai = ai_service or AIService(self.memory)

        if self.no_ai:
            if hasattr(self.ai, 'ia_habilitada'):
                self.ai.ia_habilitada = False
            if hasattr(self.ai, 'ollama_habilitado'):
                self.ai.ollama_habilitado = False
            logger.info("Modo --no-ai activo: solo comandos locales.")

        # 3. Router lógico
        self.processor = CommandProcessor(
            self.ai, 
            self.action, 
            use_rapidfuzz=True
        )

        # 4. Feature Flags (Rollback capability)
        self.flags = {
            "USE_RAPIDFUZZ": True,
            "BATCH_SAVE": True,
        }

        self.alias_despertar = WAKE_WORD
        self.is_sleeping = True
        self.running = True

    # ------------------------------------------------------------------
    # Wake-word helpers
    # ------------------------------------------------------------------

    def _wake_word_detected(self, command: str) -> bool:
        """Detecta wake word ignorando tildes y mayúsculas."""
        cmd_norm = normalize_text(command)
        return any(normalize_text(alias) in cmd_norm for alias in self.alias_despertar)

    def _remove_wake_word(self, command: str) -> str:
        """Elimina aliases del wake word del texto (versión robusta)."""
        result = command
        for alias in self.alias_despertar:
            # Eliminar tanto con tilde como sin ella
            result = result.replace(alias, "").replace(normalize_text(alias), "")
        return result.strip()

    def _remove_wake_word(self, command: str) -> str:
        """Elimina aliases del wake word del texto (versión robusta)."""
        result = command
        for alias in self.alias_despertar:
            # Eliminar tanto con tilde como sin ella
            result = result.replace(alias, "").replace(self._normalizar(alias), "")
        return result.strip()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def detener(self) -> None:
        """Detiene el bucle principal de forma segura."""
        self.running = False

    def iniciar(self) -> None:
        """Bucle principal: escucha, decide y actúa."""
        if not self.silent:
            self.telemetry.send("speaking", "", "Sistemas inicializados en modo nativo.")
            self.audio.hablar("Sistemas inicializados en modo nativo.")

        self.telemetry.send("sleeping")

        try:
            while self.running:
                try:
                    # ── Emitir estado de escucha ──────────────────────
                    if self.is_sleeping:
                        logger.debug("Modo de espera. (Di 'Ícaro' para despertarme)...")
                        self.telemetry.send("sleeping")
                    else:
                        logger.info("Ícaro escuchando activamente...")
                        self.telemetry.send("listening")

                    comando = self.audio.escuchar()

                    # ── Silencio / inactividad ────────────────────────
                    if not comando:
                        time.sleep(0.1)
                        inactive = (
                            not self.is_sleeping
                            and (time.time() - self.audio.ultima_interaccion > 15)
                        )
                        if inactive:
                            self.telemetry.send("speaking", "", "Entrando en reposo.")
                            self.audio.hablar("Entrando en reposo.")
                            self.is_sleeping = True
                            self.telemetry.send("sleeping")
                        continue

                    self.audio.ultima_interaccion = time.time()

                    # ── Mostrar SIEMPRE lo que se interpretó (para feedback del usuario) ──
                    if self.is_sleeping:
                        self.telemetry.send("sleeping", comando)
                    else:
                        self.telemetry.send("listening", comando)

                    # ── Comandos de salida (hardcoded por seguridad) ──
                    if any(
                        p in comando
                        for p in ("salir por completo", "apagar asistente", "terminar", "salir")
                    ):
                        self.telemetry.send("speaking", comando, "Apagando módulos. Hasta la próxima.")
                        self.audio.hablar("Apagando módulos. Hasta la próxima.")
                        self.detener()
                        break

                    # ── Máquina de estados ────────────────────────────
                    if self.is_sleeping:
                        if self._wake_word_detected(comando):
                            self.is_sleeping = False
                            comando = self._remove_wake_word(comando)

                            if comando.strip():
                                # Se dijo wake word + comando en la misma frase
                                self._ciclo_procesamiento(comando)
                            else:
                                # Solo el wake word — saludo de bienvenida
                                self.telemetry.send("speaking", "", "A tu servicio.")
                                self.audio.hablar("A tu servicio.")
                        # Si dormido y no detectó wake word → ignorar y seguir
                    else:
                        self._ciclo_procesamiento(comando)

                except Exception as exc:
                    logger.critical(f"Error Crítico Icaro Engine: {exc}", exc_info=True)
                    self.telemetry.send("error", "", str(exc))
                    self.audio.hablar("Ocurrió un error grave en la secuencia principal.")
                    # Recuperación: volver a modo escucha
                    self.telemetry.send("sleeping")

        except KeyboardInterrupt:
            logger.info("Apagado forzado por el usuario (Ctrl+C).")
            self.detener()

        finally:
            self.telemetry.close()

        logger.info("Sistemas fuera de línea.")

    def _ciclo_procesamiento(self, comando: str) -> None:
        """
        Ejecuta un ciclo completo:
            Guardar → [thinking] → Procesar → [speaking] → Hablar → [listening]
        """
        # Estado: procesando
        self.telemetry.send("thinking", comando, "")

        # 1. Guardar prompt usuario en memoria
        self.memory.guardar("user", comando)

        # 2. Enrutar y ejecutar acción
        respuesta = self.processor.process(comando)

        # 3. Hablar y guardar respuesta
        if respuesta:
            self.telemetry.send("speaking", comando, respuesta)
            self.audio.hablar(respuesta)
            self.memory.guardar("model", respuesta)

        # Volver a estado de escucha activa
        self.telemetry.send("listening")
