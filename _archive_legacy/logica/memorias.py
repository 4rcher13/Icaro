import os
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


class CerebroIcaro:
    """Motor cognitivo híbrido de Ícaro: Local (Qwen 1.5B) + Nube (Gemini)."""

    _DESECHABLES = frozenset(("abre", "cerrar", "hora", "fecha", "volumen", "que puedes hacer"))

    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.archivo_historial = os.path.join(base_dir, "data", "historial.json")
        self.archivo_perfil = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfil.json")

        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.modelo_local = "qwen2.5:3b"

        # 1. Cargar configuración básica
        print("[Memoria] Cargando perfiles y configuración...")
        self.config_perfil = self._cargar_json(self.archivo_perfil, {})
        self.historial_espejo = self._cargar_json(self.archivo_historial, [])

        # 2. Carga de Skills acelerada
        self._skills_texto = self._cargar_skills_optimizada(
            os.path.join(base_dir, "__skillsIA__")
        )

        # Prompt para el modelo local (Liderazgo ejecutivo + comandos JSON)
        self.instruccion_local = (
            "Eres Ícaro, asistente y amigo inteligente de Jesús (Chucho). "
            "Experto en ingeniería de software. Siempre debes responder usando formato estructurado (JSON). "
            "REGLAS:\n"
            "1. Habla natural, cálido y conversacional. Usa contracciones (claro, listo, ya lo hice, ahí va).\n"
            "2. Prohibido sonar robótico (nada de 'Procesando...', 'Ejecutando...').\n"
            "3. Muy conciso: tareas del sistema en 1 oración (ej. 'Listo'). Preguntas directas sin preámbulos.\n"
            "4. Responde en el campo 'respuesta'. No uses símbolos técnicos. Los números léelos con palabras naturales.\n"
            "5. Si la tarea es simple o de OS, resuélvela tú. Si requiere programación compleja, análisis profundo "
            "o respuestas muy largas, delega usando la herramienta 'usar_gemini'."
            + (f"\nCONTEXTO DEL PROYECTO:\n{self._skills_texto[:500]}" if self._skills_texto else "")
        )

        # --- Inicializar Gemini (Nube) ---
        api_key = "AIzaSyDQ7K29F1F70GxuS7suwuwXjuMV66b2pK4"
        if genai and api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                perfil = self.config_perfil
                self.instruccion_sistema = (
                    f"Eres Ícaro, asistente virtual y amigo de {perfil.get('user_name', 'Jesús')} "
                    f"({perfil.get('user_nickname', 'Chucho')}), {perfil.get('user_role', 'Estudiante de Ingeniería en Software')}. "
                    "Ayúdalo a codificar, depurar y optimizar código.\n\n"
                    "REGLAS:\n"
                    "1. Habla natural, cálido y conversacional. Usa lenguaje cotidiano (claro, listo, ahí va).\n"
                    "2. Nunca suenes robótico (no digas 'Procesando' ni 'Entendido, ejecutaré').\n"
                    "3. Tus respuestas son para voz (TTS): no uses emojis, no leas símbolos técnicos como slash, y pronuncia números con naturalidad.\n"
                    "4. Sé directo y conciso para consultas simples, y expláyate solo si lo pide el contexto o es código complejo."
                )

                # Inyectar Skills completos en Gemini (tiene ventana de contexto grande)
                if self._skills_texto:
                    self.instruccion_sistema += f"\n\nBASE DE CONOCIMIENTO INTERNA:\n{self._skills_texto}"

                # Convertir historial JSON a objetos Content de Gemini
                history = [
                    types.Content(role=m["role"], parts=[types.Part.from_text(text=m["text"])])
                    for m in self.historial_espejo if m.get("role") and m.get("text")
                ] or None

                self.chat = self.client.chats.create(
                    model='gemini-2.5-flash',
                    config=types.GenerateContentConfig(
                        system_instruction=self.instruccion_sistema,
                        temperature=0.75
                    ),
                    history=history
                )
                self.ia_habilitada = True
                print("[OK] Cerebro Cognitivo de Ícaro (Gemini) cargado.")
            except Exception as e:
                print(f"[WARN] Error inicializando Gemini: {e}")

        # --- Inicializar Ollama (Local) ---
        if ollama:
            try:
                print(f"[Ollama] Conectando a {self.modelo_local}...")
                ollama.list()
                self.ollama_habilitado = True
                print(f"[OK] Motor Local listo.")
            except Exception:
                print("[WARN] Ollama no disponible.")

    # ===================== UTILIDADES DE I/O =====================

    @staticmethod
    def _cargar_json(ruta, default):
        """Carga un archivo JSON de forma segura."""
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    @staticmethod
    def _limpiar_markdown(texto):
        """Elimina remanentes de markdown para TTS limpio."""
        return texto.replace("*", "").replace("#", "").replace("`", "").strip()

    @staticmethod
    def _cargar_skills_optimizada(ruta_skills):
        """Lee archivos SKILL.md de forma eficiente."""
        if not os.path.exists(ruta_skills):
            return ""

        print("[Memoria] Indexando base de conocimientos...")
        fragmentos = []
        try:
            # Solo buscar en primer nivel para rapidez, o usar una lista pre-cachada si fuera necesario
            for f in os.listdir(ruta_skills):
                if f.upper().endswith(".MD"):
                    ruta_f = os.path.join(ruta_skills, f)
                    with open(ruta_f, "r", encoding="utf-8", errors="ignore") as archivo:
                        contenido = archivo.read()
                        if contenido.startswith("---"):
                            partes = contenido.split("---", 2)
                            contenido = partes[2] if len(partes) > 2 else contenido
                        fragmentos.append(contenido.strip())
        except Exception as e:
            print(f"[WARN] Error cargando skills: {e}")

        if fragmentos:
            return "\n\n".join(fragmentos)
        return ""

    # ===================== MEMORIA DINÁMICA =====================

    def _es_desechable(self, prompt):
        """Capa 3: identifica interacciones de un solo uso."""
        low = prompt.lower()
        return any(cmd in low for cmd in self._DESECHABLES)

    def _guardar_interaccion(self, prompt, respuesta):
        """Capa 2: guarda con filtrado de basura y compresión de código."""
        if self._es_desechable(prompt):
            return

        # Comprimir prompts largos (código) para no inflar el historial
        guardado = f"[Código: {prompt[:50]}...]" if len(prompt) > 1000 else prompt

        self.historial_espejo.extend([
            {"role": "user", "text": guardado},
            {"role": "model", "text": respuesta}
        ])

        # Poda inteligente
        if len(self.historial_espejo) > 40:
            self.historial_espejo = self.historial_espejo[-40:]

        try:
            with open(self.archivo_historial, "w", encoding="utf-8") as f:
                json.dump(self.historial_espejo, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR al guardar memoria] {e}")

    # ===================== MOTORES DE IA =====================

    def inyectar_contexto_archivo(self, nombre_archivo, contenido):
        """Usa el motor LOCAL para analizar archivos sin gastar tokens."""
        return self.consultar_local(
            f"Analiza el código de '{nombre_archivo}'. Busca errores y sugiere mejoras.\n\nCÓDIGO:\n{contenido}"
        )

    def preparar_mejora_copiloto(self, nombre_archivo, contenido):
        """
        Usa la NUBE para un análisis profundo.
        Devuelve (Resumen_Humanizado, Codigo_Completo_Mejorado).
        """
        if not self.ia_habilitada:
            return "No tengo conexión a la nube para un análisis profundo, señor.", None

        prompt = (
            f"Señor, estoy analizando su archivo '{nombre_archivo}' en VS Code. "
            "1. Primero, explíqueme brevemente qué va a mejorar y POR QUÉ (2-3 oraciones).\n"
            "2. Luego, entregue el código completo y optimizado del archivo.\n"
            "IMPORTANTE: Separe el resumen del código con la marca [CODIGO_MEJORADO].\n\n"
            f"CÓDIGO ACTUAL:\n{contenido}"
        )

        try:
            # Forzamos Gemini para el Copiloto por su capacidad de razonamiento
            respuesta = self.chat.send_message(prompt).text
            if "[CODIGO_MEJORADO]" in respuesta:
                partes = respuesta.split("[CODIGO_MEJORADO]")
                resumen = self._limpiar_markdown(partes[0])
                # Limpiar el código de bloques ```python o similares
                codigo = partes[1].replace("```python", "").replace("```", "").strip()
                return resumen, codigo
            else:
                return self._limpiar_markdown(respuesta), None
        except Exception as e:
            print(f"[ERROR Copiloto] {e}")
            return "Tuve un problema de enlace al procesar la mejora, señor.", None

    def escanear_proyecto(self, ruta_carpeta):
        """
        Recorre una carpeta de proyecto, construye un mapa de archivos
        y le pide a Qwen un resumen humano de lo que hizo el programador.
        """
        if not self.ollama_habilitado:
            return "Mi núcleo local está desactivado, señor."

        extensiones_codigo = (".py", ".js", ".html", ".css", ".c", ".cpp", ".java", ".cs", ".ts", ".jsx")
        carpetas_ignorar = {"__pycache__", ".git", "venv", "node_modules", "data", ".gemini"}

        archivos_encontrados = []
        for root, dirs, files in os.walk(ruta_carpeta):
            dirs[:] = [d for d in dirs if d not in carpetas_ignorar]
            for f in files:
                if any(f.endswith(ext) for ext in extensiones_codigo):
                    ruta_completa = os.path.join(root, f)
                    ruta_relativa = os.path.relpath(ruta_completa, ruta_carpeta)
                    try:
                        with open(ruta_completa, "r", encoding="utf-8", errors="ignore") as archivo:
                            lineas = archivo.readlines()
                        # Solo leer las primeras 30 líneas de cada archivo para no saturar
                        preview = "".join(lineas[:30])
                        archivos_encontrados.append({
                            "nombre": ruta_relativa,
                            "lineas_totales": len(lineas),
                            "preview": preview
                        })
                    except Exception:
                        continue

        if not archivos_encontrados:
            return f"No encontré archivos de código en esa carpeta, señor."

        # Construir el resumen para Qwen
        resumen = f"El proyecto tiene {len(archivos_encontrados)} archivos de código:\n\n"
        for arch in archivos_encontrados:
            resumen += f"--- {arch['nombre']} ({arch['lineas_totales']} líneas) ---\n{arch['preview']}\n\n"

        prompt = (
            f"Jesús te pide que revises su proyecto ubicado en '{os.path.basename(ruta_carpeta)}'. "
            "Explícale de forma breve y humana (como un compañero de clase que lo ayuda): "
            "qué hace cada archivo, qué errores potenciales ves y qué podría mejorar. "
            "Habla directo y sé útil, sin rodeos.\n\n"
            f"{resumen}"
        )

        return self.consultar_local(prompt)

    def consultar_local(self, prompt):
        """Conversación directa con el modelo local Qwen (default)."""
        if not self.ollama_habilitado:
            return "Mi núcleo local está desactivado, señor."

        try:
            print(f"[INFO] Consultando Motor Local ({self.modelo_local})...")
            messages = [{"role": "system", "content": self.instruccion_local}]

            # Solo últimos 4 mensajes para no saturar el 1.5B
            for msg in self.historial_espejo[-4:]:
                messages.append({
                    "role": "user" if msg["role"] == "user" else "assistant",
                    "content": msg["text"]
                })
            messages.append({"role": "user", "content": prompt})

            response = ollama.chat(
                model=self.modelo_local, 
                messages=messages, 
                stream=False,
                options={'temperature': 0.4, 'num_predict': 400}
            )
            respuesta = self._limpiar_markdown(response['message']['content'])
            self._guardar_interaccion(prompt, respuesta)
            return respuesta
        except Exception as e:
            return f"Error en motor local: {e}"

    def consultar(self, prompt):
        """Interacción con Gemini (Nube) con auto-fallback a Local."""
        if not self.ia_habilitada:
            return self.consultar_local(prompt)  # Fallback directo

        for i in range(3):
            try:
                resp = self.chat.send_message(prompt)
                texto = self._limpiar_markdown(resp.text) if resp and resp.text else "Fallo temporal en mi núcleo."
                self._guardar_interaccion(prompt, texto)
                return texto
            except Exception as e:
                msg = str(e)
                print(f"[WARN Gemini intento {i+1}/3] {msg}")
                if "429" in msg or "quota" in msg.lower() or i == 2:
                    print("[AUTO-FALLBACK] Cambiando a Motor Local...")
                    return self.consultar_local(prompt)
                time.sleep(2)

        return "Fallo crítico en ambos motores, señor."

    def enrutar_comando(self, comando, descripcion_herramientas):
        """
        Envía el comando al modelo local como Router Primario.
        Retorna (nombre_herramienta_str_o_none, params_dict, respuesta_hablar_str)
        """
        # PRIORIDAD 1: Local (Decisiones rápidas)
        if self.ollama_habilitado:
            try:
                return self._enrutar_comando_local(comando, descripcion_herramientas)
            except Exception as e:
                print(f"[WARN] Motor Local falló en ruteo ({e}). Fallback a Nube...")
                
        # PRIORIDAD 2: Nube (Solo si Local falla o no está habilitado)
        if self.ia_habilitada:
            try:
                print("[INFO] Enrutando con Motor Nube (Fallback)...")
                return self._enrutar_comando_gemini(comando, descripcion_herramientas)
            except Exception as e:
                print(f"[ERROR Nube Fallback] {e}")

        return None, {}, "Lo siento, mis procesadores están bloqueados."

    def _enrutar_comando_local(self, comando, descripcion_herramientas):
        """Enrutador puro de Ollama Local"""
        prompt_enrutamiento = f"""
Comando del usuario: "{comando}"

HERRAMIENTAS DISPONIBLES (si no necesitas, usa null o usar_gemini):
{descripcion_herramientas}

EJEMPLOS DE RUTEO CORRECTO:
- Comando: "Abre VS Code" -> {{"herramienta": "abrir_aplicacion", "params": {{"nombre_app": "code"}}, "respuesta": "Listo, abriendo."}}
- Comando: "Sube el volumen" -> {{"herramienta": "control_volumen", "params": {{"accion": "subir"}}, "respuesta": "Claro, ya lo subí."}}
- Comando: "Hola Icaro" -> {{"herramienta": null, "params": {{}}, "respuesta": "Hola Chucho, ¿qué hacemos hoy?"}}
- Comando: "Explica esta gran porción de código" u otra pregunta de programación -> {{"herramienta": "usar_gemini", "params": {{"query": "Explica esta gran porción de código"}}, "respuesta": "Dame un segundo, lo estoy procesando con detalle."}}

OBLIGATORIO - Tu respuesta DEBE ser solo un JSON con esta estructura exacta:
{{"herramienta": "nombre_herramienta_o_null", "params": {{"param1": "valor"}}, "respuesta": "tu respuesta hablada natural y corta"}}
"""
        print(f"[INFO] Enrutando con Motor Local ({self.modelo_local})...")
        messages = [{"role": "system", "content": self.instruccion_local}]

        for msg in self.historial_espejo[-2:]:
            messages.append({
                "role": "user" if msg["role"] == "user" else "assistant",
                "content": msg["text"]
            })
        messages.append({"role": "user", "content": prompt_enrutamiento})

        response = ollama.chat(
            model=self.modelo_local, 
            messages=messages, 
            format='json', 
            stream=False,
            options={'temperature': 0.1, 'num_predict': 150} # Rapidez y precisión
        )
        respuesta_texto = response['message']['content']
        
        try:
            datos = json.loads(respuesta_texto)
        except json.JSONDecodeError:
            # Tolerancia a errores de JSON si el modelo alucina
            return None, {}, "Lo siento señor, mi motor local tuvo un pequeño fallo de compresión."

        hrrm = datos.get("herramienta", None)
        params = datos.get("params", {})
        resp = datos.get("respuesta", "")
        
        if hrrm in ("null", "None", ""):
            hrrm = None
            
        self._guardar_interaccion(comando, resp)
        return hrrm, params, self._limpiar_markdown(resp)

    def _enrutar_comando_gemini(self, comando, descripcion_herramientas):
        """Enrutador puro de Gemini Cloud"""
        prompt_enrutamiento = f"""
Comando del usuario: "{comando}"

HERRAMIENTAS DISPONIBLES:
{descripcion_herramientas}

OBLIGATORIO: Eres el cerebro de ruteo. Responde SOLO y EXCLUSIVAMENTE con un JSON puro, sin tags como ```json, usando esta estructura:
{{"herramienta": "nombre_herramienta_o_null", "params": {{}}, "respuesta": "tu respuesta hablada concisa"}}
"""
        resp = self.chat.send_message(prompt_enrutamiento)
        texto = resp.text.replace("```json", "").replace("```", "").strip()     
        datos = json.loads(texto)
        
        hrrm = datos.get("herramienta", None)
        params = datos.get("params", {})
        respuesta_ia = datos.get("respuesta", "Entendido.")
        
        if hrrm in ("null", "None", "", "nombre_herramienta_o_null"):
            hrrm = None

        self._guardar_interaccion(comando, respuesta_ia)
        return hrrm, params, self._limpiar_markdown(respuesta_ia)
