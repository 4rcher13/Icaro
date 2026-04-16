import time
import json
import ollama

def evaluar_modelo(modelo, comandos, descripcion_herramientas):
    print(f"\n=============================================")
    print(f" EVALUANDO MODELO: {modelo}")
    print(f"=============================================\n")
    
    instruccion_local = (
        "Eres Ícaro, asistente y amigo inteligente de Jesús (Chucho). "
        "Experto en ingeniería de software. Siempre debes responder usando formato estructurado (JSON). "
        "REGLAS:\n"
        "1. Habla natural, cálido y conversacional. Usa contracciones.\n"
        "2. Muy conciso: tareas del sistema en 1 oración. Preguntas directas sin preámbulos.\n"
        "3. Responde en el campo 'respuesta'.\n"
        "4. Si requiere programación compleja, delega usando la herramienta 'usar_gemini'."
    )
    
    tiempos = []
    exitos = 0
    
    for cmd, usar_gemini_esperado in comandos:
        print(f"-> Comando: '{cmd}'")
        
        prompt_enrutamiento = f"""
Comando del usuario: "{cmd}"

HERRAMIENTAS DISPONIBLES:
{descripcion_herramientas}

OBLIGATORIO - Tu respuesta DEBE ser solo y exclusivamente un JSON con esta estructura exacta:
{{"herramienta": "nombre_herramienta_o_null", "params": {{"param1": "valor"}}, "respuesta": "tu respuesta hablada natural y corta"}}
"""
        messages = [
            {"role": "system", "content": instruccion_local},
            {"role": "user", "content": prompt_enrutamiento}
        ]
        
        try:
            start_time = time.time()
            response = ollama.chat(
                model=modelo, 
                messages=messages, 
                format='json', 
                stream=False,
                options={'temperature': 0.1, 'num_predict': 150}
            )
            elapsed = time.time() - start_time
            tiempos.append(elapsed)
            
            respuesta_texto = response['message']['content']
            datos = json.loads(respuesta_texto)
            
            hrrm = datos.get("herramienta")
            resp = datos.get("respuesta", "")
            
            # Validación
            usa_gemini_real = hrrm == "usar_gemini"
            correcto = (usa_gemini_real == usar_gemini_esperado)
            if correcto: exitos += 1
            
            print(f"   [Latencia]: {elapsed:.2f}s")
            print(f"   [Tool]: {hrrm} | [Resp]: {resp}")
            print(f"   [Test Delegación]: {'OK' if correcto else 'FALLÓ (Esperaba usar_gemini='+str(usar_gemini_esperado)+')'}\n")
            
        except Exception as e:
            print(f"   [ERROR]: {e}\n")
            
    avg_time = sum(tiempos) / len(tiempos) if tiempos else 0
    print(f"--> RESULTADOS {modelo}:")
    print(f"    Latencia Promedio: {avg_time:.2f}s")
    print(f"    Precisión Delegación: {exitos}/{len(comandos)} ({(exitos/len(comandos))*100:.1f}%)")

if __name__ == "__main__":
    desc = "- abrir_aplicacion(nombre_app=\"nombre\")\n- control_volumen(accion=\"subir\" o \"bajar\")\n- usar_gemini(query=\"texto\")"
    
    comandos_prueba = [
        ("Abre el reproductor de música", False),
        ("Súbele al volumen", False),
        ("¿Qué hora es?", False),
        ("Escribe un script en Python para conectarme a una base de datos MySQL usando SQLAlchemy con pooling avanzado.", True),
        ("Explícame en detalle cómo funciona el motor V8 de JavaScript", True),
        ("Hola, ¿cómo estás?", False)
    ]
    
    evaluar_modelo("qwen2.5:3b", comandos_prueba, desc)
    evaluar_modelo("phi3.5:latest", comandos_prueba, desc)
