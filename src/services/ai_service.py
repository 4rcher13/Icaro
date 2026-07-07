import json
import re
import logging
import threading
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

# Configurar stdout para UTF-8 en Windows para evitar caídas por codificación de emojis en consola
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


from ..core.nlu.intents import local_fallback

# ─── Lazy Imports para SDKs de IA (evitar carga pesada al arranque) ────────
# google.genai, ollama y openai se importan dentro de los métodos _init_*
# para reducir el cold-start del asistente.
genai = None
types = None
ollama = None
OpenAI = None

from ..config.settings import GEMINI_API_KEY, MODELO_LOCAL, OBSIDIAN_VAULT_PATH, GITHUB_TOKEN, USER_NAME, NVIDIA_API_KEY
from ..core.event_bus import bus, EventType
from ..core.plugin_loader import plugin_loader
from ..core.shared_memory import log_event

# Importación segura de MCPs — el asistente arranca aunque alguno falle
try:
    from ..mcps.gemini_mcp import GeminiMCP
except ImportError:
    GeminiMCP = None  # type: ignore

try:
    from ..mcps.sequential_thinking import SequentialThinkingMCP
except ImportError:
    SequentialThinkingMCP = None  # type: ignore

try:
    from ..mcps.cybersecurity_mcp import CybersecurityMCP
except ImportError:
    CybersecurityMCP = None  # type: ignore

try:
    from ..mcps.obsidian_mcp import ObsidianMCP
except ImportError:
    ObsidianMCP = None  # type: ignore

try:
    from ..mcps.github_mcp import GitHubMCP
except ImportError:
    GitHubMCP = None  # type: ignore

logger = logging.getLogger(__name__)

_DEBUG_LOG = Path(__file__).resolve().parent.parent.parent / "debug-a76827.log"


def _dbg_perf(location: str, message: str, data: dict | None = None, hypothesis_id: str = "?") -> None:
    # region agent log
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "a76827",
                "location": location,
                "message": message,
                "data": data or {},
                "hypothesisId": hypothesis_id,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # endregion


# --------------------------------------------------------------------------
# Clasificador de complejidad: decide si usar Ollama (rápido) o Gemini (complejo)
# --------------------------------------------------------------------------
_SIMPLE_INTENTS = {
    "buscar_google", "control_volumen", "reproducir_youtube",
    "cerrar_ventana", "abrir_aplicacion", "crear_carpeta",
    "escribir_texto", "dar_hora_fecha", "suspender_equipo", "hacer_click",
    "ver_pantalla"
}

# Palabras clave que indican tareas complejas → Gemini
_COMPLEX_KEYWORDS = frozenset([
    "investiga", "investigacion", "analiza", "analisis", "explica", "explicame",
    "codigo", "programa", "funcion", "clase", "algoritmo", "refactoriza",
    "compara", "diferencia", "ventaja", "desventaja", "opinion",
    "resumen", "resume", "resena", "tutorial", "como funciona",
    "arquitectura", "patron", "diseno", "estrategia", "optimiza",
    "depura", "debug", "error", "bug", "solucion", "arregla",
    "traduce", "traduccion", "genera", "crea un", "escribe un",
    "modifica", "cambia el codigo", "agrega", "implementa",
    # Variantes con acentos (el input de voz puede traerlos)
    "explicá", "explícame", "explícalo", "investigación", "análisis",
    "código", "función", "patrón", "diseño", "solución", "traducción",
    "opinión",
])


def _is_complex_query(text: str) -> bool:
    """Determina si un comando requiere razonamiento avanzado (Gemini)."""
    t = text.lower()
    # Si contiene palabras clave de complejidad
    if any(kw in t for kw in _COMPLEX_KEYWORDS):
        return True
    # Si el texto es largo (>60 chars), probablemente es conversación o pregunta compleja
    if len(t) > 60:
        return True
    return False


