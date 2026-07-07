import logging
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _interpreter_shutting_down() -> bool:
    return getattr(sys, "is_finalizing", lambda: False)()

# ─── ChromaDB (import ligero, ~0.1s) ──────────────────────────────────────
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB no disponible. La memoria RAG estará desactivada.")

if CHROMADB_AVAILABLE:
    from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

    class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
        """
        Función de embedding para ChromaDB utilizando google-genai y gemini-embedding-2.
        Implementa el protocolo EmbeddingFunction de ChromaDB.
        """
        def __init__(self, api_key: Optional[str] = None):
            self._api_key = api_key
            self._client = None

        def __call__(self, input: Documents) -> Embeddings:
            if not self._client:
                import google.genai as genai
                key = self._api_key
                if not key:
                    from ..config.settings import GEMINI_API_KEY
                    key = GEMINI_API_KEY
                self._client = genai.Client(api_key=key)

            try:
                response = self._client.models.embed_content(
                    model="gemini-embedding-2",
                    contents=input,
                )
                return [e.values for e in response.embeddings]
            except Exception as e:
                logger.error(f"Error en GeminiEmbeddingFunction: {e}")
                raise e

        @staticmethod
        def name() -> str:
            return "gemini-embedding-2"

        @staticmethod
        def build_from_config(config: dict) -> "GeminiEmbeddingFunction":
            return GeminiEmbeddingFunction(api_key=config.get("api_key"))

        def get_config(self) -> dict:
            return {"api_key": self._api_key}
else:
    GeminiEmbeddingFunction = None  # type: ignore


_embedding_model = None
_embedding_lock = threading.Lock()  # Protege acceso a _embedding_model y _embedding_failed
_embedding_ready = threading.Event()   # Se pone en "set" cuando el modelo está listo
_embedding_failed = False              # Bandera para no reintentar si falló
_active_instances: list["VectorMemory"] = []
_instances_lock = threading.Lock()
_embedding_thread = None  # Referencia al thread de carga en background


def _initialize_embedding_model_background() -> None:
    """
    Inicia el thread de carga de embeddings en background si aún no está corriendo.
    Esta función DEBE llamarse al menos una vez durante la inicialización del módulo.
    """
    global _embedding_thread
    
    if _embedding_ready.is_set() or _embedding_thread is not None:
        return
    
    def load_model():
        _load_embedding_model_background()
    
    _embedding_thread = threading.Thread(target=load_model, daemon=True, name="VectorMemoryEmbeddingLoader")
    _embedding_thread.start()


def _load_embedding_model_background() -> None:
    """
    Configura la función de embeddings (Gemini o fallback local de ChromaDB) en background.
    Protegido por lock para evitar race conditions.
    """
    global _embedding_model, _embedding_failed

    if _embedding_ready.is_set():
        return

    if not CHROMADB_AVAILABLE or _interpreter_shutting_down():
        _embedding_ready.set()
        return

    try:
        from ..config.settings import GEMINI_API_KEY
        if GEMINI_API_KEY:
            _embedding_model = GeminiEmbeddingFunction(api_key=GEMINI_API_KEY)
            logger.info("Modelo de embeddings Gemini listo.")
        else:
            from chromadb.utils import embedding_functions
            _embedding_model = embedding_functions.DefaultEmbeddingFunction()
            logger.warning("GEMINI_API_KEY no encontrada. Usando DefaultEmbeddingFunction local.")
    except Exception as e:
        logger.error(f"Error inicializando embeddings: {e}")
        _embedding_failed = True
    finally:
        _embedding_ready.set()


def get_embedding_model(timeout: float = 90.0):
    """
    Devuelve el modelo de embeddings cuando esté disponible.
    Bloquea como máximo `timeout` segundos (solo en la primera query).
    Si el modelo aún no está listo, espera; si falló, retorna None.
    """
    if _embedding_failed:
        return None
    if not _embedding_ready.is_set():
        logger.debug("Esperando que el modelo de embeddings termine de cargar...")
        _embedding_ready.wait(timeout=timeout)
    return _embedding_model


