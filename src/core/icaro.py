import time
import logging
import re
import threading
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from ..config.settings import WAKE_WORD
from .memory_manager import MemoryManager
from .shared_memory import set_shared_memory
from .command_processor import CommandProcessor
from .planner import TaskPlanner
from .telemetry import Telemetry
from ..services.audio_service import AudioService
from ..services.execution_service import ExecutionService
from ..services.action_service import ActionService
from ..services.ai_service import AIService
from ..utils.text_utils import normalize_text
from .protocols import AudioProtocol, AIProtocol, MemoryProtocol, ActionProtocol, TelemetryProtocol
from .event_bus import bus, EventType
from .plugin_loader import plugin_loader

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
        # 1. Cargar Plugins y Skills
        plugin_loader.load_all()

        # 2. Telemetría y estado
        self.telemetry = telemetry_service or Telemetry()
        self._state = IcaroState.INITIALIZING
        self._emit_state()  # emite "initializing"

        logger.info("Iniciando subsistemas con inyección de dependencias...")
        self.silent = silent
        self.no_ai = no_ai
        self.inactivity_timeout = inactivity_timeout
        self.last_interaction_time = time.time()

        self._sleeping_logged = False

        # 2. Servicios
        self.memory = memory_manager or MemoryManager()
        
        # Registrar memoria compartida (singleton) para acceso global desde MCPs y servicios
        set_shared_memory(self.memory)
        
        self.audio = audio_service or AudioService()
        self.action = action_service or ActionService()
        self.ai = ai_service or AIService(self.memory)

        # Inyectar conectores necesarios para acciones
        self.action.set_obsidian_mcp(getattr(self.ai, 'obsidian_mcp', None))
        self.action.set_ai_service(self.ai)  # Para visión multimodal

        # 3. Deshabilitar IA si se solicita (usando método formal)
        if self.no_ai:
            self._disable_ai_service()

        # 3.5. Task Planner y Execution Service
        self.planner = TaskPlanner(self.ai)
        self.executor = ExecutionService(self.action, self.audio)

        # 4. Router de comandos
        self.processor = CommandProcessor(
            self.ai, 
            self.action, 
            planner=self.planner, 
            executor=self.executor, 
            use_rapidfuzz=True
        )

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
        if new_state != IcaroState.SLEEPING:
            self._sleeping_logged = False
        self._emit_state(transcript, response)
        bus.publish(EventType.STATE_CHANGED, {"state": new_state.name, "transcript": transcript, "response": response})

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

    def _get_greeting(self) -> str:
        """Devuelve un saludo basado en la hora actual con formato de 12 horas y minutos."""
        now = datetime.now()
        hour = now.hour
        minute = now.minute

        if 5 <= hour < 12:
            saludo = "Buenos días"
        elif 12 <= hour < 19:
            saludo = "Buenas tardes"
        else:
            saludo = "Buenas noches"

        hour_12 = hour % 12 or 12
        periodo = "de la mañana" if hour < 12 else ("de la tarde" if hour < 19 else "de la noche")

        if minute == 0:
            hora_str = f"las {hour_12} en punto {periodo}"
        elif minute == 30:
            hora_str = f"las {hour_12} y media {periodo}"
        else:
            hora_str = f"las {hour_12} y {minute} minutos {periodo}"

        return f"{saludo}, son {hora_str} ¿en qué le puedo ayudar?"

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
            if hasattr(self.ai, 'nvidia_habilitado'):
                self.ai.nvidia_habilitado = False
            if hasattr(self.ai, '_models_initialized'):
                self.ai._models_initialized = True
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
            # Resumir la sesión y guardarla en ChromaDB al dormir
            self._summarize_session_async(wait=False)

    def _summarize_session_async(self, wait: bool = False) -> None:
        """Genera un resumen de la sesión en segundo plano y lo guarda en ChromaDB."""
        def run():
            try:
                historial = self.memory.cargar()
                if not historial:
                    return
                
                # Filtrar y contar mensajes reales de usuario/modelo
                conversacion = [m for m in historial if m.get("role") in ("user", "model")]
                if len(conversacion) < 2:
                    logger.info("Historial demasiado corto para resumir.")
                    return
                
                logger.info("Generando resumen de sesión en background...")
                resumen = self._summarize_history(historial)
                if resumen:
                    logger.info(f"Sesión resumida con éxito: {resumen}")
                    self._save_session_summary(resumen, wait=wait)
                else:
                    logger.info("No se generó resumen de sesión (nada relevante o vacío).")
            except Exception as e:
                logger.error(f"Error en resumen asíncrono de sesión: {e}")

        t = threading.Thread(target=run, daemon=True, name="SessionSummarizer")
        t.start()
        if wait:
            # Esperar a que finalice la llamada (ej. en apagado), con un timeout de 4 segundos
            t.join(timeout=4.0)

    def _summarize_history(self, historial: list) -> Optional[str]:
        """Pide al servicio de IA un resumen si expone esa capacidad."""
        summarize_session = getattr(self.ai, "summarize_session", None)
        if not callable(summarize_session):
            logger.debug("El servicio AI no implementa summarize_session(); se omite el resumen.")
            return None
        return summarize_session(historial)

    def _save_session_summary(self, resumen: str, wait: bool = False) -> None:
        """Guarda el resumen en memoria vectorial cuando está disponible."""
        vector_db = getattr(self.memory, "vector_db", None)
        if not vector_db:
            return
        add_memory = getattr(vector_db, "add_memory", None)
        if not callable(add_memory):
            return

        import inspect
        sig = inspect.signature(add_memory)
        if "wait" in sig.parameters:
            add_memory(
                role="model",
                text=f"Resumen de conversación previa: {resumen}",
                intent="resumen_sesion",
                wait=wait
            )
        else:
            add_memory(
                role="model",
                text=f"Resumen de conversación previa: {resumen}",
                intent="resumen_sesion"
            )

    # -------------------- Ciclo de procesamiento de un comando --------------------
    def _save_memory_async(self, role: str, text: str) -> None:
        """Guarda en memoria de forma no bloqueante para no ralentizar el path crítico."""
        threading.Thread(
            target=self.memory.guardar,
            args=(role, text),
            daemon=True,
            name="MemSave"
        ).start()

    def _process_command(self, command: str) -> None:
        """
        Procesa un comando ya confirmado (wake word removido si es necesario).
        Respeta silent y no_ai.
        """
        # Mostrar que estamos pensando
        self._transition_to(IcaroState.THINKING, transcript=command)

        # Guardar en memoria lo que dijo el usuario (no bloqueante)
        self._save_memory_async("user", command)

        # Obtener respuesta del procesador (puede ser vacía si no_ai y comando desconocido)
        response = self.processor.process(command)

        if response:
            bus.publish(EventType.RESPONSE_READY, response)
            self._transition_to(IcaroState.SPEAKING, transcript=command, response=response)
            self._speak(response)
            self._save_memory_async("model", response)
        else:
            logger.warning(f"Sin respuesta para: '{command}'")
            # Si no hay respuesta, pasamos directamente a LISTENING (sin hablar)
            self._transition_to(IcaroState.LISTENING, transcript=command)

    # -------------------- Ciclo de vida y bucle principal --------------------
    def detener(self) -> None:
        self.running = False

    def _listen_for_command(self) -> str:
        """Escucha audio manteniendo coherente el estado actual."""
        if self._state == IcaroState.SLEEPING:
            if not getattr(self, "_sleeping_logged", False):
                logger.info("En reposo. (Di 'Ícaro' para activarme)")
                self._sleeping_logged = True
        elif self._state != IcaroState.LISTENING:
            self._transition_to(IcaroState.LISTENING)
        return self.audio.escuchar()

    def _shutdown_audio(self) -> None:
        """Libera recursos de audio si el servicio soporta apagado explícito."""
        shutdown = getattr(self.audio, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def iniciar(self) -> None:
        """Bucle principal con máquina de estados explícita."""
        # Mensaje de bienvenida (solo si no silent)
        if not self.silent:
            time.sleep(0.3)  # Solo lo necesario para que el widget UDP esté listo
            greeting = self._get_greeting()
            self._transition_to(IcaroState.SPEAKING, response=greeting)
            self._speak(greeting)

        self._transition_to(IcaroState.LISTENING)
        self.last_interaction_time = time.time()

        try:
            while self.running:
                try:
                    command = self._listen_for_command()

                    # --- Sin audio detectado ---
                    if not command:
                        self._check_inactivity()
                        continue

                    # --- Hay audio: actualizar timestamp ---
                    self.last_interaction_time = time.time()
                    # B8 FIX: normalizar a minúsculas antes del chequeo de salida,
                    # ya que el reconocedor puede devolver "Adiós" (con mayúscula)
                    # y el chequeo ocurre antes de que CommandProcessor normalice.
                    command = command.lower().strip()
                    logger.info(f"Interpretado: '{command}'")

                    # --- Comandos de salida (hardcoded) ---
                    if any(p in command for p in ("adiós", "salir", "a dios", "hasta luego", "hasta pronto")):
                        self._transition_to(IcaroState.SPEAKING, response="Hasta pronto.")
                        self._speak("Hasta pronto.")
                        # Resumir la sesión y guardarla antes de apagar
                        self._summarize_session_async(wait=True)
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
            self._shutdown_audio()
            self.telemetry.close()
            logger.info("Sistemas fuera. Apagado")
