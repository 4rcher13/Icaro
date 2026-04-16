import sounddevice as sd

print("Probando InputStream con callback (No Bloqueante)...")
def callback(indata, frames, time, status):
    pass

exitos = []
dispositivos = sd.query_devices()
for i, d in enumerate(dispositivos):
    if d["max_input_channels"] > 0:
        rate = int(d["default_samplerate"])
        try:
            with sd.InputStream(samplerate=rate, channels=1, dtype="int16", device=i, callback=callback):
                sd.sleep(100)
            exitos.append((i, d["name"]))
            print(f"[{i}] {d['name']} -> FUNCIONA")
        except Exception as e:
            print(f"[{i}] {d['name']} -> Fallo: {e}")

print(f"\nDispositivos que soportan callback: {len(exitos)}")
