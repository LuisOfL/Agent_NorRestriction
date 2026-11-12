# HackingLLM Studio - Entorno Gráfico GGUF de Alto Rendimiento

Entorno gráfico local hiper-optimizado para ejecutar modelos en formato `.gguf` aprovechando al máximo la tarjeta gráfica **NVIDIA GeForce RTX 4050 Laptop GPU (6 GB VRAM GDDR6)** y el procesador **AMD Ryzen (6 núcleos / 12 hilos)**.

---

## ⚡ Solución a los Problemas Previos

### 1. ¿Por qué tardaba tanto la computadora al responder?
* **Causa principal**: Cuando un modelo GGUF no tiene soporte CUDA activo o cuando se descargan más capas de las que caben en la VRAM de la GPU (6 GB), Windows activa la memoria compartida (*GPU Shared Memory Fallback*). Al transferir datos constantemente entre la RAM del sistema y la GPU por el bus PCIe, la velocidad colapsa de ~60 tokens/segundo a menos de 1 token/segundo.
* **Solución aplicada**:
  - **Motor C++ Nativo (CUDA 12.4)**: Compilado para arquitecturas modernas con soporte AVX2 y núcleos Tensor.
  - **Flash Attention**: Reduce hasta un 40% el consumo de VRAM en la atención contextual.
  - **Control Inteligente de Capas (`n_gpu_layers`)**: El entorno te permite asignar exactamente las capas que caben en tus 6 GB de VRAM (por ejemplo, 33 capas para modelos 7B/8B o 100% para modelos 3B) evitando el desbordamiento.
  - **Cuantización de KV Cache (`q8_0`)**: Reduce a la mitad el consumo de memoria del historial del chat.
  - **Hilos Físicos de CPU**: Optimizado para 6 hilos reales de tu AMD Ryzen, eliminando la penalización de latencia del SMT/HyperThreading.

### 2. ¿Por qué el modelo se cortaba a la mitad y no terminaba de escribir?
* **Causa principal**: La gran mayoría de interfaces genéricas tienen fijado un `max_tokens` (o `n_predict`) muy bajo por defecto (ej. 256 o 512 tokens), cortando abruptamente respuestas largas, explicaciones de código o tablas.
* **Solución aplicada**:
  - **Límite Extendido de Salida**: Selector de 4,096 a 8,192 tokens de salida continuos.
  - **Ventana de Contexto Amplia**: Soporte de 8,192 a 16,384 tokens con preservación de contexto.
  - **Botón Inteligente "Continuar escribiendo"**: Si una respuesta extremadamente larga alcanza el límite, aparece automáticamente un banner y botón para que el modelo siga redactando desde la última palabra sin reiniciar la conversación.

---

## 🚀 Cómo Iniciar el Entorno

### Opción 1 (Recomendada - 1 Clic):
Haz doble clic sobre el archivo:
```
INICIAR_HACKINGLLM.bat
```
El servidor arrancará e inmediatamente se abrirá tu navegador web con la interfaz gráfica en:
`http://127.0.0.1:7860`

### Opción 2 (Por consola):
```powershell
python run.py
```

---

## 📁 Dónde Colocar tus Archivos GGUF

1. Puedes arrastrar o copiar tus archivos `.gguf` dentro de la carpeta:
   `c:\Users\luigu\OneDrive\Escritorio\HackingLLM\models\`
2. O en la interfaz gráfica, pulsa el botón **"Explorar en PC..."** para seleccionar cualquier archivo `.gguf` que tengas en tu disco duro (Descargas, Documentos, etc.).

---

## 🎯 Modelos GGUF Recomendados para tu RTX 4050 (6GB)

| Modelo | Cuantización | Tamaño | VRAM Usada | Velocidad Estimada | Especialidad |
|---|---|---|---|---|---|
| **Llama-3.2-3B-Instruct** | Q4_K_M | ~2.0 GB | ~2.6 GB (100% GPU) | **75 - 95 tokens/s** | Respuestas ultrarrápidas, tareas generales |
| **Phi-3.5-mini-instruct** | Q4_K_M | ~2.4 GB | ~3.0 GB (100% GPU) | **70 - 85 tokens/s** | Lógica, matemáticas, resúmenes |
| **Qwen2.5-Coder-7B-Instruct** | Q4_K_M | ~4.7 GB | ~5.2 GB (28-30 capas) | **40 - 55 tokens/s** | Programación, scripts, depuración |
| **DeepSeek-R1-Distill-Qwen-8B** | Q4_K_M | ~4.9 GB | ~5.3 GB (28 capas) | **35 - 50 tokens/s** | Razonamiento paso a paso, análisis complejo |

> 💡 **Para descargar cualquiera de estos modelos automáticamente**: Ejecuta `python download_model.py` y elige la opción que prefieras.