class VectorMemory:
    """
    Memoria semántica persistente usando ChromaDB.
    El modelo de embeddings se carga en background; el cliente ChromaDB
    se inicializa de forma lazy en la primera operación real.
    """

    def __init__(self, db_path: str = "data/chroma_db"):
        self.enabled = CHROMADB_AVAILABLE
        self.collection = None
        self.client = None
        self._db_path = db_path
        self._closed = False

        # Validar/crear directorio base
        if self.enabled:
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"No se pudo crear directorio para ChromaDB en '{db_path}': {e}")
                self.enabled = False

        # Worker para guardar memorias sin bloquear la respuesta
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="VecMemWorker")

        # Iniciar carga de embeddings en background (solo una vez por proceso)
        _initialize_embedding_model_background()

        with _instances_lock:
            _active_instances.append(self)

    def _ensure_collection(self) -> bool:
        """Crea/obtiene la colección cuando el modelo de embeddings esté disponible (lazy client)."""
        if not self.enabled or self._closed or _interpreter_shutting_down():
            return False
            
        if self.client is None:
            try:
                self.client = chromadb.PersistentClient(path=self._db_path)
                logger.info(f"VectorMemory: cliente ChromaDB inicializado en '{self._db_path}'.")
            except Exception as e:
                logger.error(f"No se pudo abrir ChromaDB en '{self._db_path}': {e}")
                self.enabled = False
                return False

        if self.collection is not None:
            return True

        embed_fn = get_embedding_model()
        if not embed_fn:
            logger.warning("Modelo de embeddings no disponible. VectorMemory desactivada.")
            self.enabled = False
            return False

        try:
            self.collection = self.client.get_or_create_collection(
                name="icaro_memories",
                embedding_function=embed_fn,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("Colección ChromaDB obtenida/creada exitosamente.")
            return True
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("atexit", "shutdown", "interpreter")):
                self.enabled = False
                logger.debug(f"Error creando colección ChromaDB durante apagado: {e}")
                return False
            
            # Intentar recrear si hay desajuste de dimensiones
            logger.warning(f"Error obteniendo colección (posible desajuste de dimensiones). Recreando: {e}")
            try:
                self.client.delete_collection(name="icaro_memories")
                self.collection = self.client.get_or_create_collection(
                    name="icaro_memories",
                    embedding_function=embed_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info("Colección recreada exitosamente.")
                return True
            except Exception as e2:
                logger.error(f"Error crítico al recrear colección ChromaDB: {e2}")
                self.enabled = False
                return False

    def _add_memory_task(self, role: str, text: str, intent: Optional[str] = None) -> None:
        """Tarea real de guardado (se ejecuta en el worker thread)."""
        if self._closed or not self._ensure_collection():
            return

        timestamp = time.time()
        memory_id = f"mem_{int(timestamp * 1000)}"
        metadata = {
            "role": role,
            "timestamp": timestamp,
            "intent": intent or "none",
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[memory_id],
            )
            logger.debug(f"Memoria guardada: {memory_id}")
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("atexit", "shutdown", "interpreter")):
                logger.debug(f"Escritura VectorMemory omitida durante apagado: {e}")
            else:
                logger.error(f"Error guardando en VectorMemory: {e}", exc_info=True)

    def add_memory(self, role: str, text: str, intent: Optional[str] = None, wait: bool = False) -> None:
        """Encola el guardado de una memoria (no bloquea). Si wait=True, lo hace de forma síncrona."""
        if not self.enabled or self._closed or not text or len(text.strip()) < 5:
            return
        
        if wait:
            self._add_memory_task(role, text, intent)
        else:
            try:
                self.executor.submit(self._add_memory_task, role, text, intent)
            except RuntimeError as e:
                # Executor cerrado
                logger.debug(f"No se pudo encolar memoria (executor cerrado): {e}")

    def shutdown(self, wait: bool = True) -> None:
        """Detiene el worker y evita escrituras durante el apagado del intérprete."""
        if self._closed:
            return  # Ya cerrado
            
        self._closed = True
        self.enabled = False
        
        try:
            self.executor.shutdown(wait=wait)
        except Exception as e:
            logger.warning(f"Error durante shutdown del executor: {e}")
        
        with _instances_lock:
            try:
                _active_instances.remove(self)
            except ValueError:
                pass  # Ya removido


    def query_memories(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Busca las memorias semánticamente más similares a la consulta."""
        if not self.enabled or not query or self._closed:
            return []
        if not self._ensure_collection():
            return []

        try:
            results = self.collection.query(query_texts=[query], n_results=n_results)
            docs = results.get("documents", [[]])[0] if results.get("documents") else []
            metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
            dists = results.get("distances", [[]])[0] if results.get("distances") else []
            
            # Evitar IndexError si alguna lista está vacía
            if not docs:
                return []
                
            return [
                {"text": docs[i], "metadata": metas[i], "distance": dists[i] if i < len(dists) else None}
                for i in range(len(docs))
            ]
        except Exception as e:
            logger.error(f"Error consultando VectorMemory: {e}", exc_info=True)
            return []

    def get_context_string(self, query: str, max_results: int = 3) -> str:
        """Retorna fragmentos relevantes formateados para inyectar en el prompt."""
        if not query or self._closed:
            return ""
            
        memories = self.query_memories(query, n_results=max_results)
        if not memories:
            return ""
            
        lines = ["Fragmentos relevantes de conversaciones pasadas:"]
        for mem in memories:
            try:
                role = "Usuario" if mem.get("metadata", {}).get("role") == "user" else "Ícaro"
                text = mem.get("text", "")
                if text:
                    lines.append(f"- {role}: {text}")
            except Exception as e:
                logger.warning(f"Error procesando memoria en get_context_string: {e}")
                
        return "\n".join(lines) + "\n" if len(lines) > 1 else ""


def shutdown_all_instances(wait: bool = False) -> None:
    """Cierra todos los VectorMemory activos (p. ej. al terminar pytest)."""
    with _instances_lock:
        instances = list(_active_instances)
    
    for vm in instances:
        try:
            vm.shutdown(wait=wait)
        except Exception as e:
            logger.warning(f"Error cerrando VectorMemory instance: {e}")
