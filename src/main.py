import sys
import logging
import argparse
from pathlib import Path

# Añadir el directorio raíz al path si es necesario (para ejecución directa)
sys.path.append(str(Path(__file__).parent.parent))

from src.config.settings import LOGS_DIR, LOG_FILE
from src.core.icaro import Icaro

def main():
    parser = argparse.ArgumentParser(description="Ícaro — Asistente de Voz Modular")
    parser.add_argument("--debug",   action="store_true", help="Activa logs nivel DEBUG")
    parser.add_argument("--silent",  action="store_true", help="Desactiva síntesis de voz al arrancar")
    parser.add_argument("--no-ai",   action="store_true", help="Desactiva la IA; solo comandos locales")
    args = parser.parse_args()

    # Asegurar existencia de carpeta logs
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Configurar logging según flag
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info("Arrancando Ícaro desde main principal.")
    asistente = Icaro(silent=args.silent, no_ai=args.no_ai)
    asistente.iniciar()

if __name__ == "__main__":
    main()