import logging
from collections.abc import Mapping
from difflib import get_close_matches
from typing import Any, Protocol, TypeAlias

try:
    import rapidfuzz
    from rapidfuzz import fuzz
    rapidfuzz_available = True
except ImportError:
    rapidfuzz_available = False
    rapidfuzz = None

# Flujo procesar -> normalizar -> enrutar -> ejecutar

logger = logging.getLogger(__name__)

_DEFAULT_RESPONSE = "Entendido."
_ACTION_ERROR_RESPONSE = "No pude completar la accion solicitada."
_INVALID_PLAN_RESPONSE = "No pude generar un plan valido para esa tarea."
_PLAN_TASK_INTENT = "plan_task"
_DIRECT_RESPONSE_INTENTS = frozenset(("dar_hora_fecha", "ver_pantalla"))
_UNKNOWN_ACTION_MARKER = "desconocida:"

# Vocabulario canonico de intents locales reconocibles por fonetica
_INTENT_KEYWORDS = [
    "hora", "fecha", "calculadora", "notepad", "codigo", "código", "abrir",
    "cerrar", "buscar", "youtube", "volumen", "subir", "bajar",
    "salir", "apagar", "suspender", "carpeta", "copiar", "pegar",
    "pantalla", "ver", "captura", "observa", "mira",
]

IntentData: TypeAlias = Mapping[str, Any]
PlanStep: TypeAlias = Mapping[str, Any]


class AIService(Protocol):
    def route_command(self, text: str) -> IntentData:
        ...


class ActionService(Protocol):
    def execute(self, intent_data: IntentData) -> Any:
        ...


class PlannerService(Protocol):
    def create_plan(self, command: str) -> list[PlanStep]:
        ...


class ExecutorService(Protocol):
    def execute_plan(self, steps: list[PlanStep]) -> Any:
        ...


class CommandProcessor:
    """
    Router principal de la logica.
    Pipeline unidireccional: normalizar -> enrutar -> ejecutar -> responder
    """

    def __init__(
        self,
        ai_service: AIService,
        action_service: ActionService,
        planner: PlannerService | None = None,
        executor: ExecutorService | None = None,
        use_rapidfuzz: bool = False,
    ) -> None:
        self.ai = ai_service
        self.action = action_service
        self.planner = planner
        self.executor = executor
        self.use_rapidfuzz = use_rapidfuzz and rapidfuzz_available

    def process(self, comando: str) -> str:
        """Procesa un comando completo siguiendo el pipeline de 4 etapas."""
        # Etapa 1: Normalizar
        clean = self._normalize(comando)

        # Etapa 2: Enrutar
        intent_data = self._route_command(clean)

        # Etapa 3: Ejecutar accion si aplica
        respuesta = self._execute(intent_data, clean)

        # Etapa 4: Retornar texto final para el audio
        return respuesta

    def _normalize(self, text: str) -> str:
        """
        Limpia el texto crudo del reconocedor.
        Aplica correccion fonetica basica via rapidfuzz o difflib.
        """
        text = text.lower().strip()
        words = text.split()
        corrected: list[str] = []

        for word in words:
            # Solo aplicar fuzzy-matching a palabras de 4+ caracteres
            # para evitar falsos positivos (ej. 'hola' -> 'hora')
            if len(word) >= 4:
                if self.use_rapidfuzz:
                    match = rapidfuzz.process.extractOne(word, _INTENT_KEYWORDS, scorer=fuzz.ratio, score_cutoff=90)
                    if match:
                        corrected.append(match[0])
                        continue
                else:
                    match = get_close_matches(word, _INTENT_KEYWORDS, n=1, cutoff=0.90)
                    if match:
                        corrected.append(match[0])
                        continue
            corrected.append(word)

        result = " ".join(corrected)
        if result != text:
            engine = "rapidfuzz" if self.use_rapidfuzz else "difflib"
            logger.debug("Correccion fonetica (%s): '%s' -> '%s'", engine, text, result)
        return result

    def _route_command(self, command: str) -> IntentData:
        """Delega a la IA para clasificar la intención del comando."""
        try:
            return self.ai.route_command(command)
        except Exception:
            logger.exception("No se pudo enrutar el comando.")
            return {"respuesta": _DEFAULT_RESPONSE}
        
    def _execute(self, intent_data: object, command_text: str = "") -> str:
        """Ejecuta la acción del sistema operativo si hay intent."""

        if not isinstance(intent_data, Mapping):
            logger.warning("Intent data invalido: %r", intent_data)
            return _DEFAULT_RESPONSE

        respuesta_hablada = self._spoken_response(intent_data)

        intent = intent_data.get("intent")
        if not isinstance(intent, str):
            return respuesta_hablada

        if intent == _PLAN_TASK_INTENT:
            return self._execute_plan_task(command_text, respuesta_hablada)

        return self._execute_action(intent, intent_data, respuesta_hablada)
    

    def _spoken_response(self, intent_data: IntentData) -> str:
        response = intent_data.get("respuesta") or _DEFAULT_RESPONSE
        return str(response)

    def _execute_plan_task(self, command_text: str, fallback_response: str) -> str:
        if not self.planner or not self.executor:
            logger.warning("plan_task recibido sin planner/executor configurados.")
            return fallback_response

        try:
            logger.info("Enrutando a TaskPlanner para plan_task...")
            steps = self.planner.create_plan(command_text)
            if not steps:
                return _INVALID_PLAN_RESPONSE
            return self.executor.execute_plan(steps) or fallback_response
        except Exception:
            logger.exception("Error ejecutando plan_task.")
            return _ACTION_ERROR_RESPONSE

    def _execute_action(
        self,
        intent: str,
        intent_data: IntentData,
        fallback_response: str,
    ) -> str:
        try:
            resultado_accion = self.action.execute(dict(intent_data))
        except Exception:
            logger.exception("Error ejecutando accion para intent '%s'.", intent)
            return _ACTION_ERROR_RESPONSE

        if intent in _DIRECT_RESPONSE_INTENTS:
            return resultado_accion or fallback_response

        if not resultado_accion:
            return fallback_response

        if self._is_unknown_action(resultado_accion):
            logger.debug("Intent conversacional ignorado por ActionService: %s", resultado_accion)
            return fallback_response

        logger.info("Sistema: %s", resultado_accion)
        return fallback_response

    def _is_unknown_action(self, action_result: str) -> bool:
        return _UNKNOWN_ACTION_MARKER in str(action_result).lower()
