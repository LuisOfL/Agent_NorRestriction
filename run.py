"""
Lanzador principal de HackingLLM Studio
Inicia el backend FastAPI y abre la interfaz gráfica en el navegador.
"""

import os
import sys
import time
import webbrowser
import threading
import uvicorn

def open_browser():
    time.sleep(1.2)
    url = "http://127.0.0.1:7860"
    print(f"\n[+] Abriendo entorno grafico en: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    print("\n" + "="*65)
    print("      HACKINGLLM - ENTORNO GRAFICO GGUF DE ALTO RENDIMIENTO")
    print("      Optimizado para NVIDIA RTX 4050 (6GB) & AMD Ryzen")
    print("="*65 + "\n")
    print("[*] Iniciando servidor de inferencia y telemetria...")
    
    # Lanzar apertura de navegador en hilo secundario
    threading.Thread(target=open_browser, daemon=True).start()
    
    uvicorn.run("server:app", host="127.0.0.1", port=7860, reload=False, log_level="warning")

