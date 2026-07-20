import os
import logging
from pathlib import Path
import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

class SileroVAD:
    """
    Servicio de Voice Activity Detection (VAD) usando el modelo Silero VAD v5 ONNX local.
    Soporta procesamiento por sub-chunks de 512 muestras (32ms) para admitir cualquier
    tamaño de ventana solicitado por el llamador (ej. 64ms, 96ms o 100ms).
    """
    
    def __init__(self, model_path: str = None):
        if model_path is None:
            # Buscar el modelo en src/models/
            base_dir = Path(__file__).resolve().parent.parent
            model_path = str(base_dir / "models" / "silero_vad.onnx")
            
        logger.info(f"Cargando Silero VAD desde: {model_path}")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"No se encontró el modelo Silero VAD en {model_path}. Asegúrate de ubicarlo en el proyecto.")
            
        # Configurar ONNX Runtime en modo CPU optimizado
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
        
        # Estado LSTM de Silero VAD v5: [2, batch_size, 128]
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.sample_rate = np.array(16000, dtype=np.int64)
        
    def reset(self):
        """Reinicia el estado del LSTM."""
        self.state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_speech(self, audio_data: np.ndarray, threshold: float = 0.5) -> float:
        """
        Procesa un frame de audio int16 o float32 de cualquier tamaño.
        Retorna la probabilidad de habla (0.0 a 1.0) del último sub-frame.
        """
        # Asegurar float32 y escala [-1.0, 1.0]
        if audio_data.dtype == np.int16:
            audio_float = audio_data.astype(np.float32) / 32768.0
        else:
            audio_float = audio_data.astype(np.float32)
            
        chunk_size = 512
        num_samples = len(audio_float)
        
        # Si el audio es más corto de 512 muestras, rellenamos con ceros
        if num_samples < chunk_size:
            padded = np.zeros(chunk_size, dtype=np.float32)
            padded[:num_samples] = audio_float
            audio_float = padded
            num_samples = chunk_size
            
        prob = 0.0
        # Procesar en bloques de 512 muestras
        for i in range(0, num_samples, chunk_size):
            chunk = audio_float[i:i+chunk_size]
            if len(chunk) < chunk_size:
                # Relleno final si es necesario
                padded = np.zeros(chunk_size, dtype=np.float32)
                padded[:len(chunk)] = chunk
                chunk = padded
                
            input_data = np.expand_dims(chunk, axis=0) # [1, 512]
            
            try:
                # Ejecutar inferencia
                outputs = self.session.run(
                    None, 
                    {
                        'input': input_data,
                        'state': self.state,
                        'sr': self.sample_rate
                    }
                )
                prob = float(outputs[0][0][0])
                self.state = outputs[1] # Actualizar estado LSTM
            except Exception as e:
                logger.error(f"Error durante inferencia Silero VAD: {e}")
                
        return prob
