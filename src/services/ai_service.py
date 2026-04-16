import json
import time

try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    genai = None

try:
    import ollama
except ImportError:
    ollama = None

import logging
from ..config.settings import GEMINI_API_KEY, MODELO_LOCAL

logger = logging.getLogger(__name__)

class AIService:
    """Motor Cognitivo y Router Lógico de Ícaro."""
    
    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.modelo_local = MODELO_LOCAL
        self.client = None
        self.chat = None
        self._models_initialized = False
        
        self.herramientas_schema = """
- buscar_google(query="texto a buscar")
- control_volumen(accion="subir" o "bajar" o "silenciar")
- reproducir_youtube(query="nombre video")
- cerrar_ventana(nombre_ventana="nombre")
- abrir_aplicacion(nombre_app="nombre de aplicacion como vscode, word, etc.")
- crear_carpeta(nombre="nombre")
- escribir_texto(texto="texto a escribir")
- dar_hora_fecha(tipo="hora" o "fecha")
- suspender_equipo()
- hacer_click()
"""

    def _ensure_models_initialized(self) -> bool:
        if self._models_initialized:
            return self.ia_habilitada or self.ollama_habilitado
            
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY no configurada, fallando a local pasivamente.")
            
        self._models_initialized = True
        
        # Nube: Gemini
        api_key = GEMINI_API_KEY
        if genai and api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                self.instruccion_sistema = (
                    "Eres Ícaro, asistente inteligente. "
                    "Habla natural, directo y sé conciso."
                )
                self.chat = self.client.chats.create(
                    model='gemini-2.5-flash',
                    config=types.GenerateContentConfig(
                        system_instruction=self.instruccion_sistema,
                        temperature=0.75
                    )
                )
                self.ia_habilitada = True
            except Exception as e:
                logger.error(f"Fallo Gemini: {e}")

        # Local: Ollama
        if ollama:
            try:
                ollama.list()
                self.ollama_habilitado = True
            except Exception:
                logger.warning("Ollama offline.")
                
        return self.ia_habilitada or self.ollama_habilitado

    def route_command(self, text: str) -> dict:
        """
        Interpreta el texto y devuelve un Action Intent ({intent, target, respuesta}).
        Prioriza el modelo local para latencia cero.
        """
        # 1. Fallback rápido (Despierto/saludos)
        if text.lower() in ["hola", "hey", "hola icaro", "hey icaro"]:
            return {"intent": None, "target": None, "respuesta": "Hola, a tu servicio."}
            
        if not self._ensure_models_initialized():
            return {"intent": None, "target": None, "respuesta": "Sistemas cognitivos no configurados."}
        
        desc = self.herramientas_schema
        prompt_enrutamiento = f"""
Comando del usuario: "{text}"
HERRAMIENTAS: {desc}
Devuelve EXCLUSIVAMENTE un JSON con:
{{"intent": "nombre_o_null", "target": "parametro", "respuesta": "que dirias tú"}}
Ejemplo: {{"intent": "abrir_aplicacion", "target": "vscode", "respuesta": "Abriendo visual studio"}}
"""
        # Intentar LOCAL primero
        if self.ollama_habilitado:
            try:
                res = ollama.chat(
                    model=self.modelo_local, 
                    messages=[{"role": "user", "content": prompt_enrutamiento}],
                    format='json',
                    options={'temperature': 0.1, 'num_predict': 150}
                )
                datos = json.loads(res['message']['content'])
                return self._parse_routing_data(datos)
            except Exception as e:
                logger.warning(f"Error Local: {e}, fallback nube.")

        # Fallback NUBE
        if self.ia_habilitada:
            try:
                prompt_enrutamiento += "\nNO uses ```json en la respuesta, solo texto plano JSON."
                res = self.chat.send_message(prompt_enrutamiento)
                texto_limpio = res.text.replace("```json", "").replace("```", "").strip()
                datos = json.loads(texto_limpio)
                return self._parse_routing_data(datos)
            except Exception as e:
                logger.error(f"Error Nube: {e}")
                
        # Fallback Total
        return {"intent": None, "target": None, "respuesta": "Mis sistemas cognitivos están offline."}
        
    def _parse_routing_data(self, datos: dict) -> dict:
        intent = datos.get("intent")
        target = datos.get("target") or datos.get("params", {}).get("nombre_app", "") # Helper para errores de estructura
        if isinstance(target, dict) and target: # Si el modelo devuelve params dentro de target
             target = list(target.values())[0]
        respuesta = datos.get("respuesta", "Entendido.")
        
        if intent in ("null", "None", ""):
            intent = None

        return {"intent": intent, "target": target, "respuesta": respuesta}

    def summarize(self, text: str) -> str:
        """Da una respuesta directa a una charla/resumen sin lanzar acciones."""
        if not self._ensure_models_initialized():
            return "Las capacidades IA están apagadas."
            
        if self.ia_habilitada:
            try:
                return self.chat.send_message(text).text
            except: pass
        return "Resumen no disponible ahora."
        
    def fallback_response(self) -> str:
        return "No pude entender eso, ¿puedes repetirlo?"
