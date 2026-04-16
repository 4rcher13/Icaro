import unittest
import os
import json
from pathlib import Path

# Parchear el HISTORY_FILE antes de cargar MemoryManager
import src.config.settings as settings
from unittest.mock import patch

class TestMemory(unittest.TestCase):
    def setUp(self):
        # Usar un archivo temporal para la prueba dentro del directorio temp 
        self.test_file_path = settings.BASE_DIR / "data" / "historial_test.json"
        if self.test_file_path.exists():
            self.test_file_path.unlink()
            
        self.patcher = patch('src.core.memory_manager.HISTORY_FILE', self.test_file_path)
        self.patcher.start()
        
        from src.core.memory_manager import MemoryManager
        self.MemoryManager = MemoryManager

    def tearDown(self):
        self.patcher.stop()
        if self.test_file_path.exists():
            self.test_file_path.unlink()

    def test_guardar_y_cargar(self):
        mem = self.MemoryManager()
        mem.guardar("user", "Hola")
        
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
        # Escribir archivo no válido intencionalmente
        self.test_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write("{invalid_json_;;;;}")
        
        mem = self.MemoryManager()
        historial = mem.cargar()
        self.assertEqual(historial, [])
        
if __name__ == "__main__":
    unittest.main()
