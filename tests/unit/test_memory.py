import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestMemory(unittest.TestCase):
    def setUp(self):
        # Crear archivo temporal real — sin residuos, sin tocar disco del proyecto
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp_path = Path(self.tmp.name)
        self.tmp.close()
        self.tmp_path.unlink()  # queremos que no exista aún al empezar
        
        self.patcher = patch("src.core.memory_manager.HISTORY_FILE", self.tmp_path)
        self.patcher.start()
        
        from src.core.memory_manager import MemoryManager
        self.MemoryManager = MemoryManager

    def tearDown(self):
        self.patcher.stop()
        if self.tmp_path.exists():
            self.tmp_path.unlink()

    def test_guardar_y_cargar(self):
        mem = self.MemoryManager(buffer_size=1)  # Flush after every write
        mem.guardar("user", "Hola")
        mem.flush()  # Ensure data is written to disk
        
        # Simular reinicio leyendo desde disco
        mem2 = self.MemoryManager()
        self.assertEqual(len(mem2.cargar()), 1)
        self.assertEqual(mem2.cargar()[0]["text"], "Hola")

    def test_limite_historial(self):
        mem = self.MemoryManager()
        mem.max_items = 2
        
        mem.guardar("user", "Uno")
        mem.guardar("model", "Dos")
        mem.guardar("user", "Tres")
        
        historial = mem.cargar()
        self.assertEqual(len(historial), 2)
        self.assertEqual(historial[0]["text"], "Dos")
        self.assertEqual(historial[1]["text"], "Tres")

    def test_json_corrupto(self):
        # Escribir JSON inválido intencionalmente
        self.tmp_path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_path.write_text("{invalid_json_;;;;}", encoding="utf-8")
        
        mem = self.MemoryManager()
        historial = mem.cargar()
        self.assertEqual(historial, [])

    def test_historial_vacio_en_archivo_nuevo(self):
        mem = self.MemoryManager()
        self.assertEqual(mem.cargar(), [])

    def test_guardar_multiples_roles(self):
        mem = self.MemoryManager()
        mem.guardar("user", "¿Qué hora es?")
        mem.guardar("model", "Son las 3 PM.")
        mem.guardar("user", "Gracias.")
        h = mem.cargar()
        self.assertEqual(len(h), 3)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[1]["role"], "model")


if __name__ == "__main__":
    unittest.main()

