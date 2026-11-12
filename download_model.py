"""
Script para descargar modelos GGUF optimizados para RTX 4050 (6GB VRAM)
"""

import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

PRESETS = {
    "1": {
        "name": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "2.02 GB",
        "speed": "Ultra rápida (~80-100 t/s)",
        "vram": "Cabe 100% en la RTX 4050",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    },
    "2": {
        "name": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "size": "4.68 GB",
        "speed": "Muy rápida (~45-55 t/s)",
        "vram": "Especialista en Programación / Código (entra en 6GB)",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    },
    "3": {
        "name": "DeepSeek-R1-Distill-Qwen-8B-Q4_K_M.gguf",
        "size": "4.92 GB",
        "speed": "Rápida (~40-50 t/s)",
        "vram": "Razonamiento Profundo R1 (entra con 28 capas en GPU)",
        "url": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-8B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-8B-Q4_K_M.gguf"
    },
    "4": {
        "name": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size": "2.39 GB",
        "speed": "Ultra rápida (~75 t/s)",
        "vram": "Muy ligero y potente de Microsoft",
        "url": "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
    }
}

def download_file(url, dest_path):
    print(f"\nDescargando en: {dest_path}")
    
    def reporthook(count, block_size, total_size):
        downloaded = count * block_size
        percent = int(downloaded * 100 / total_size) if total_size > 0 else 0
        mb_down = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        bar = "=" * (percent // 2) + "-" * (50 - (percent // 2))
        sys.stdout.write(f"\r[{bar}] {percent}% ({mb_down:.1f} / {mb_total:.1f} MB)")
        sys.stdout.flush()

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')]
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(url, dest_path, reporthook)
    print("\n[+] Descarga completada exitosamente!")

def main():
    print("=" * 65)
    print("  DESCARGADOR DE MODELOS GGUF OPTIMIZADOS PARA RTX 4050")
    print("=" * 65)
    print("Selecciona el modelo que deseas descargar para la carpeta models/:")
    for key, p in PRESETS.items():
        print(f" [{key}] {p['name']}")
        print(f"     Tamano: {p['size']} | Velocidad: {p['speed']}")
        print(f"     VRAM: {p['vram']}")
        print("-" * 65)
    print(" [0] Salir")

    choice = input("\nElige una opcion (1-4): ").strip()
    if choice in PRESETS:
        p = PRESETS[choice]
        dest = MODELS_DIR / p["name"]
        if dest.exists():
            print(f"\n[!] El archivo {p['name']} ya existe en la carpeta models/.")
            return
        download_file(p["url"], dest)
    else:
        print("Operacion cancelada.")

if __name__ == "__main__":
    main()

