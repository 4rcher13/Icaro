"""
Widget UI de Ícaro — Ventana flotante glassmorphism.

Escucha telemetría UDP del asistente y actualiza la UI en tiempo real.

Protocolo UDP recibido: "estado|transcripcion|respuesta"
  - estado:       initializing | sleeping | listening | thinking | speaking | error
  - transcripcion: Texto que el usuario dijo (puede estar vacío).
  - respuesta:    Última respuesta de Ícaro (puede estar vacía).
"""
import webview
import threading
import socket
import os
from typing import Optional

class Api:
    """Puente Python↔JavaScript expuesto al widget HTML."""

    def __init__(self, window_container: list[Optional[webview.Window]]) -> None:
        self._refs = window_container

    def close(self) -> None:
        """Llamado desde el botón × del widget para cerrar la ventana."""
        try:
            if self._refs[0]:
                self._refs[0].destroy()
        except Exception as exc:
            print(f"[UI] Error cerrando ventana: {exc}")


def _escape_js(s: str) -> str:
    """Escapa una cadena para pasarla como argumento de string JS con comillas simples."""
    return (
        s.replace("\\", "\\\\")
         .replace("'",  "\\'")
         .replace("\n", " ")
         .replace("\r", "")
    )


def udp_listener(window: webview.Window) -> None:
    """
    Hilo daemon que escucha paquetes UDP y reenvía cambios de estado al HTML.
    Timeout de 1 s para que el hilo pueda terminar limpiamente al cerrar la app.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 5005))
        sock.settimeout(1.0)
        print("[UI] Escuchando telemetría en 127.0.0.1:5005")
    except Exception as exc:
        print(f"[UI ERR] No se pudo vincular puerto 5005: {exc}")
        return

    while True:
        try:
            data, _ = sock.recvfrom(1024)
            payload = data.decode("utf-8").strip()

            parts = payload.split("|", 2)
            state      = parts[0] if len(parts) > 0 else "sleeping"
            transcript = parts[1] if len(parts) > 1 else ""
            response   = parts[2] if len(parts) > 2 else ""

            window.evaluate_js(
                f"changeState('{_escape_js(state)}',"
                f"'{_escape_js(transcript)}',"
                f"'{_escape_js(response)}')"
            )

        except socket.timeout:
            continue  # Normal — permite re-chequear sin bloquear para siempre
        except OSError:
            break     # Socket cerrado → salir limpiamente
        except Exception as exc:
            print(f"[UI ERR] Telemetría: {exc}")


if __name__ == "__main__":
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widget.html")

    window_ref: list[Optional[webview.Window]] = [None]
    api = Api(window_ref)

    window = webview.create_window( #
        "Ícaro",
        url=html_path,
        width=400,
        height=440,
        frameless=True,
        transparent=True,
        on_top=True,
        js_api=api,
    )

    window_ref[0] = window

    threading.Thread(target=udp_listener, args=(window,), daemon=True).start()
    webview.start(debug=False)
