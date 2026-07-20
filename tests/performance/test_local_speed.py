import ollama
import time

def test_local_speed():
    model = "qwen2.5-coder:1.5b"
    prompt = "Hola Ícaro, esto es una prueba de velocidad. Responde en una sola oración sobre qué es un puntero en C."
    
    print(f"--- Iniciando Test de Velocidad Local ({model}) ---")
    start_time = time.time()
    
    try:
        response = ollama.chat(model=model, messages=[
            {'role': 'user', 'content': prompt},
        ])
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"\nRespuesta: {response['message']['content']}")
        print(f"\n--- TIEMPO TOTAL: {elapsed:.2f} segundos ---")
        
        if elapsed < 2:
            print("[RESULTADO] Increíblemente rápido. Ideal para integración en tiempo real.")
        elif elapsed < 5:
            print("[RESULTADO] Velocidad aceptable para un asistente de voz.")
        else:
            print("[RESULTADO] Un poco lento, pero funcional.")
            
    except Exception as e:
        print(f"Error al conectar con Ollama: {e}")

if __name__ == "__main__":
    test_local_speed()
