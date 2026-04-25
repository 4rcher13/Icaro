import logging
from difflib import get_close_matches
try:
    from rapidfuzz import process, fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

# Flujo procesar -> normalizar -> enrutar -> ejecutar

logger = logging.getLogger(__name__)

# Vocabulario canónicos de intents locales reconocibles por fonética
_INTENT_KEYWORDS = [
    "hora", "fecha", "calculadora", "notepad", "código", "abrir",
    "cerrar", "buscar", "youtube", "volumen", "subir", "bajar",
    "salir", "apagar", "suspender", "carpeta", "copiar", "pegar",
]

class CommandProcessor:
    """
    Router principal de la lógica.
    Pipeline unidireccional: normalizar → enrutar → ejecutar → responder
    """
    
    def __init__(self, ai_service, action_service, use_rapidfuzz: bool = False):
        self.ai = ai_service
        self.action = action_service
        self.use_rapidfuzz = use_rapidfuzz and RAPIDFUZZ_AVAILABLE

    def process(self, comando: str) -> str:
        """Procesa un comando completo siguiendo el pipeline de 4 etapas."""
        # Etapa 1: Normalizar (limpia, corrige fonética)
        clean = self._normalize(comando)
        
        # Etapa 2: Enrutar (IA decidir intención)
        intent_data = self._route(clean)
        
        # Etapa 3: Ejecutar acción si aplica
        respuesta = self._execute(intent_data)
        
        # Etapa 4: Postprocesar (retornar texto final para el audio)
        return respuesta

    def _normalize(self, text: str) -> str:
        """
        Limpia el texto crudo del reconocedor.
        Aplica corrección fonética básica via rapidfuzz o difflib.
        """
        text = text.lower().strip()
        words = text.split()
        corrected = []
        
        for word in words:
            # Solo aplicar fuzzy-matching a palabras de 4+ caracteres
            # para evitar falsos positivos (ej. 'hola' → 'hora')
            if len(word) >= 4:
                if self.use_rapidfuzz:
                    match_data = process.extractOne(
                        word, _INTENT_KEYWORDS, scorer=fuzz.ratio
                    )
                    # Threshold 90% — debe ser muy similar para corregir
                    if match_data and match_data[1] >= 90:
                        corrected.append(match_data[0])
                        continue
                else:
                    matches = get_close_matches(word, _INTENT_KEYWORDS, n=1, cutoff=0.90)
                    if matches:
                        corrected.append(matches[0])
                        continue
            corrected.append(word)
                
        result = " ".join(corrected)
        if result != text:
            engine = "rapidfuzz" if self.use_rapidfuzz else "difflib"
            logger.debug(f"Corrección fonética ({engine}): '{text}' → '{result}'")
        return result

    def _route(self, clean: str) -> dict:
        """Delega a la IA para clasificar la intención del comando."""
        return self.ai.route_command(clean)

    def _execute(self, intent_data: dict) -> str:
        """Ejecuta la acción del sistema operativo si hay intent, devuelve la respuesta hablada."""
        respuesta_hablada = intent_data.get("respuesta", "Entendido.")
        
        if intent_data.get("intent"):
            resultado_accion = self.action.execute(intent_data)
            # Comandos como hora/fecha, el resultado de la acción ES la respuesta
            if intent_data.get("intent") in ("dar_hora_fecha",):
                return resultado_accion
            if resultado_accion and not resultado_accion.startswith("Acción desconocida"):
                logger.info(f"Sistema: {resultado_accion}")
            elif resultado_accion and resultado_accion.startswith("Acción desconocida"):
                # La IA devolvió un intent de conversación ficticio — solo log debug
                logger.debug(f"Intent conversacional ignorado por ActionService: {resultado_accion}")

        return respuesta_hablada

