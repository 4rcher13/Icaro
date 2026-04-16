"""
main/cerebro.py — Enrutador Inteligente (IA LOCAL decide qué acción ejecutar)
"""

from herramientas import acciones
from logica.plugins.copiloto_vscode import copiloto_vscode_plugin

class Cerebro:
    def __init__(self, cerebro_memoria):
        self.memoria = cerebro_memoria  # Instancia de CerebroIcaro
        
        # Descripciones de las herramientas para que la IA entienda qué hacen
        self.desc_herramientas = """
- buscar_google(query="texto a buscar"): Busca algo en Google
- control_volumen(accion="subir" o "bajar" o "silenciar"): Controla el volumen del sistema
- reproducir_youtube(query="nombre video"): Busca en Youtube y lo reproduce
- cerrar_ventana(nombre_ventana="nombre"): Cierra una ventana o pestaña visible
- abrir_aplicacion(nombre_app="nombre"): Abre una aplicación instalada
- crear_carpeta(nombre="nombre"): Crea una carpeta en el escritorio
- escribir_texto(texto="texto a escribir"): Escribe un texto usando el teclado simulado
- dar_hora_fecha(tipo="hora" o "fecha"): Retorna la hora o fecha actual
- suspender_equipo(): Suspende el PC inmediatamente
- hacer_click(): Simula un click izquierdo del ratón (útil para interactuar con la pantalla, dar click en un video)
- analizar_archivo(nombre="nombre.py"): Analiza un archivo del código fuente actual usando IA
- escanear_proyecto(carpeta="nombre"): Analiza toda una carpeta con IA
- copiloto_vscode(): Se conecta a VS code para analizar y arreglar el archivo activo
- usar_gemini(query="texto de la consulta de código o compleja del usuario"): Envía la petición a la IA en la Nube (Gemini) a procesar. Úsalo SIEMPRE que la petición implique redactar código, resolver problemas algorítmicos o requiera respuestas extensas e investigativas.
"""

    def procesar_comando(self, comando: str) -> str:
        """
        Recibe el texto del usuario, pide a la IA que decida qué herramienta usar,
        ejecuta la herramienta y devuelve el texto que debe hablar el asistente.
        """
        # Paso 1: Pedir a la IA que enrute el comando
        hrrm, params, resp_ia = self.memoria.enrutar_comando(comando, self.desc_herramientas)
        
        if not hrrm:
            # Es conversación libre, o fallo, solo retornar la respuesta
            return resp_ia
            
        print(f"[Cerebro] IA decidió usar herramienta: {hrrm} con parámetros: {params}")
        
        # Paso 2: Ejecutar la herramienta correspondiente
        resultado_ejecucion = ""
        
        try:
            if hrrm == "buscar_google":
                resultado_ejecucion = acciones.buscar_google(params.get("query", ""))
            elif hrrm == "control_volumen":
                resultado_ejecucion = acciones.control_volumen(params.get("accion", ""))
            elif hrrm == "reproducir_youtube":
                resultado_ejecucion = acciones.reproducir_youtube(params.get("query", ""))
            elif hrrm == "cerrar_ventana":
                resultado_ejecucion = acciones.cerrar_ventana(params.get("nombre_ventana", ""))
            elif hrrm == "abrir_aplicacion":
                resultado_ejecucion = acciones.abrir_aplicacion(params.get("nombre_app", ""))
            elif hrrm == "crear_carpeta":
                resultado_ejecucion = acciones.crear_carpeta(params.get("nombre", ""))
            elif hrrm == "escribir_texto":
                resultado_ejecucion = acciones.escribir_texto(params.get("texto", ""))
            elif hrrm == "dar_hora_fecha":
                resultado_ejecucion = acciones.dar_hora_fecha(params.get("tipo", "hora"))
            elif hrrm == "suspender_equipo":
                resultado_ejecucion = acciones.suspender_equipo()
            elif hrrm == "hacer_click":
                resultado_ejecucion = acciones.hacer_click()
            elif hrrm == "analizar_archivo":
                resultado_ejecucion = acciones.analizar_archivo(params.get("nombre", ""), self.memoria)
            elif hrrm == "escanear_proyecto":
                resultado_ejecucion = acciones.escanear_proyecto(params.get("carpeta", ""), self.memoria)
            elif hrrm == "copiloto_vscode":
                return copiloto_vscode_plugin(self.memoria)  # Tiene su propio manejo de habla
            elif hrrm == "usar_gemini":
                resultado_ejecucion = self.memoria.consultar(params.get("query", comando))
                return resultado_ejecucion  # Devolvemos esto directamente sin hablar "resp_ia" del enrutador local
            else:
                print(f"[Cerebro] Herramienta desconocida: {hrrm}")
                
        except Exception as e:
            print(f"[ERROR] Fallo al ejecutar {hrrm}: {e}")
            resultado_ejecucion = "Ocurrió un error al ejecutar la acción."

        # Paso 3: Retornar la respuesta original de la IA (que ya debería venir formulada como si lo hubiera hecho)
        # O si la herramienta requiere hablar explícitamente el resultado (como la hora o fecha)
        if hrrm in ("dar_hora_fecha", "analizar_archivo", "escanear_proyecto"):
             return resultado_ejecucion # En estos casos el resultado es lo que el bot debe decir directamente
             
        # Para herramientas simples (abrir, volumen), el JSON de la IA ya trae una frase natural en "respuesta"
        return resp_ia
