"""
Tests unitarios del AIService.
Actualizados para Smart Routing y la nueva API.

Ejecutar: python -m pytest tests/test_ai.py -v
"""
import unittest
from unittest.mock import patch, MagicMock
from src.services.ai_service import AIService, _is_complex_query


class TestAI(unittest.TestCase):
    def setUp(self):
        self.patcher_ollama = patch("src.services.ai_service.ollama", new=None)
        self.patcher_genai = patch("src.services.ai_service.genai", new=None)
        self.patcher_openai = patch("src.services.ai_service.OpenAI", new=None)
        self.patcher_ollama.start()
        self.patcher_genai.start()
        self.patcher_openai.start()
        
        self.mem_mock = MagicMock()
        self.mem_mock.get_recent.return_value = []
        self.ai = AIService(self.mem_mock, warmup=False)
        
    def tearDown(self):
        patch.stopall()
        
    def test_routing_empty_prompt(self):
        """Prompt vacío retorna intent None."""
        self.ai.ia_habilitada = False
        self.ai.ollama_habilitado = False
        self.ai._models_initialized = True
        res = self.ai.route_command("")
        self.assertIsNone(res.get("intent"))

    def test_routing_saludos_local(self):
        """Saludos se resuelven por local_fallback sin tocar IA."""
        res = self.ai.route_command("hola")
        self.assertEqual(res["respuesta"], "Hola, ¿en qué te ayudo?")
        self.assertIsNone(res["intent"])

    def test_routing_hora_local(self):
        """Comando de hora se resuelve localmente."""
        res = self.ai.route_command("qué hora es")
        self.assertEqual(res["intent"], "dar_hora_fecha")

    def test_routing_fallback_nube(self):
        """Si local falla, usa Gemini como fallback."""
        self.ai.ia_habilitada = True
        self.ai.ollama_habilitado = False
        self.ai._models_initialized = True
        self.ai.client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"intent": "abrir_aplicacion", "target": "excel", "respuesta": "Abriendo Excel"}'
        self.ai.client.models.generate_content.return_value = mock_response
        
        # Usar un comando que NO se resuelve localmente (sin palabras clave como abre/busca/pon/hora)
        res = self.ai.route_command("necesito que me lances el programa de hojas de cálculo por favor amigo")
        self.assertEqual(res["intent"], "abrir_aplicacion")
        self.assertEqual(res["target"], "excel")

    def test_routing_exception_api(self):
        """Si la API falla, retorna fallback seguro."""
        self.ai.ia_habilitada = True
        self.ai.ollama_habilitado = False
        self.ai.nvidia_habilitado = False
        self.ai._models_initialized = True
        self.ai.client = MagicMock()
        self.ai.client.models.generate_content.side_effect = Exception("API Caída o Timeout")
        
        # Usar un comando que NO se resuelve localmente
        res = self.ai.route_command("necesito ayuda con un problema complejo de programación avanzada")
        self.assertIsNone(res["intent"])
        
    def test_parse_routing_data_valid(self):
        """_parse_routing_data extrae correctamente datos válidos."""
        datos = {
            "intent": "abrir_aplicacion",
            "target": "notepad",
            "respuesta": "Abriendo Notepad."
        }
        result = self.ai._parse_routing_data(datos)
        self.assertEqual(result["intent"], "abrir_aplicacion")
        self.assertEqual(result["target"], "notepad")
        self.assertEqual(result["respuesta"], "Abriendo Notepad.")
    
    def test_parse_routing_data_invalid_intent(self):
        """Intent inválido se convierte en None."""
        datos = {
            "intent": "intent_falso",
            "target": "algo",
            "respuesta": "Test"
        }
        result = self.ai._parse_routing_data(datos)
        self.assertIsNone(result["intent"])
    
    def test_parse_routing_data_null_string(self):
        """El string 'null' se convierte en None."""
        datos = {
            "intent": "null",
            "target": None,
            "respuesta": "Hola"
        }
        result = self.ai._parse_routing_data(datos)
        self.assertIsNone(result["intent"])
    
    def test_extraer_json_static_method(self):
        """_extraer_json funciona como método estático."""
        result = AIService._extraer_json('{"intent": "test"}')
        self.assertEqual(result, {"intent": "test"})
        
        result = AIService._extraer_json("no json here")
        self.assertIsNone(result)
    
    def test_sanitize_response(self):
        """_sanitize_response normaliza la estructura."""
        resp = {"intent": "test", "target": "a", "respuesta": "b", "extra": "c"}
        result = self.ai._sanitize_response(resp)
        self.assertEqual(result, {"intent": "test", "target": "a", "respuesta": "b"})
    
    def test_routing_sin_api_key(self):
        """Sin API key configurada, debe devolver respuesta de sistema degradado."""
        with patch("src.services.ai_service.GEMINI_API_KEY", None):
            self.ai._models_initialized = True
            self.ai.ia_habilitada = False
            self.ai.ollama_habilitado = False
            self.ai.nvidia_habilitado = False
            
            # Comando que no tiene fallback local
            res = self.ai.route_command("explícame que es machine learning")
            self.assertIsNone(res.get("intent"))

    def test_build_context_skips_rag_for_simple_queries(self):
        """Consultas simples no deberían disparar RAG ni contexto pesado."""
        mem = MagicMock()
        mem.get_recent.return_value = []
        mem.vector_db = MagicMock()
        mem.vector_db.get_context_string.return_value = "contexto" 
        ai = AIService(mem, warmup=False)

        context = ai._build_context("abre youtube")

        self.assertEqual(context, "")
        mem.vector_db.get_context_string.assert_not_called()

    def test_disable_ai(self):
        """disable_ai() desactiva todos los motores."""
        self.ai.ia_habilitada = True
        self.ai.ollama_habilitado = True
        self.ai.nvidia_habilitado = True
        
        self.ai.disable_ai()
        
        self.assertFalse(self.ai.ia_habilitada)
        self.assertFalse(self.ai.ollama_habilitado)
        self.assertFalse(self.ai.nvidia_habilitado)

    def test_truncado_respuesta_larga(self):
        """Respuestas largas se truncan para TTS."""
        datos = {
            "intent": None,
            "target": None,
            "respuesta": "A" * 4500
        }
        result = self.ai._parse_routing_data(datos)
        self.assertLessEqual(len(result["respuesta"]), self.ai.MAX_RESPUESTA_TTS + 5)
        self.assertGreater(len(result["respuesta"]), 100)


class TestSmartRoutingClassifier(unittest.TestCase):
    """Tests del clasificador de complejidad."""
    
    def test_simple_commands(self):
        self.assertFalse(_is_complex_query("abre youtube"))
        self.assertFalse(_is_complex_query("sube volumen"))
        self.assertFalse(_is_complex_query("qué hora es"))
        self.assertFalse(_is_complex_query("pon radiohead"))
    
    def test_complex_commands(self):
        self.assertTrue(_is_complex_query("explícame los punteros en C"))
        self.assertTrue(_is_complex_query("investiga sobre machine learning"))
        self.assertTrue(_is_complex_query("analiza este código"))
        self.assertTrue(_is_complex_query("genera una función de ordenamiento"))
    
    def test_long_text_is_complex(self):
        """Textos largos (>60 chars) se clasifican como complejos."""
        long_text = "esto es un texto que tiene mas de sesenta caracteres para probar la clasificacion"
        self.assertTrue(_is_complex_query(long_text))


if __name__ == "__main__":
    unittest.main()
