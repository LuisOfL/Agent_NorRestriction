@echo off
title HackingLLM - GGUF Studio RTX 4050
cd /d "%~dp0"

echo ======================================================================
echo           HACKINGLLM - ENTORNO GRAFICO GGUF DE ALTO RENDIMIENTO
echo           Optimizado para NVIDIA RTX 4050 (6GB) y AMD Ryzen
echo ======================================================================
echo.
echo [*] Verificando dependencias...

python -c "import fastapi, uvicorn, psutil" >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Instalando modulos necesarios...
    python -m pip install fastapi uvicorn psutil
)

echo [*] Iniciando interfaz grafica...
echo [*] Se abrira automaticamente en tu navegador web.
echo.
python run.py

pause