class AIService:
    """Motor Cognitivo y Router Lógico de Ícaro (optimizado con Smart Routing)."""

    # Constantes configurables
    MAX_RESPUESTA_TTS = 800             # caracteres máximos para respuesta hablada (TTS fluido)
    TIMEOUT_SEGUNDOS = 12               # timeout para llamadas a modelos
    TIMEOUT_ROUTING = 8                 # timeout más estricto para clasificación de intents
    REINTENTOS_LLM = 2                  # reintentos ante fallo transitorio
    MAX_CONTINUATIONS = 2               # límite de continuaciones por respuesta cortada
    MCP_CONTEXT_TIMEOUT = 1.0           # segundos máx. esperando MCPs en contexto

    INTENTS_VALIDOS = {
        "buscar_google", "control_volumen", "reproducir_youtube",
        "cerrar_ventana", "abrir_aplicacion", "crear_carpeta",
        "escribir_texto", "dar_hora_fecha", "suspender_equipo", "hacer_click",
        "guardar_en_obsidian", "ver_pantalla", "plan_task"
    }

    # Prompt compacto para clasificación de intents (Ollama - tareas simples)
    _PROMPT_SIMPLE = """\
{{contexto}}Eres Ícaro, el asistente de IA personal de {user_name}. Clasifica el comando del usuario. Responde SOLO JSON válido.
Intents posibles: {{intents}}
Si es conversación general, intent=null.
Comando: {{text}}
JSON:"""

    # Prompt completo para Gemini (tareas complejas)
    _PROMPT_COMPLEX = """\
{{contexto}}Eres Ícaro, el asistente de IA inteligente, amigable y mentor de programación/ciberseguridad de {user_name}. Analiza el comando y responde SOLO JSON.

Intents: {{intents}}
Reglas:
- "intent": uno de los intents o null (conversación). Si la petición requiere múltiples acciones u ordenar tareas complejas, usa SIEMPRE "plan_task".
- "target": objeto de la acción o título de la nota si es para Obsidian. Si es plan_task, pon target vacío.
- "respuesta": Si hay intent, confirmación corta (max 15 palabras). Si es conversación, respuesta natural hablando amigablemente con {user_name}. Si es plan_task, pon "Generando plan de ejecución...".
- "contenido_nota": (Opcional) Si el intent es guardar_en_obsidian, el texto formateado en Markdown para la nota.

Comando: {{text}}
JSON:"""

    def __init__(self, memory_manager, *, warmup: bool = True):
        self.memory = memory_manager
        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.nvidia_habilitado = False
        self.modelo_local = MODELO_LOCAL
        self.client = None          # Cliente Gemini
        self.chat = None            # Sesión de chat Gemini
        self.nvidia_client = None   # Cliente NVIDIA (DeepSeek)
        self._models_initialized = False
        self._ai_disabled = False
        self._init_lock = threading.Lock()

        # Pre-formatear prompts con el nombre del usuario
        self._PROMPT_SIMPLE = self._PROMPT_SIMPLE.format(user_name=USER_NAME)
        self._PROMPT_COMPLEX = self._PROMPT_COMPLEX.format(user_name=USER_NAME)

        # Inicializar MCPs (opcionales — no bloquean el arranque)
        self.gemini_mcp = GeminiMCP() if GeminiMCP else None
        self.thinking_mcp = SequentialThinkingMCP() if SequentialThinkingMCP else None
        self.security_mcp = CybersecurityMCP() if CybersecurityMCP else None
        self.obsidian_mcp = ObsidianMCP(OBSIDIAN_VAULT_PATH) if ObsidianMCP else None
        self.github_mcp = GitHubMCP(GITHUB_TOKEN) if GitHubMCP else None
        
        # Executor para llamadas asíncronas a MCPs (evita bloqueos)
        self.mcp_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="MCPCalls")

        # Precalentar modelos en background para reducir latencia del primer comando
        if warmup:
            threading.Thread(
                target=self._ensure_models_initialized,
                daemon=True,
                name="IAWarmup",
            ).start()

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_genai_types():
        """Importa google.genai.types bajo demanda (evita fallos si types es None)."""
        global types
        if types is None:
            try:
                from google.genai import types as _types
                types = _types
            except ImportError:
                return None
        return types

    def _run_with_timeout(self, fn: Callable[[], Any], timeout: float) -> Any:
        """Ejecuta fn con timeout; lanza FuturesTimeout si excede."""
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="LLMCall") as pool:
            return pool.submit(fn).result(timeout=timeout)

    # ------------------------------------------------------------------
    # Inicialización paralela de modelos
    # ------------------------------------------------------------------
    def _init_gemini(self) -> None:
        """Inicializa Gemini (nube). Thread-safe. Lazy import."""
        global genai, types
        if not genai:
            try:
                import google.genai as _genai
                from google.genai import types as _types
                genai = _genai
                types = _types
            except ImportError:
                logger.warning("Librería google-genai no instalada.")
                return
        if not GEMINI_API_KEY:
            logger.warning("Gemini no configurado (API key faltante).")
            return
        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            if not self._ai_disabled:
                self.ia_habilitada = True
            logger.info("Gemini iniciado correctamente de forma stateless.")
        except Exception as exc:
            logger.error(f"Fallo al iniciar Gemini: {exc}")

    def _init_ollama(self) -> None:
        """Inicializa Ollama (local). Thread-safe. Lazy import."""
        global ollama
        if not ollama:
            try:
                import ollama as _ollama
                ollama = _ollama
            except ImportError:
                logger.warning("Librería ollama no instalada.")
                return
        try:
            # Ping ligero (~50ms) en lugar de ollama.list() que escanea todos los modelos
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2)
            if not self._ai_disabled:
                self.ollama_habilitado = True
            logger.info("Ollama disponible localmente.")
        except Exception as exc:
            logger.warning(f"Ollama no disponible: {exc}")

    def _init_nvidia(self) -> None:
        """Inicializa el cliente de NVIDIA API (DeepSeek). Thread-safe. Lazy import."""
        global OpenAI
        if not OpenAI:
            try:
                from openai import OpenAI as _OpenAI
                OpenAI = _OpenAI
            except ImportError:
                logger.warning("Librería openai no instalada.")
                return
        if not NVIDIA_API_KEY:
            logger.warning("NVIDIA API no configurada (API key faltante).")
            return
        try:
            self.nvidia_client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=NVIDIA_API_KEY
            )
            if not self._ai_disabled:
                self.nvidia_habilitado = True
            logger.info("NVIDIA API (DeepSeek) iniciada correctamente.")
        except Exception as exc:
            logger.error(f"Fallo al iniciar NVIDIA API: {exc}")

    def _ensure_models_initialized(self) -> bool:
        """Inicializa Gemini, Ollama y NVIDIA en paralelo (una sola vez)."""
        if self._ai_disabled:
            return False
        if self._models_initialized:
            return self.ia_habilitada or self.ollama_habilitado or self.nvidia_habilitado

        with self._init_lock:
            if self._ai_disabled:
                return False
            if self._models_initialized:
                return self.ia_habilitada or self.ollama_habilitado or self.nvidia_habilitado

            t_init = time.perf_counter()

            # Inicializar modelos en paralelo
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="IAInit") as pool:
                futures = {
                    pool.submit(self._init_gemini): "gemini",
                    pool.submit(self._init_ollama): "ollama",
                    pool.submit(self._init_nvidia): "nvidia",
                }
                for f in as_completed(futures, timeout=10):
                    name = futures[f]
                    t0 = time.perf_counter()
                    try:
                        f.result()
                        _dbg_perf(
                            "ai_service.py:_ensure_models_initialized",
                            f"{name} init ok",
                            {"elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)},
                            "H1",
                        )
                    except Exception as exc:
                        logger.error(f"Error en inicialización de modelo ({name}): {exc}")

            _dbg_perf(
                "ai_service.py:_ensure_models_initialized",
                "models init complete",
                {
                    "total_ms": round((time.perf_counter() - t_init) * 1000, 1),
                    "gemini": self.ia_habilitada,
                    "ollama": self.ollama_habilitado,
                    "nvidia": self.nvidia_habilitado,
                },
                "H1",
            )
            self._models_initialized = True

        return self.ia_habilitada or self.ollama_habilitado or self.nvidia_habilitado

    # ------------------------------------------------------------------
    # Llamada a LLM con Smart Routing
    # ------------------------------------------------------------------
    @staticmethod
    def _extraer_json(texto: str) -> Optional[Dict]:
        """Extrae el primer bloque JSON válido de un texto, soportando objetos anidados."""
        if not texto:
            return None
        # B11 FIX: usar contador de llaves para capturar JSON anidado completo
        start = texto.find('{')
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(texto[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidato = texto[start:i + 1]
                    try:
                        return json.loads(candidato)
                    except json.JSONDecodeError:
                        logger.debug(f"JSON inválido encontrado: {candidato[:100]}")
                        # Buscar siguiente '{' e intentar de nuevo
                        next_start = texto.find('{', i + 1)
                        if next_start == -1:
                            return None
                        start = next_start
                        depth = 0
        return None

    def _call_nvidia(self, prompt: str, *, max_tokens: int = 512) -> Optional[Dict[str, Any]]:
        """Llama a Nvidia API (DeepSeek v4 Flash) con soporte de continuación."""
        if not self.nvidia_habilitado or not self.nvidia_client:
            return None

        def _do_call() -> Optional[Dict[str, Any]]:
            for intento in range(self.REINTENTOS_LLM):
                try:
                    full_text = ""
                    current_prompt = prompt
                    intent_val = None
                    target_val = None

                    for _ in range(self.MAX_CONTINUATIONS + 1):
                        messages = [
                            {"role": "system", "content": f"Eres Ícaro, el asistente de IA para programación de {USER_NAME}. Responde SIEMPRE en formato JSON."},
                            {"role": "user", "content": current_prompt}
                        ]

                        completion = self.nvidia_client.chat.completions.create(
                            model="deepseek-ai/deepseek-v4-flash",
                            messages=messages,
                            temperature=0.1,
                            top_p=0.9,
                            max_tokens=max_tokens,
                            stream=False,
                            user=USER_NAME
                        )

                        message = completion.choices[0].message
                        if getattr(message, 'refusal', None):
                            logger.warning(f"API refusal: {message.refusal}")
                            return {"intent": "desconocido", "target": "", "respuesta": "Lo siento, la solicitud fue rechazada por políticas de seguridad."}
                        
                        texto_generado = message.content
                        if not texto_generado:
                            break

                        finish_reason = getattr(completion.choices[0], 'finish_reason', '') or ''
                        finish_reason_str = str(finish_reason).upper()

                        datos = self._extraer_json(texto_generado)
                        if datos:
                            intent_val = datos.get("intent", intent_val)
                            target_val = datos.get("target", target_val)
                            part_resp = datos.get("respuesta", "")
                            full_text = part_resp if not full_text else full_text + " " + part_resp

                            if "LENGTH" not in finish_reason_str and "MAX_TOKENS" not in finish_reason_str:
                                return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                        else:
                            match_resp = re.search(r'"respuesta"\s*:\s*"(.*)', texto_generado, re.DOTALL)
                            if match_resp:
                                full_text += match_resp.group(1).rstrip('}"\n ')
                            else:
                                full_text += texto_generado

                        logger.info("NVIDIA DeepSeek se cortó. Solicitando continuación...")
                        current_prompt = (
                            f"{prompt}\n\n[SISTEMA: Continúa en JSON desde donde quedó. "
                            f"Texto parcial: '{full_text[-120:]}']"
                        )

                    return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                except Exception as exc:
                    logger.error(f"NVIDIA API falló (intento {intento+1}): {exc}")
                    if intento < self.REINTENTOS_LLM - 1:
                        time.sleep(0.3)
            return None

        try:
            return self._run_with_timeout(_do_call, self.TIMEOUT_SEGUNDOS)
        except FuturesTimeout:
            logger.warning("NVIDIA API excedió el timeout.")
            return None

    def _call_secondary_llm(self, prompt: str, *, prefer_local: bool = True) -> Optional[Dict[str, Any]]:
        """Llama al LLM secundario. Ollama local primero si prefer_local (más rápido)."""
        if prefer_local and self.ollama_habilitado:
            result = self._call_ollama(prompt)
            if result:
                return result
        if self.nvidia_habilitado:
            return self._call_nvidia(prompt)
        if not prefer_local and self.ollama_habilitado:
            return self._call_ollama(prompt)
        return None

    def _call_ollama(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Llama a Ollama con soporte de continuación."""
        if not self.ollama_habilitado:
            return None

        def _do_call() -> Optional[Dict[str, Any]]:
            for intento in range(self.REINTENTOS_LLM):
                try:
                    full_text = ""
                    current_prompt = prompt
                    intent_val = None
                    target_val = None

                    for _ in range(self.MAX_CONTINUATIONS + 1):
                        res = ollama.chat(
                            model=self.modelo_local,
                            messages=[{"role": "user", "content": current_prompt}],
                            format="json",
                            keep_alive="10m",
                            options={
                                "temperature": 0.0,
                                "num_predict": 256,
                                "top_p": 0.9,
                                "num_ctx": 4096,
                                "stop": ["\n```", "```"],
                            }
                        )
                        texto_generado = res["message"]["content"]
                        if not texto_generado:
                            break

                        datos = self._extraer_json(texto_generado)
                        if datos:
                            intent_val = datos.get("intent", intent_val)
                            target_val = datos.get("target", target_val)
                            part_resp = datos.get("respuesta", "")
                            full_text = part_resp if not full_text else full_text + " " + part_resp

                            if texto_generado.strip().endswith("}"):
                                return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                        else:
                            match_resp = re.search(r'"respuesta"\s*:\s*"(.*)', texto_generado, re.DOTALL)
                            if match_resp:
                                full_text += match_resp.group(1).rstrip('}"\n ')
                            else:
                                full_text += texto_generado

                        logger.info("Ollama se cortó. Solicitando continuación...")
                        current_prompt = (
                            f"{prompt}\n\n[SISTEMA: Continúa en JSON desde donde quedó. "
                            f"Texto parcial: '{full_text[-120:]}']"
                        )

                    return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                except Exception as exc:
                    logger.warning(f"Ollama falló (intento {intento+1}): {exc}")
                    if intento < self.REINTENTOS_LLM - 1:
                        time.sleep(0.3)

            logger.warning("Ollama no dio respuesta válida después de reintentos.")
            return None

        try:
            return self._run_with_timeout(_do_call, self.TIMEOUT_ROUTING)
        except FuturesTimeout:
            logger.warning("Ollama excedió el timeout de routing.")
            return None

    def _call_gemini(self, prompt: str, *, max_output_tokens: int = 512) -> Optional[Dict[str, Any]]:
        """Llama a Gemini de forma stateless con soporte de continuación automática."""
        if not self.ia_habilitada or not self.client:
            return None

        genai_types = self._ensure_genai_types()
        if genai_types is None:
            logger.error("google.genai.types no disponible.")
            return None

        def _do_call() -> Optional[Dict[str, Any]]:
            for intento in range(self.REINTENTOS_LLM):
                try:
                    full_text = ""
                    current_prompt = prompt
                    intent_val = None
                    target_val = None

                    for _ in range(self.MAX_CONTINUATIONS + 1):
                        res = self.client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=current_prompt,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=(
                                    f"Eres Ícaro, el asistente de IA para programación avanzada y ciberseguridad de {USER_NAME}. "
                                    "Analiza el contexto y responde SIEMPRE en formato JSON."
                                ),
                                temperature=0.2,
                                max_output_tokens=max_output_tokens,
                                response_mime_type="application/json",
                                safety_settings=[
                                    genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                    genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                    genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                    genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                ]
                            )
                        )

                        texto_generado = res.text.strip() if res.text else ""
                        if not texto_generado:
                            break

                        finish_reason_str = ""
                        try:
                            if res.candidates:
                                fr = res.candidates[0].finish_reason
                                finish_reason_str = str(fr.name if hasattr(fr, 'name') else fr).upper()
                        except Exception:
                            pass

                        datos = self._extraer_json(texto_generado)
                        if datos:
                            intent_val = datos.get("intent", intent_val)
                            target_val = datos.get("target", target_val)
                            part_resp = datos.get("respuesta", "")
                            full_text = part_resp if not full_text else full_text + " " + part_resp

                            if "MAX_TOKENS" not in finish_reason_str and "LENGTH" not in finish_reason_str:
                                return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                        else:
                            match_resp = re.search(r'"respuesta"\s*:\s*"(.*)', texto_generado, re.DOTALL)
                            if match_resp:
                                full_text += match_resp.group(1).rstrip('}"\n ')
                            else:
                                full_text += texto_generado

                        logger.info("Gemini se cortó. Solicitando continuación...")
                        current_prompt = (
                            f"{prompt}\n\n[SISTEMA: Continúa en JSON desde donde quedó. "
                            f"Texto parcial: '{full_text[-120:]}']"
                        )

                    return {"intent": intent_val, "target": target_val, "respuesta": full_text}
                except Exception as exc:
                    logger.error(f"Gemini falló (intento {intento+1}): {exc}")
                    if intento < self.REINTENTOS_LLM - 1:
                        time.sleep(0.5)
            return None

        try:
            return self._run_with_timeout(_do_call, self.TIMEOUT_SEGUNDOS)
        except FuturesTimeout:
            logger.warning("Gemini excedió el timeout.")
            return None

    # ------------------------------------------------------------------
    # Enrutamiento principal con Smart Routing
    # ------------------------------------------------------------------
    def route_command(self, text: str) -> Dict[str, Any]:
        """
        Pipeline con Smart Routing:
          1. Respuesta local rápida (local_fallback) — 0ms
          2. Clasificar complejidad del comando
          3a. Simple → Ollama (rápido, local) → Gemini fallback
          3b. Complejo → Gemini (potente, nube) → Ollama fallback
          4. Fallback humanoide
        """
        # --- Paso 1: local inmediato (sin IA) ---
        local = local_fallback(text)
        if local:
            logger.info(f"Respuesta LOCAL para: '{text}'")
            bus.publish(EventType.INTENT_ROUTED, local)
            return self._sanitize_response(local)

        # Emitir evento de que estamos pensando
        bus.publish(EventType.THINKING_STARTED, text)

        t_route = time.perf_counter()

        # --- Paso 2: inicializar IA si no lo estaba ---
        ai_available = self._ensure_models_initialized()
        if not ai_available:
            logger.warning("Ningún modelo IA disponible.")
            return {
                "intent": None,
                "target": None,
                "respuesta": "Mis sistemas de IA están offline. Puedo hacer cosas básicas como dar la hora o abrir apps. ¿Qué necesitas?"
            }

        # --- Paso 3: Smart Routing (contexto construido una sola vez) ---
        is_complex = _is_complex_query(text)
        user_text_escaped = json.dumps(text, ensure_ascii=False)
        intents_str = ", ".join(self.INTENTS_VALIDOS)

        t_ctx = time.perf_counter()
        contexto = self._build_context(text, include_mcp=is_complex)
        _dbg_perf(
            "ai_service.py:route_command",
            "context built",
            {"elapsed_ms": round((time.perf_counter() - t_ctx) * 1000, 1), "is_complex": is_complex},
            "H3",
        )

        if is_complex:
            # Tareas complejas: Gemini primero (mejor razonamiento)
            logger.info(f"Smart Routing -> GEMINI (complejo): '{text[:50]}'")
            prompt = self._PROMPT_COMPLEX.format(
                contexto=contexto,
                intents=intents_str,
                text=user_text_escaped
            )
            datos = self._call_gemini(prompt)
            if not datos:
                prompt_simple = self._PROMPT_SIMPLE.format(
                    contexto=contexto,
                    intents=intents_str,
                    text=user_text_escaped
                )
                datos = self._call_secondary_llm(prompt_simple, prefer_local=False)
        else:
            # Tareas simples: Ollama/NVIDIA local primero
            logger.info(f"Smart Routing -> SECUNDARIO (simple/rápido): '{text[:50]}'")
            prompt = self._PROMPT_SIMPLE.format(
                contexto=contexto,
                intents=intents_str,
                text=user_text_escaped
            )
            datos = self._call_secondary_llm(prompt, prefer_local=True)
            if not datos or (datos.get("intent") is None and not datos.get("respuesta")):
                logger.info("LLM Secundario no detectó acción o respuesta, delegando a Gemini...")
                prompt_complex = self._PROMPT_COMPLEX.format(
                    contexto=contexto,
                    intents=intents_str,
                    text=user_text_escaped
                )
                datos = self._call_gemini(prompt_complex)

        if datos:
            result = self._parse_routing_data(datos)
            bus.publish(EventType.INTENT_ROUTED, result)
            _dbg_perf(
                "ai_service.py:route_command",
                "route complete",
                {"total_ms": round((time.perf_counter() - t_route) * 1000, 1), "intent": result.get("intent")},
                "H4",
            )
            return result

        # --- Paso 4: fallback total ---
        _dbg_perf(
            "ai_service.py:route_command",
            "route failed",
            {"total_ms": round((time.perf_counter() - t_route) * 1000, 1)},
            "H4",
        )
        return {
            "intent": None,
            "target": None,
            "respuesta": "Lo siento, no pude procesar eso ahora mismo. ¿Puedes repetirlo?"
        }

    def _build_context(self, query: str = "", *, include_mcp: bool = True) -> str:
        """Construye contexto histórico ligero y semántico (RAG)."""
        if not self.memory:
            return ""
        
        contexto_final = ""
        q_lower = query.lower()
        
        # 1. Recuperación Semántica (RAG) - solo si hay query sustancial
        if hasattr(self.memory, 'vector_db') and self.memory.vector_db and len(query) > 8:
            try:
                contexto_semantico = self.memory.vector_db.get_context_string(query, max_results=2)
                if contexto_semantico:
                    contexto_final += contexto_semantico + "\n"
            except Exception as e:
                logger.debug(f"Fallo en RAG semántico: {e}")

        # 2. Skills: solo en consultas complejas o largas
        if include_mcp or len(query) > 40:
            contexto_plugins = plugin_loader.get_context_injection()
            if contexto_plugins:
                contexto_final += "Conocimiento de Habilidades (Skills):\n" + contexto_plugins + "\n"

        # 3. MCPs (solo si include_mcp y hay keywords relevantes)
        if include_mcp:
            mcp_tasks = []

            if self.gemini_mcp and ("gemini" in q_lower or "api" in q_lower):
                mcp_tasks.append(self.mcp_executor.submit(self.gemini_mcp.search_documentation, query))

            if self.security_mcp and any(w in q_lower for w in ["seguridad", "vulnerabilidad", "exploit", "hash"]):
                mcp_tasks.append(self.mcp_executor.submit(self.security_mcp.get_security_best_practice, query))

            if self.obsidian_mcp and any(w in q_lower for w in ["nota", "obsidian", "mi conocimiento"]):
                mcp_tasks.append(self.mcp_executor.submit(self.obsidian_mcp.search_notes, query))

            if mcp_tasks:
                try:
                    for future in as_completed(mcp_tasks, timeout=self.MCP_CONTEXT_TIMEOUT):
                        try:
                            res = future.result()
                            if res:
                                contexto_final += f"\n--- Información Externa ---\n{res}\n"
                                # Registrar que se obtuvieron resultados de MCPs
                                log_event("AIService", "mcp_context_retrieved", f"Contexto MCP obtenido para: {query[:50]}")
                        except Exception as e:
                            logger.debug(f"Error en llamada asíncrona a MCP: {e}")
                except Exception:
                    logger.debug("Timeout esperando MCPs en contexto.")

        # 3.5. VS Code Editor Context (if applicable)
        try:
            from src.core.editor_context import get_editor_context
            editor_ctx = get_editor_context()
            code_keywords = [
                "código", "codigo", "archivo", "tengo aquí", "tengo aqui", 
                "tengo abierto", "mira mi", "este código", "este codigo", 
                "esta clase", "esta función", "esta funcion", "mejorar", 
                "refactorizar", "vscode", "vs code", "mira esto", "que tengo", 
                "qué tengo", "mira"
            ]
            if any(kw in q_lower for kw in code_keywords):
                if editor_ctx:
                    fileName = editor_ctx.get("fileName", "")
                    language = editor_ctx.get("language", "")
                    code = editor_ctx.get("code", "")
                    selection = editor_ctx.get("selection")
                    
                    # Format selection details if any
                    sel_str = ""
                    if selection and selection.get("text"):
                        sel_str = f"Código Seleccionado:\n```\n{selection['text']}\n```\n"
                    
                    contexto_final += f"\n--- Contexto de VS Code Activo ---\n"
                    contexto_final += f"Archivo: {fileName}\n"
                    contexto_final += f"Lenguaje: {language}\n"
                    if sel_str:
                        contexto_final += sel_str
                    contexto_final += f"Código Completo:\n```\n{code}\n```\n"
                    contexto_final += f"----------------------------------\n"
                else:
                    contexto_final += f"\n--- Contexto de VS Code Activo ---\nNo hay ningún archivo activo o seleccionado en VS Code en este momento.\n----------------------------------\n"
        except Exception as e:
            logger.error(f"Error inyectando contexto de VS Code: {e}")

        # 4. Historial Reciente (Short-term)
        try:
            historial = self.memory.get_recent(5 if not include_mcp else 8)
            if historial:
                contexto_final += "Historial reciente:\n" + "\n".join(
                    f"{'U' if h['role'] == 'user' else 'I'}: {h['text']}"
                    for h in historial
                ) + "\n"
        except Exception as e:
            logger.debug(f"No se pudo acceder a memoria: {e}")
            
        return contexto_final

    # ------------------------------------------------------------------
    # Parseo y sanitización de respuestas
    # ------------------------------------------------------------------
    def _parse_routing_data(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae y valida intent, target, respuesta. Trunca respuesta para TTS."""
        # Normalizar intent
        intent = datos.get("intent")
        if isinstance(intent, str):
            intent = intent.strip().lower()
            if intent == "null" or intent not in self.INTENTS_VALIDOS:
                intent = None
        else:
            intent = None

        # Normalizar target
        target = datos.get("target")
        if target is None:
            # soporte legacy: buscar dentro de params si existe (por compatibilidad)
            params = datos.get("params", {})
            if "nombre_app" in params:
                target = params["nombre_app"]
            elif "query" in params:
                target = params["query"]
        if isinstance(target, dict):
            target = next(iter(target.values())) if target else None
        if not isinstance(target, str):
            target = str(target) if target is not None else ""

        # Respuesta y truncado inteligente
        respuesta = datos.get("respuesta", "Entendido.")
        if not isinstance(respuesta, str):
            respuesta = str(respuesta)

        # Truncar para TTS, respetando límite de caracteres y cortando en punto o coma
        if len(respuesta) > self.MAX_RESPUESTA_TTS:
            len_original = len(respuesta)
            truncado = respuesta[:self.MAX_RESPUESTA_TTS]
            # Buscar último separador de oración
            for sep in (". ", "? ", "! ", ", "):
                pos = truncado.rfind(sep)
                if pos > self.MAX_RESPUESTA_TTS // 2:
                    truncado = truncado[:pos + 1]
                    break
            respuesta = truncado.strip() + ("." if not truncado.endswith((".", "?", "!")) else "")
            # B6 FIX: log correcto — original -> truncado (antes estaban swapeados)
            logger.debug(f"Respuesta truncada de {len_original} a {len(respuesta)} caracteres.")

        return {"intent": intent, "target": target, "respuesta": respuesta}

    def _sanitize_response(self, resp: Dict[str, Any]) -> Dict[str, Any]:
        """Asegura que la respuesta local tenga la estructura correcta."""
        return {
            "intent": resp.get("intent"),
            "target": resp.get("target", ""),
            "respuesta": resp.get("respuesta", "")
        }

    # ------------------------------------------------------------------
    # Conversación directa (sin acciones)
    # ------------------------------------------------------------------
    def summarize(self, text: str) -> str:
        """Respuesta conversacional usando la misma lógica prioritaria."""
        if not self._ensure_models_initialized():
            return "Las capacidades de IA están apagadas."

        contexto = self._build_context(text)
        prompt = f"{contexto}\nEres Ícaro. El usuario dice: {json.dumps(text)}\nResponde brevemente en español:"

        # Para summarize, preferir Gemini (mejor calidad conversacional)
        datos_text = None
        if self.ia_habilitada:
            datos = self._call_gemini(prompt)
            if datos and "respuesta" in datos:
                return datos["respuesta"]
            # Si Gemini devuelve texto plano (no JSON)
            genai_types = self._ensure_genai_types()
            if self.client and genai_types:
                try:
                    res = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=0.4, 
                            max_output_tokens=512,
                            safety_settings=[
                                genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                            ]
                        )
                    )
                    if res and res.text:
                        return res.text.strip()[:self.MAX_RESPUESTA_TTS]
                except Exception:
                    pass

        # Fallback al LLM secundario
        datos = self._call_secondary_llm(prompt)
        if datos and "respuesta" in datos:
            return datos["respuesta"]

        return "No pude generar una respuesta en este momento."

    def summarize_session(self, messages: list) -> Optional[str]:
        """
        Genera un resumen de conocimiento crítico de una sesión.
        """
        if not messages or not (self.ia_habilitada or self.nvidia_habilitado):
            return None

        # Formatear la conversación para el prompt
        conv = "\n".join([f"{'U' if m['role'] == 'user' else 'I'}: {m['text']}" for m in messages])
        
        prompt = f"""
Analiza la siguiente conversación y extrae SOLO información importante (hechos, preferencias del usuario, datos técnicos, decisiones).
Si no hay nada relevante a largo plazo (solo saludos o charla trivial), responde 'null'.
Resumen conciso (máx 50 palabras):

CONVERSACIÓN:
{conv}
"""
        # Opción 1: Gemini
        if self.ia_habilitada:
            try:
                res = self._call_gemini(prompt)
                if res and res.get("respuesta"):
                    summary = res["respuesta"]
                    if summary.lower() == "null":
                        return None
                    return summary
                
                # Fallback si no devuelve JSON
                genai_types = self._ensure_genai_types()
                if self.client and genai_types:
                    res = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=0.2, 
                            max_output_tokens=256,
                            safety_settings=[
                                genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                                genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
                            ]
                        )
                    )
                    text = res.text.strip()
                    if text.lower() == "null":
                        return None
                    return text
            except Exception as e:
                logger.error(f"Error en summarize_session con Gemini: {e}")

        # Opción 2: NVIDIA DeepSeek (v4 Flash)
        if self.nvidia_habilitado:
            try:
                logger.info("Generando resumen de sesión con NVIDIA DeepSeek...")
                res = self._call_nvidia(prompt)
                if res and res.get("respuesta"):
                    summary = res["respuesta"]
                    if summary.lower() == "null":
                        return None
                    return summary
            except Exception as e:
                logger.error(f"Error en summarize_session con NVIDIA DeepSeek: {e}")

        return None

    def fallback_response(self) -> str:
        return "No pude entender eso, ¿puedes repetirlo?"

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado de salud de todos los subsistemas de IA."""
        return {
            "gemini_cloud": self.ia_habilitada,
            "ollama_local": self.ollama_habilitado,
            "nvidia_deepseek": self.nvidia_habilitado,
            "mcps": {
                "gemini_docs": self.gemini_mcp.enabled if self.gemini_mcp else False,
                "security": self.security_mcp.enabled if self.security_mcp else False,
                "obsidian": self.obsidian_mcp.enabled if self.obsidian_mcp else False,
                "github": self.github_mcp.enabled if self.github_mcp else False
            }
        }

    def disable_ai(self) -> None:
        """Desactiva todos los motores de IA."""
        self._ai_disabled = True
        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.nvidia_habilitado = False
        self._models_initialized = True
        logger.info("IA desactivada explícitamente.")
