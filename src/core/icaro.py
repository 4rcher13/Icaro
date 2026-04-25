import time
import logging
import re
from enum import Enum, auto
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


# -------------------- ESTADOS EXPLÍCITOS --------------------
class IcaroState(Enum):
    """Estados finitos del asistente."""
    INITIALIZING = auto()
    SLEEPING = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    ERROR = auto()


class Icaro:
    """
    Orquestador principal con máquina de estados formal.
    Cada cambio de estado emite telemetría sin duplicados innecesarios.
    """

    def __init__(
        self,
        silent: bool = False,
        no_ai: bool = False,
        audio_service: Optional[AudioProtocol] = None,
        ai_service: Optional[AIProtocol] = None,
        memory_manager: Optional[MemoryProtocol] = None,
        action_service: Optional[ActionProtocol] = None,
        telemetry_service: Optional[TelemetryProtocol] = None,
        inactivity_timeout: float = 30.0  # nuevo: tiempo de inactividad configurable
    ):
        # 1. Telemetría y estado
        self.telemetry = telemetry_service or Telemetry()
        self._state = IcaroState.INITIALIZING
        self._emit_state()  # emite "initializing"

        logger.info("Iniciando subsistemas con inyección de dependencias...")
        self.silent = silent
        self.no_ai = no_ai
        self.inactivity_timeout = inactivity_timeout
        self.last_interaction_time = time.time()   # ← mover el timestamp aquí

        # 2. Servicios
        self.memory = memory_manager or MemoryManager()
        self.audio = audio_service or AudioService()
        self.action = action_service or ActionService()
        self.ai = ai_service or AIService(self.memory)

        # 3. Deshabilitar IA si se solicita (usando método formal)
        if self.no_ai:
            self._disable_ai_service()

        # 4. Router de comandos
        self.processor = CommandProcessor(self.ai, self.action, use_rapidfuzz=True)

        # 5. Configuración del wake word (normalizado una sola vez)
        self.wake_aliases = [normalize_text(alias) for alias in WAKE_WORD]
        self.wake_regex = re.compile(
            r'\b(' + '|'.join(re.escape(alias) for alias in self.wake_aliases) + r')\s*',
            re.IGNORECASE
        )

        self.running = True

    # -------------------- Telemetría con máquina de estados --------------------
    def _emit_state(self, transcript: str = "", response: str = "") -> None:
        """
        Envía el estado actual al widget.
        Solo se envía si el estado cambió o hay texto nuevo.
        """
        self.telemetry.send(self._state.name.lower(), transcript, response)

    def _transition_to(self, new_state: IcaroState, transcript: str = "", response: str = "") -> None:
        """Cambia de estado y emite la transición."""
        if self._state == new_state and not transcript and not response:
            return
        self._state = new_state
        self._emit_state(transcript, response)

    # -------------------- Wake word helpers optimizados --------------------
    def _contains_wake_word(self, command: str) -> bool:
        """Retorna True si el comando contiene algún alias del wake word."""
        cmd_norm = normalize_text(command)
        return any(alias in cmd_norm for alias in self.wake_aliases)

    def _remove_wake_word(self, command: str) -> str:
        """Elimina el wake word del comando y limpia espacios sobrantes."""
        # Remueve el wake word y cualquier espacio/tabulador después
        cleaned = self.wake_regex.sub('', command)
        # Normaliza espacios múltiples y trim
        return re.sub(r'\s+', ' ', cleaned).strip()

    # -------------------- Salida de voz controlada por silent --------------------
    def _speak(self, text: str) -> None:
        """Habla solo si el modo silencioso está desactivado."""
        if not self.silent and text:
            self.audio.hablar(text)

    # -------------------- Deshabilitar IA (sin hackear atributos internos) --------------------
    def _disable_ai_service(self) -> None:
        """Desactiva la IA local llamando al método correcto (si existe)."""
        if hasattr(self.ai, 'disable_ai'):
            self.ai.disable_ai()
        else:
            # Fallback seguro para mantener compatibilidad
            logger.warning("El servicio AI no implementa disable_ai(); se usan atributos directos.")
            if hasattr(self.ai, 'ia_habilitada'):
                self.ai.ia_habilitada = False
            if hasattr(self.ai, 'ollama_habilitado'):
                self.ai.ollama_habilitado = False
        logger.info("Modo --no-ai activo: solo comandos locales.")

    # -------------------- Lógica de inactividad --------------------
    def _check_inactivity(self) -> None:
        """Verifica si ha pasado el timeout y duerme al asistente si está activo."""
        if self._state != IcaroState.LISTENING:
            return
        if time.time() - self.last_interaction_time > self.inactivity_timeout:
            self._transition_to(IcaroState.SPEAKING, response="Entrando en reposo.")
            self._speak("Entrando en reposo.")
            self._transition_to(IcaroState.SLEEPING)

    # -------------------- Ciclo de procesamiento de un comando --------------------
    def _process_command(self, command: str) -> None:
        """
        Procesa un comando ya confirmado (wake word removido si es necesario).
        Respeta silent y no_ai.
        """
        # Mostrar que estamos pensando
        self._transition_to(IcaroState.THINKING, transcript=command)

        # Guardar en memoria lo que dijo el usuario
        self.memory.guardar("user", command)

        # Obtener respuesta del procesador (puede ser vacía si no_ai y comando desconocido)
        response = self.processor.process(command)

        if response:
            self._transition_to(IcaroState.SPEAKING, transcript=command, response=response)
            self._speak(response)
            self.memory.guardar("model", response)
        else:
            logger.warning(f"Sin respuesta para: '{command}'")
            # Si no hay respuesta, pasamos directamente a LISTENING (sin hablar)
            self._transition_to(IcaroState.LISTENING, transcript=command)

    # -------------------- Ciclo de vida y bucle principal --------------------
    def detener(self) -> None:
        self.running = False

    def iniciar(self) -> None:
        """Bucle principal con máquina de estados explícita."""
        # Mensaje de bienvenida (solo si no silent)
        if not self.silent:
            time.sleep(2.0)  # todavía se necesita para el widget UDP
            self._transition_to(IcaroState.SPEAKING, response="Sistemas inicializados en modo nativo.")
            self._speak("Sistemas inicializados en modo nativo.")

        self._transition_to(IcaroState.SLEEPING)

        try:
            while self.running:
                try:
                    # --- Determinar en qué estado estamos ---
                    if self._state == IcaroState.SLEEPING:
                        logger.debug("En reposo. (Di 'Ícaro' para activarme)")   # debug bajo
                        # No emitimos SLEEPING repetitivo porque _transition_to ya lo hizo
                        command = self.audio.escuchar()
                    else:  # LISTENING, THINKING o SPEAKING? En realidad solo debería estar LISTENING aquí
                        # Aseguramos que estamos en LISTENING antes de escuchar
                        if self._state != IcaroState.LISTENING:
                            self._transition_to(IcaroState.LISTENING)
                        command = self.audio.escuchar()

                    # --- Sin audio detectado ---
                    if not command:
                        self._check_inactivity()
                        continue

                    # --- Hay audio: actualizar timestamp ---
                    self.last_interaction_time = time.time()
                    logger.info(f"Interpretado: '{command}'")

                    # --- Comandos de salida (hardcoded) ---
                    if any(p in command for p in ("salir por completo", "apagar asistente", "terminar", "salir")):
                        self._transition_to(IcaroState.SPEAKING, response="Apagando módulos. Hasta la próxima.")
                        self._speak("Apagando módulos. Hasta la próxima.")
                        self.detener()
                        break

                    # --- Máquina de estados principal ---
                    if self._state == IcaroState.SLEEPING:
                        if self._contains_wake_word(command):
                            # Despertar
                            self._transition_to(IcaroState.LISTENING)   # cambia a listening sin texto
                            clean_cmd = self._remove_wake_word(command)
                            if clean_cmd:
                                # Wake word + comando inline
                                self._process_command(clean_cmd)
                            else:
                                # Solo wake word: saludar y seguir escuchando
                                self._transition_to(IcaroState.SPEAKING, response="A tu servicio.")
                                self._speak("A tu servicio.")
                                self._transition_to(IcaroState.LISTENING)
                        # Si duerme y no hay wake word, seguimos durmiendo (no emitimos nada)
                    else:
                        # Estamos activos (LISTENING normalmente)
                        # Aseguramos que el comando se procese
                        self._process_command(command)
                        # Después de procesar, el estado queda en LISTENING (se hace dentro de _process_command)

                except Exception as exc:
                    logger.critical(f"Error crítico en Icaro: {exc}", exc_info=True)
                    self._transition_to(IcaroState.ERROR, response=str(exc))
                    self._speak("Ocurrió un error en el sistema.")
                    # Recuperación: volver a SLEEPING
                    self._transition_to(IcaroState.SLEEPING)

        except KeyboardInterrupt:
            logger.info("Apagado forzado por el usuario (Ctrl+C).")
            self.detener()
        finally:
            self.telemetry.close()
            logger.info("Sistemas fuera de línea.")