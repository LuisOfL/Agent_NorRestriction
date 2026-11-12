"""
HackingLLM Server - Backend de alto rendimiento para inferencia GGUF con aceleración GPU (RTX 4050 / CUDA)
Optimizaciones integradas:
- Flash Attention
- Descarga controlada de capas a GPU (evita saturación de VRAM)
- Detección de corte de texto y botón 'Continuar'
- Control de hilos CPU óptimos (6 hilos físicos)
- Telemetría en tiempo real (VRAM, RAM, Tokens/seg)
"""

import os
import sys
import json
import time
import signal
import subprocess
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
ENGINE_DIR = BASE_DIR / "engine"
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="HackingLLM Engine - GGUF High Performance Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estado global del workspace con persistencia en disco (nunca usa la carpeta interna del IDE como proyecto)
WORKSPACE_CONFIG_FILE = BASE_DIR / ".antigravity_workspace"

def _get_default_projects_dir() -> Path:
    desktop = Path.home() / "OneDrive" / "Escritorio"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    example_dir = desktop / "Example"
    if example_dir.exists() and example_dir.is_dir():
        return example_dir.resolve()
    fallback = desktop / "Proyectos_IA" if desktop.exists() else (BASE_DIR.parent / "Proyectos_IA")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback.resolve()

def _load_saved_workspace() -> Path:
    try:
        if WORKSPACE_CONFIG_FILE.exists():
            saved = Path(WORKSPACE_CONFIG_FILE.read_text(encoding="utf-8").strip())
            if saved.exists() and saved.is_dir() and saved.resolve() != BASE_DIR.resolve():
                return saved.resolve()
    except Exception:
        pass
    default_dir = _get_default_projects_dir()
    try:
        WORKSPACE_CONFIG_FILE.write_text(str(default_dir), encoding="utf-8")
    except Exception:
        pass
    return default_dir

def _save_workspace_path(folder: Path) -> None:
    try:
        resolved = folder.resolve()
        if resolved != BASE_DIR.resolve():
            WORKSPACE_CONFIG_FILE.write_text(str(resolved), encoding="utf-8")
    except Exception:
        pass

def _sync_workspace(workspace_path: Optional[str] = None) -> Path:
    """Sincroniza y garantiza que el workspace activo nunca sea la carpeta interna de HackingLLM."""
    if workspace_path:
        try:
            cand = Path(workspace_path).resolve()
            if cand != BASE_DIR.resolve():
                cand.mkdir(parents=True, exist_ok=True)
                workspace.current_dir = cand
                _save_workspace_path(cand)
                return workspace.current_dir
        except Exception:
            pass
    if workspace.current_dir.resolve() == BASE_DIR.resolve():
        workspace.current_dir = _load_saved_workspace()
    return workspace.current_dir

class WorkspaceState:
    current_dir: Path = _load_saved_workspace()
    lock: threading.Lock = threading.Lock()

workspace = WorkspaceState()

def get_dir_tree(folder: Path, current_depth: int = 0, max_depth: int = 4) -> List[Dict[str, Any]]:
    """Genera árbol jerárquico de archivos ignorando carpetas ocultas y binarios pesados."""
    if current_depth > max_depth or not folder.exists() or not folder.is_dir():
        return []
        
    ignored_names = {
        ".git", ".venv", "venv", "node_modules", "__pycache__",
        "engine", "models", ".system_generated", ".vscode", ".idea"
    }
    
    items = []
    try:
        entries = sorted(folder.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name in ignored_names or entry.name.startswith("."):
                continue
            rel_path = str(entry.relative_to(workspace.current_dir)).replace("\\", "/")
            if entry.is_dir():
                items.append({
                    "name": entry.name,
                    "type": "directory",
                    "path": rel_path,
                    "children": get_dir_tree(entry, current_depth + 1, max_depth)
                })
            else:
                items.append({
                    "name": entry.name,
                    "type": "file",
                    "path": rel_path,
                    "size": entry.stat().st_size
                })
    except Exception:
        pass
    return items

@app.get("/api/workspace/current")
def get_current_workspace():
    """Obtiene la carpeta actual de trabajo."""
    active_ws = _sync_workspace()
    return {
        "current_dir": str(active_ws.resolve()),
        "name": active_ws.name or str(active_ws)
    }

@app.get("/api/workspace/browse-folders")
def browse_folders(path: Optional[str] = None):
    """Permite navegar por las carpetas del sistema para el modal de abrir carpeta."""
    if not path or path == "":
        target = workspace.current_dir
    else:
        target = Path(path).resolve()
        
    if not target.exists() or not target.is_dir():
        target = Path.home()
        
    parent_path = str(target.parent.resolve()) if target.parent != target else None
    
    subfolders = []
    try:
        for item in sorted(target.iterdir(), key=lambda x: x.name.lower()):
            if item.is_dir() and not item.name.startswith("."):
                subfolders.append({
                    "name": item.name,
                    "path": str(item.resolve())
                })
    except Exception:
        pass
        
    desktop = Path.home() / "OneDrive" / "Escritorio"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    downloads = Path.home() / "Downloads"
    documents = Path.home() / "Documents"
    
    shortcuts = [
        {"name": "Escritorio", "path": str(desktop.resolve()) if desktop.exists() else str(Path.home())},
        {"name": "Descargas", "path": str(downloads.resolve()) if downloads.exists() else str(Path.home())},
        {"name": "Documentos", "path": str(documents.resolve()) if documents.exists() else str(Path.home())},
        {"name": "Usuario (" + Path.home().name + ")", "path": str(Path.home().resolve())},
    ]

    return {
        "current_path": str(target.resolve()),
        "parent_path": parent_path,
        "subfolders": subfolders,
        "shortcuts": shortcuts
    }

@app.post("/api/workspace/select-folder")
def select_workspace_folder():
    """Abre el explorador nativo de carpetas de Windows al frente de la pantalla."""
    try:
        ps_cmd = (
            '[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null; '
            '$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; '
            '$dlg.Description = "Seleccionar Carpeta de Proyecto para HackingLLM Studio"; '
            '$dlg.ShowNewFolderButton = $true; '
            '$form = New-Object System.Windows.Forms.Form; '
            '$form.TopMost = $true; '
            '$form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; '
            '$form.Show(); '
            '$res = $dlg.ShowDialog($form); '
            'if ($res -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dlg.SelectedPath }; '
            '$form.Close()'
        )
        res = subprocess.run(["powershell", "-Sta", "-NoProfile", "-Command", ps_cmd], stdout=subprocess.PIPE, text=True, timeout=60)
        selected = res.stdout.strip()
        if selected and os.path.exists(selected) and os.path.isdir(selected):
            sel_path = Path(selected).resolve()
            if sel_path == BASE_DIR.resolve():
                return {"success": False, "message": "Selecciona o crea una carpeta de proyecto distinta a HackingLLM.", "path": str(workspace.current_dir.resolve())}
            workspace.current_dir = sel_path
            _save_workspace_path(workspace.current_dir)
            return {"success": True, "path": str(workspace.current_dir.resolve()), "name": workspace.current_dir.name}
    except Exception as e:
        pass
    return {"success": False, "path": str(workspace.current_dir.resolve())}

@app.post("/api/workspace/set-folder")
def set_workspace_folder(req: Dict[str, Any]):
    folder_path = (req.get("path") or "").strip()
    if not folder_path:
        raise HTTPException(status_code=400, detail="Ruta de carpeta no válida")
    target = Path(folder_path).resolve()
    if target == BASE_DIR.resolve():
        raise HTTPException(status_code=400, detail="Por seguridad no puedes usar la carpeta interna del motor HackingLLM como proyecto. Crea o selecciona otra carpeta.")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo crear o acceder a la carpeta: {e}")
    workspace.current_dir = target
    _save_workspace_path(workspace.current_dir)
    return {"success": True, "path": str(workspace.current_dir.resolve()), "name": workspace.current_dir.name}

@app.get("/api/workspace/tree")
def get_workspace_tree():
    """Devuelve el árbol de archivos de la carpeta abierta."""
    active_ws = _sync_workspace()
    tree = get_dir_tree(active_ws)
    return {
        "root": str(active_ws.resolve()),
        "name": active_ws.name,
        "tree": tree
    }

@app.get("/api/workspace/file/read")
def read_workspace_file(path: str):
    """Lee el contenido de un archivo relativo al workspace."""
    target = (workspace.current_dir / path).resolve()
    if not str(target).startswith(str(workspace.current_dir.resolve())):
        raise HTTPException(status_code=403, detail="Acceso denegado fuera de la carpeta del proyecto")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo leer el archivo: {e}")

@app.post("/api/workspace/run")
def run_project():
    """Ejecuta el archivo principal del proyecto en una consola de Windows o en el navegador."""
    try:
        main_py = workspace.current_dir / "main.py"
        app_py = workspace.current_dir / "app.py"
        index_html = workspace.current_dir / "index.html"
        
        if main_py.exists():
            cmd = f'start cmd /k "cd /d "{str(workspace.current_dir.resolve())}" && python main.py"'
            os.system(cmd)
            return {"success": True, "message": "Ejecutando main.py en una nueva consola"}
        elif app_py.exists():
            cmd = f'start cmd /k "cd /d "{str(workspace.current_dir.resolve())}" && python app.py"'
            os.system(cmd)
            return {"success": True, "message": "Ejecutando app.py en una nueva consola"}
        elif index_html.exists():
            import webbrowser
            webbrowser.open(f"file:///{str(index_html.resolve()).replace(os.sep, '/')}")
            return {"success": True, "message": "Abriendo index.html en navegador"}
        else:
            return {"success": False, "message": "No se encontró main.py, app.py ni index.html en la carpeta del proyecto"}
    except Exception as e:
        return {"success": False, "message": str(e)}

class WriteFileRequest(BaseModel):
    path: str
    content: str
    force: Optional[bool] = False
    workspace_path: Optional[str] = None

def apply_search_replace_patches(original_content: str, patch_text: str) -> tuple[str, int]:
    """
    Aplica bloques de edición inteligente SEARCH / REPLACE (estilo Aider / Cursor / Antigravity).
    Permite modificar solo las partes necesarias de un archivo existente sin reescribir todo desde 0.
    """
    import re
    # Reconoce bloques con <<<<<<< SEARCH ... ======= ... >>>>>>> (tolerante a bloques SEARCH vacíos, longitud y mayúsculas)
    pattern = re.compile(
        r'<{3,10}\s*SEARCH[^\r\n]*\r?\n([\s\S]*?)\r?\n?={3,10}[^\r\n]*\r?\n([\s\S]*?)\r?\n?>{3,10}[^\r\n]*',
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(pattern.finditer(patch_text))
    if not matches:
        return patch_text, 0

    current_content = original_content
    applied_count = 0

    for m in matches:
        search_block = m.group(1)
        replace_block = m.group(2)

        # 0. Si SEARCH está vacío, insertar/reemplazar cuando el archivo está vacío o agregar al final
        if not search_block.strip():
            if not current_content.strip():
                current_content = replace_block
            else:
                sep = "\n\n" if not current_content.endswith("\n") else "\n"
                current_content = current_content + sep + replace_block
            applied_count += 1
            continue

        # 1. Búsqueda exacta
        if search_block in current_content:
            current_content = current_content.replace(search_block, replace_block, 1)
            applied_count += 1
            continue

        # 2. Búsqueda normalizada por saltos de línea (\r\n vs \n)
        norm_search = search_block.replace("\r\n", "\n")
        norm_current = current_content.replace("\r\n", "\n")
        norm_replace = replace_block.replace("\r\n", "\n")

        if norm_search in norm_current:
            norm_res = norm_current.replace(norm_search, norm_replace, 1)
            if "\r\n" in original_content:
                current_content = norm_res.replace("\n", "\r\n")
            else:
                current_content = norm_res
            applied_count += 1
            continue

        # 3. Búsqueda flexible (ignorando espacios en blanco finales de cada línea)
        search_lines = [line.rstrip() for line in norm_search.split("\n")]
        curr_lines = [line.rstrip() for line in norm_current.split("\n")]
        s_len = len(search_lines)

        found_idx = -1
        for i in range(len(curr_lines) - s_len + 1):
            if curr_lines[i:i+s_len] == search_lines:
                found_idx = i
                break

        if found_idx != -1:
            raw_curr_lines = norm_current.split("\n")
            raw_replace_lines = norm_replace.split("\n")
            new_lines = raw_curr_lines[:found_idx] + raw_replace_lines + raw_curr_lines[found_idx + s_len:]
            res = "\n".join(new_lines)
            if "\r\n" in original_content:
                current_content = res.replace("\n", "\r\n")
            else:
                current_content = res
            applied_count += 1
            continue

        # 4. Búsqueda flexible ignorando indentación inicial (leading/trailing whitespace)
        search_stripped = [line.strip() for line in norm_search.split("\n") if line.strip()]
        if search_stripped:
            curr_raw_lines = norm_current.split("\n")
            match_start = -1
            match_end = -1
            for i in range(len(curr_raw_lines)):
                if curr_raw_lines[i].strip() == search_stripped[0]:
                    k = 0
                    j = i
                    while j < len(curr_raw_lines) and k < len(search_stripped):
                        if curr_raw_lines[j].strip():
                            if curr_raw_lines[j].strip() == search_stripped[k]:
                                k += 1
                            else:
                                break
                        j += 1
                    if k == len(search_stripped):
                        match_start = i
                        match_end = j
                        break
            if match_start != -1 and match_end != -1:
                raw_replace_lines = norm_replace.split("\n")
                new_lines = curr_raw_lines[:match_start] + raw_replace_lines + curr_raw_lines[match_end:]
                res = "\n".join(new_lines)
                if "\r\n" in original_content:
                    current_content = res.replace("\n", "\r\n")
                else:
                    current_content = res
                applied_count += 1
                continue

    return current_content, applied_count

@app.post("/api/workspace/file/write")
def write_workspace_file(req: WriteFileRequest):
    """Crea, sobreescribe o parchea inteligentemente un archivo en la carpeta del proyecto."""
    active_ws = _sync_workspace(req.workspace_path)
    target = (active_ws / req.path).resolve()
    if not str(target).startswith(str(active_ws.resolve())):
        raise HTTPException(status_code=403, detail="Acceso denegado fuera de la carpeta del proyecto")
    if target.parent.resolve() == BASE_DIR.resolve() and req.path.lower() in {"server.py", "run.py", "download_model.py", "iniciar_hackingllm.bat"}:
        raise HTTPException(status_code=403, detail="Protección activa: no se permite sobrescribir archivos internos del motor HackingLLM.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Verificar si es una edición parcial SEARCH/REPLACE
        has_search_block = ("SEARCH" in req.content.upper() and "=======" in req.content)
        if target.exists() and has_search_block and not req.force:
            original = target.read_text(encoding="utf-8", errors="replace")
            new_content, applied = apply_search_replace_patches(original, req.content)
            if applied > 0:
                target.write_text(new_content, encoding="utf-8")
                return {
                    "success": True, 
                    "path": req.path, 
                    "patched": True, 
                    "patches_applied": applied,
                    "bytes": len(new_content)
                }
            # Si no pudo hacer match pero tenía formato SEARCH, evitar sobreescribir con el bloque patch roto
            return {
                "success": False, 
                "path": req.path, 
                "patched": False, 
                "message": f"No se encontró el bloque original exacto a reemplazar en {req.path}."
            }

        # Protección contra sobrescritura accidental de un archivo existente con comandos de terminal o salidas de consola
        stripped_cmd = req.content.strip().lower()
        is_cli_or_banner = (
            (len(req.content.strip().splitlines()) <= 4 and any(stripped_cmd.startswith(p) for p in ("pip ", "pip3 ", "python ", "py ", "uvicorn ", "flask ", "npm ", "npx ", "cd ", "curl ")))
            or ("==================================================" in req.content and "ctrl+c" in stripped_cmd)
        )
        if target.exists() and target.stat().st_size > 40 and is_cli_or_banner and not req.force and not has_search_block:
            return {
                "success": False,
                "path": req.path,
                "patched": False,
                "message": f"Bloqueado: '{req.content.strip()[:40]}' parece un comando o salida de terminal, no el código de {req.path}."
            }

        # Guardado normal (archivo nuevo o sobreescritura completa)
        clean_content = req.content
        # Si tenía bloque SEARCH pero se forzó el guardado, extraer todos los bloques de reemplazo
        if has_search_block and req.force:
            import re
            replacements = re.findall(
                r'={3,10}[^\r\n]*\r?\n([\s\S]*?)\r?\n?>{3,10}',
                req.content
            )
            if replacements:
                clean_content = "\n\n".join(r.strip("\r\n") for r in replacements)

        target.write_text(clean_content, encoding="utf-8")
        return {"success": True, "path": req.path, "patched": False, "bytes": len(clean_content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando archivo: {e}")

class CreateItemRequest(BaseModel):
    path: str
    is_directory: bool = False
    workspace_path: Optional[str] = None
    switch_to_folder: Optional[bool] = False

@app.post("/api/workspace/item/create")
def create_workspace_item(req: CreateItemRequest):
    active_ws = _sync_workspace(req.workspace_path)
    raw_p = Path(req.path)
    target = raw_p.resolve() if raw_p.is_absolute() else (active_ws / req.path).resolve()
    if not raw_p.is_absolute() and not str(target).startswith(str(active_ws.resolve())):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    try:
        if req.is_directory:
            target.mkdir(parents=True, exist_ok=True)
            if req.switch_to_folder and target != BASE_DIR.resolve():
                workspace.current_dir = target
                _save_workspace_path(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("", encoding="utf-8")
        return {"success": True, "path": str(target), "workspace": str(workspace.current_dir.resolve())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class DeleteItemRequest(BaseModel):
    path: str
    workspace_path: Optional[str] = None

@app.post("/api/workspace/item/delete")
def delete_workspace_item(req: DeleteItemRequest):
    target = (workspace.current_dir / req.path).resolve()
    if not str(target).startswith(str(workspace.current_dir.resolve())):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Estado global del proceso de llama-server
class ServerState:
    process: Optional[subprocess.Popen] = None
    current_model_path: Optional[str] = None
    current_model_name: Optional[str] = None
    gpu_layers: int = 0
    ctx_size: int = 8192
    port: int = 8085
    is_ready: bool = False
    lock: threading.Lock = threading.Lock()

state = ServerState()

def get_gpu_metrics() -> Dict[str, Any]:
    """Obtiene métricas de la GPU NVIDIA (RTX 4050) usando nvidia-smi."""
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.5)
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 6:
                return {
                    "has_gpu": True,
                    "name": parts[0],
                    "total_mb": float(parts[1]),
                    "used_mb": float(parts[2]),
                    "free_mb": float(parts[3]),
                    "util_pct": float(parts[4]),
                    "temp_c": float(parts[5]),
                }
    except Exception:
        pass
    
    return {
        "has_gpu": False,
        "name": "No NVIDIA GPU",
        "total_mb": 0,
        "used_mb": 0,
        "free_mb": 0,
        "util_pct": 0,
        "temp_c": 0,
    }

def get_system_metrics() -> Dict[str, Any]:
    """Obtiene métricas de CPU y RAM."""
    vm = psutil.virtual_memory()
    return {
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_free_gb": round(vm.available / (1024**3), 2),
        "ram_pct": vm.percent,
        "cpu_pct": psutil.cpu_percent(interval=None),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False) or 6,
    }

def find_llama_server_binary() -> Optional[Path]:
    """Busca el ejecutable llama-server.exe dentro de engine o subcarpetas."""
    if not ENGINE_DIR.exists():
        return None
    for p in ENGINE_DIR.rglob("llama-server.exe"):
        return p
    return None

class LoadModelRequest(BaseModel):
    model_path: str
    mmproj_path: Optional[str] = None     # Proyector multimodal para visión/imágenes
    n_gpu_layers: Optional[int] = 24      # 24 capas óptimo para Qwen 9B + mmproj en RTX 4050 (6GB VRAM)
    ctx_size: Optional[int] = 16384       # 16,384 tokens con context-shift ilimitado
    threads: Optional[int] = 6            # 6 núcleos físicos AMD Ryzen
    flash_attn: Optional[bool] = True
    cache_type_k: Optional[str] = "q4_0"
    cache_type_v: Optional[str] = "q4_0"

def stop_llama_server():
    """Detiene cualquier instancia activa de llama-server."""
    with state.lock:
        if state.process:
            try:
                state.process.terminate()
                state.process.wait(timeout=3)
            except Exception:
                try:
                    state.process.kill()
                except Exception:
                    pass
            state.process = None
        state.is_ready = False
        state.current_model_path = None
        state.current_model_name = None

def _auto_load_default_model():
    """Carga automáticamente el modelo principal de models/ al iniciar el servidor si no está activo."""
    try:
        req_health = urllib.request.Request(f"http://127.0.0.1:{state.port}/health")
        with urllib.request.urlopen(req_health, timeout=1.0) as resp:
            if resp.status == 200:
                state.is_ready = True
                return
    except Exception:
        pass

    try:
        catalog = list_models()
        models = catalog.get("models", [])
        if models:
            m = models[0]
            load_model(LoadModelRequest(
                model_path=m["path"],
                mmproj_path=m.get("suggested_mmproj"),
                n_gpu_layers=24,
                ctx_size=16384,
                threads=6,
                flash_attn=True,
                cache_type_k="q4_0",
                cache_type_v="q4_0",
            ))
    except Exception:
        pass

@app.on_event("startup")
def on_startup():
    threading.Thread(target=_auto_load_default_model, daemon=True).start()

@app.on_event("shutdown")
def on_shutdown():
    stop_llama_server()

@app.get("/api/status")
def get_status():
    """Estado general del sistema y del motor."""
    if not state.is_ready:
        try:
            req_health = urllib.request.Request(f"http://127.0.0.1:{state.port}/health")
            with urllib.request.urlopen(req_health, timeout=0.5) as resp:
                if resp.status == 200:
                    state.is_ready = True
                    state.current_model_name = "Qwen3.8-9B-Distill-uncensored-heretic.Q4_K_M.gguf"
                    state.ctx_size = 16384
                    state.gpu_layers = 24
        except Exception:
            pass

    gpu = get_gpu_metrics()
    sys_metrics = get_system_metrics()
    server_exe = find_llama_server_binary()
    
    return {
        "engine_installed": server_exe is not None and server_exe.exists(),
        "model_loaded": state.is_ready,
        "current_model": state.current_model_name,
        "current_model_path": state.current_model_path,
        "gpu_layers": state.gpu_layers,
        "ctx_size": state.ctx_size,
        "gpu": gpu,
        "system": sys_metrics,
    }

@app.post("/api/gpu/purge")
def purge_gpu_memory():
    """Libera la GPU matando procesos zombies y forzando recolección de memoria."""
    stop_llama_server()
    killed = 0
    try:
        # Buscar procesos llama-server que no pertenezcan a la app actual
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] and 'llama-server' in proc.info['name'].lower():
                try:
                    proc.kill()
                    killed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return {"success": True, "message": f"VRAM limpiada. Procesos zombies eliminados: {killed}"}

@app.get("/api/browse-file")
def browse_file():
    """Abre el explorador de archivos nativo de Windows para seleccionar un archivo .gguf."""
    try:
        ps_cmd = (
            'Add-Type -AssemblyName System.Windows.Forms; '
            '$dlg = New-Object System.Windows.Forms.OpenFileDialog; '
            '$dlg.Filter = "Archivos GGUF (*.gguf)|*.gguf|Todos los archivos (*.*)|*.*"; '
            '$dlg.Title = "Seleccionar Modelo GGUF para HackingLLM"; '
            'if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dlg.FileName }'
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], stdout=subprocess.PIPE, text=True, timeout=30)
        file_path = res.stdout.strip()
        if file_path and os.path.exists(file_path):
            p = Path(file_path)
            size_gb = round(p.stat().st_size / (1024**3), 2)
            return {"path": str(p.resolve()), "name": p.name, "size_gb": size_gb}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el selector: {e}")
    return {"path": None}

@app.post("/api/open-models-dir")
def open_models_dir():
    """Abre la carpeta models/ en el explorador de Windows."""
    try:
        os.startfile(str(MODELS_DIR.resolve()))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/models/list")
def list_models():
    """
    Lista archivos GGUF clasificando modelos de lenguaje base y proyectores multimodales (mmproj).
    """
    all_files = []
    
    # 1. Carpeta local models/
    if MODELS_DIR.exists():
        for file in MODELS_DIR.glob("*.gguf"):
            all_files.append((file, "models/"))
            
    # 2. Archivos en el directorio raíz de HackingLLM
    for file in BASE_DIR.glob("*.gguf"):
        all_files.append((file, "raíz/"))

    base_models = []
    mmproj_files = []

    for file, folder in all_files:
        size_gb = round(file.stat().st_size / (1024**3), 2)
        info = {
            "name": file.name,
            "path": str(file.resolve()),
            "size_gb": size_gb,
            "folder": folder
        }
        if "mmproj" in file.name.lower():
            mmproj_files.append(info)
        else:
            base_models.append(info)

    # Vincular sugerencia de mmproj para cada modelo base
    for bm in base_models:
        base_prefix = bm["name"].split(".")[0].lower()
        matched = None
        for mm in mmproj_files:
            if base_prefix in mm["name"].lower():
                matched = mm["path"]
                break
        bm["suggested_mmproj"] = matched or (mmproj_files[0]["path"] if mmproj_files else None)

    return {
        "models": base_models,
        "mmprojs": mmproj_files,
        "models_dir": str(MODELS_DIR.resolve())
    }

@app.post("/api/models/unload")
def unload_model():
    """Descarga el modelo actual y libera toda la VRAM."""
    stop_llama_server()
    return {"success": True, "message": "Modelo descargado y memoria liberada"}

@app.post("/api/models/load")
def load_model(req: LoadModelRequest):
    """Carga un archivo GGUF con los parámetros hiper-optimizados para la GPU."""
    model_path = Path(req.model_path)
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"No se encontró el archivo GGUF en: {req.model_path}")
        
    server_exe = find_llama_server_binary()
    if not server_exe:
        raise HTTPException(status_code=500, detail="El binario llama-server.exe no está disponible en engine/")

    stop_llama_server()

    # Si se pide optimización automática para RTX 4050 (6GB)
    gpu_metrics = get_gpu_metrics()
    free_vram_mb = gpu_metrics.get("free_mb", 3500) if gpu_metrics["has_gpu"] else 0
    
    # Calcular capas seguras si se seleccionó automático (-1 o None)
    ngl = req.n_gpu_layers if req.n_gpu_layers is not None else 33
    
    target_ctx = req.ctx_size or 16384
    cache_k = req.cache_type_k or "q4_0"
    cache_v = req.cache_type_v or "q4_0"

    cmd = [
        str(server_exe),
        "--model", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(state.port),
        "--ctx-size", str(target_ctx),
        "--predict", "-1",
        "--threads", str(req.threads or 6),
        "--n-gpu-layers", str(ngl),
        "--batch-size", "512",
        "--ubatch-size", "512",
        "--cont-batching",
        "--parallel", "1",
        "--context-shift",
        "--keep", "1024",
        "--cache-type-k", cache_k,
        "--cache-type-v", cache_v,
    ]
    
    if req.flash_attn:
        cmd.extend(["--flash-attn", "on"])
    else:
        cmd.extend(["--flash-attn", "off"])
        
    if req.mmproj_path and os.path.exists(req.mmproj_path):
        cmd.extend(["--mmproj", str(req.mmproj_path)])

    env = os.environ.copy()
    # Asegurar que las DLLs de CUDA en engine/ estén en el PATH del subproceso
    engine_bin_dir = str(server_exe.parent)
    env["PATH"] = engine_bin_dir + os.pathsep + env.get("PATH", "")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fallo al iniciar llama-server: {e}")

    # Lector de logs en segundo plano para evitar que se llene el buffer del pipe en Windows
    logs_buffer = []
    def log_collector():
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                logs_buffer.append(line)
                if len(logs_buffer) > 250:
                    logs_buffer.pop(0)
        except Exception:
            pass

    log_thread = threading.Thread(target=log_collector, daemon=True)
    log_thread.start()

    with state.lock:
        state.process = proc
        state.current_model_path = str(model_path)
        state.current_model_name = model_path.name
        state.gpu_layers = ngl
        state.ctx_size = req.ctx_size or 8192

    # Esperar hasta que el servidor responda /health (máximo 60 segundos)
    start_time = time.time()
    ready = False
    
    while time.time() - start_time < 60:
        if proc.poll() is not None:
            # El proceso murió inesperadamente
            time.sleep(0.3)
            out = "".join(logs_buffer[-25:])
            stop_llama_server()
            raise HTTPException(status_code=500, detail=f"llama-server se cerró. Log:\n{out}")
            
        try:
            req_health = urllib.request.Request(f"http://127.0.0.1:{state.port}/health")
            with urllib.request.urlopen(req_health, timeout=1.0) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)

    if not ready:
        out = "".join(logs_buffer[-20:])
        stop_llama_server()
        raise HTTPException(status_code=504, detail=f"Tiempo de espera agotado al cargar el modelo. Log:\n{out}")

    state.is_ready = True
    return {
        "success": True,
        "message": f"Modelo {model_path.name} cargado con éxito",
        "gpu_layers": ngl,
        "ctx_size": state.ctx_size,
    }

class ChatMessage(BaseModel):
    role: str
    content: Any

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except Exception:
    HAS_DDGS = False

def perform_web_search(query: str, max_results: int = 3) -> str:
    """Realiza una búsqueda web en tiempo real y devuelve el resumen para el LLM."""
    if not HAS_DDGS or not query.strip():
        return ""
    try:
        clean_query = query.strip()
        with DDGS() as ddgs:
            results = list(ddgs.text(clean_query, max_results=max_results))
            if not results:
                return ""
            
            snippets = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                snippet = r.get("body", "")
                url = r.get("href", "")
                snippets.append(f"{i}. {title}\n   Fuente: {url}\n   Info: {snippet}")
                
            return (
                "\n\n=== INFORMACIÓN EN TIEMPO REAL OBTENIDA DE INTERNET (WEB SEARCH) ===\n"
                f"Consulta realizada: '{clean_query}'\n\n"
                + "\n\n".join(snippets) +
                "\n=== FIN DE INFORMACIÓN DE INTERNET ===\n"
                "Usa esta información fresca de internet para responder con precisión técnica."
            )
    except Exception:
        return ""

class ActiveFileInfo(BaseModel):
    path: Optional[str] = None
    content: Optional[str] = None

class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    mode: Optional[str] = "agent"          # "agent" (crear apps/archivos) o "chat" (pregunta normal)
    web_search: Optional[bool] = True      # Búsqueda web RAG activa
    active_file: Optional[ActiveFileInfo] = None  # Archivo que el usuario tiene abierto en el editor
    project_files: Optional[List[str]] = None    # Lista de archivos en la carpeta del proyecto
    workspace_path: Optional[str] = None   # Ruta activa de la carpeta del proyecto en el frontend
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = -1         # -1 = SIN LÍMITE (genera hasta finalizar respuesta)
    stream: Optional[bool] = True

def get_project_code_context(folder: Path, max_files: int = 8, max_chars_per_file: int = 8000, active_path: Optional[str] = None) -> str:
    """Lee el código real de los archivos de la carpeta del proyecto evitando duplicar el archivo activo o los archivos internos del IDE."""
    code_exts = {".py", ".js", ".html", ".css", ".json", ".ts", ".jsx", ".tsx", ".sh", ".bat", ".sql", ".txt", ".md"}
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "engine", "models"}
    is_ide_root = (folder.resolve() == BASE_DIR.resolve())
    ide_internal_files = {"server.py", "run.py", "download_model.py", "iniciar_hackingllm.bat", "readme.md"}
    
    parts = []
    try:
        found_files = []
        norm_active = active_path.replace("\\", "/").lower() if active_path else None
        active_name = Path(active_path).name.lower() if active_path else None

        for p in folder.rglob("*"):
            if any(ign in p.parts for ign in ignored) or p.name.startswith("."):
                continue
            if is_ide_root and ("static" in p.parts or p.name.lower() in ide_internal_files):
                continue
            if p.is_file() and p.suffix.lower() in code_exts:
                rel = str(p.relative_to(folder)).replace("\\", "/")
                # Si este archivo ya está abierto en el editor, omitirlo aquí para no duplicar miles de tokens
                if norm_active and (rel.lower() == norm_active or p.name.lower() == active_name):
                    continue
                found_files.append(p)
                
        # Priorizar archivos principales
        priority_names = ["main.py", "app.py", "index.html", "sniffer.py", "ui.py", "database.py"]
        found_files.sort(key=lambda x: (0 if x.name.lower() in priority_names else 1, x.name.lower()))
        
        for file in found_files[:max_files]:
            rel = str(file.relative_to(folder)).replace("\\", "/")
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + "\n... [contenido resumido para optimizar memoria]"
                parts.append(f"--- ARCHIVO: {rel} ---\n{content}\n")
            except Exception:
                pass
    except Exception:
        pass
        
    if not parts:
        return ""
    return "\n=== OTROS ARCHIVOS DEL PROYECTO (REFERENCIA) ===\n" + "\n".join(parts) + "\n=== FIN REFERENCIA ===\n"

@app.post("/api/chat")
async def chat_proxy(chat_req: ChatCompletionRequest):
    """
    Proxy de streaming hacia llama-server con soporte ultra-amplio de 16,384 tokens
    y optimización de contexto.
    """
    if not state.is_ready:
        try:
            req_health = urllib.request.Request(f"http://127.0.0.1:{state.port}/health")
            with urllib.request.urlopen(req_health, timeout=1.0) as resp:
                if resp.status == 200:
                    state.is_ready = True
                    state.current_model_name = "Qwen3.8-9B-Distill-uncensored-heretic.Q4_K_M.gguf"
                    state.ctx_size = 16384
                    state.gpu_layers = 24
        except Exception:
            pass

    if not state.is_ready:
        _auto_load_default_model()

    if not state.is_ready:
        raise HTTPException(status_code=400, detail="No hay ningún modelo GGUF cargado.")

    target_url = f"http://127.0.0.1:{state.port}/v1/chat/completions"
    _sync_workspace(chat_req.workspace_path)
    
    # Inyectar contexto optimizado del repositorio (sin duplicar el archivo en pantalla)
    active_p = chat_req.active_file.path if chat_req.active_file else None
    repo_code = get_project_code_context(workspace.current_dir, active_path=active_p)
    context_parts = []
    context_parts.append(f"Eres Antigravity Code Studio, un asistente experto de programación y software dentro de Visual Studio Code.")
    context_parts.append(f"Directorio de trabajo actual: {str(workspace.current_dir.resolve())}")

    if repo_code:
        context_parts.append(repo_code)

    if chat_req.active_file and chat_req.active_file.path and chat_req.active_file.content:
        file_c = chat_req.active_file.content
        if len(file_c) > 16000:
            file_c = file_c[:16000] + "\n... [archivo extenso truncado]"
        context_parts.append(
            f"\n[ARCHIVO EN PANTALLA EN EL EDITOR ({chat_req.active_file.path})]:\n"
            f"```\n{file_c}\n```\n"
        )

    if chat_req.mode == "agent":
        context_parts.append(
            "\nREGLAS ESTRICTAS DE EDICIÓN QUIRÚRGICA (ESTILO CURSOR / ANTIGRAVITY):\n"
            "1. SI MODIFICAS UN ARCHIVO EXISTENTE (ej. app.py, sniffer.py, main.py, database.py, index.html):\n"
            "   USA OBLIGATORIAMENTE el formato SEARCH / REPLACE para cambiar SOLO las líneas o funciones necesarias.\n"
            "   PROHIBIDO reescribir el archivo completo desde cero si solo vas a corregir o agregar una parte:\n"
            "   ```file:nombre_del_archivo.ext\n"
            "   <<<<<<< SEARCH\n"
            "   // fragmento original exacto a reemplazar (pocas líneas)\n"
            "   =======\n"
            "   // fragmento corregido o nuevo\n"
            "   >>>>>>>\n"
            "   ```\n"
            "2. SOLO si creas un ARCHIVO NUEVO (que no existe aún) o si el archivo actual está vacío, escribe el archivo completo:\n"
            "   ```file:nombre_del_archivo.ext\n"
            "   // código completo\n"
            "   ```\n"
            "IMPORTANTE: Usa SIEMPRE ```file:nombre_exacto.ext en el encabezado del bloque para que el sistema aplique el parche en disco.\n"
            "3. Explica muy brevemente qué parche aplicaste.\n"
            "4. SI EL USUARIO PREGUNTA CÓMO PROBAR O EJECUTAR EL PROYECTO:\n"
            "   Responde directamente en texto explicando qué comando correr (ej. `python main.py`) o presionar el botón 'Probar / Ejecutar'."
        )
    else:
        context_parts.append(
            "\nMODO PREGUNTA NORMAL: Responde directamente en texto a las preguntas y dudas del usuario "
            "usando el código del proyecto que ya tienes arriba en este prompt. No inventes código ni pidas que te lo compartan, ya lo tienes aquí."
        )

    context_parts.append(
        "\nINSTRUCCIÓN DE RESPUESTA RÁPIDA:\n"
        "Sé directo, rápido y conciso. No hagas reflexiones o procesos de pensamiento innecesariamente largos.\n"
        "Comienza a generar la respuesta y los bloques de código de inmediato."
    )

    # Búsqueda Web en Vivo (RAG Web con Filtro Inteligente)
    web_query_used = None
    if chat_req.web_search:
        last_user_text = ""
        for m in reversed(chat_req.messages):
            if m.role == "user":
                if isinstance(m.content, str):
                    last_user_text = m.content
                elif isinstance(m.content, list):
                    for part in m.content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            last_user_text = part.get("text", "")
                            break
                if last_user_text:
                    break
        
        # Filtro inteligente: Solo buscar en internet si realmente es una consulta informativa/web
        skip_web_patterns = [
            "como lo pruebo", "como pruebo", "como ejecuto", "como correr",
            "hola", "gracias", "adios", "ok", "que opinas", "explicame este archivo"
        ]
        should_skip = any(p in last_user_text.lower() for p in skip_web_patterns)

        if last_user_text and len(last_user_text.strip()) > 5 and not should_skip:
            web_info = perform_web_search(last_user_text, max_results=3)
            if web_info:
                web_query_used = last_user_text
                # Incorporar información web dentro del ÚNICO mensaje de sistema (Qwen Jinja exige un solo system message)
                context_parts.append(web_info)

    import re

    def _compress_assistant_text(c_text: str, is_before_continuation: bool = False) -> str:
        # Limpiar cualquier bloque <think> residual (cerrado o truncado)
        cleaned = re.sub(r'<think>[\s\S]*?</think>', '', c_text)
        cleaned = re.sub(r'<think>[\s\S]*$', '', cleaned).strip()
        if not cleaned:
            cleaned = c_text

        if is_before_continuation:
            # Al continuar, el modelo solo necesita ver los últimos caracteres exactos donde quedó cortado
            if len(cleaned) > 1400:
                return "... [código previo ya generado omitido]\n" + cleaned[-1400:]
            return cleaned

        if len(cleaned) > 900 and "```" in cleaned:
            shortened = re.sub(r'```file:[^\n\r]+[\r\n]+[\s\S]*?```', '[Código generado previamente y guardado en disco]', cleaned)
            shortened = re.sub(r'```[a-zA-Z0-9_\-]*[\r\n]+[\s\S]*?```', '[Bloque de código previo]', shortened)
            # Comprimir también bloques truncados sin ``` de cierre
            shortened = re.sub(r'```file:[^\n\r]+[\r\n]+[\s\S]*$', '[Código previo truncado]', shortened)
            shortened = re.sub(r'```[a-zA-Z0-9_\-]*[\r\n]+[\s\S]*$', '[Bloque de código previo truncado]', shortened)
            cleaned = shortened

        if len(cleaned) > 1200:
            cleaned = cleaned[:700] + "\n... [contenido previo resumido]\n" + cleaned[-300:]
        return cleaned

    system_text = "\n".join(context_parts)
    # Con context-shift activo y 16384+ tokens, permitir contexto amplio sin truncar agresivamente el código del proyecto
    max_total_prompt_chars = max(16000, int((state.ctx_size or 16384) * 2.4))
    max_system_chars = int(max_total_prompt_chars * 0.75)
    if len(system_text) > max_system_chars:
        system_text = system_text[:max_system_chars] + "\n... [contexto de sistema acotado]"

    # Qwen y llama-server exigen ESTRICTAMENTE un único mensaje de rol "system" al inicio
    messages_payload = [{"role": "system", "content": system_text}]

    # Podado inteligente del historial: Mantener los últimos 4 mensajes para evaluar el prompt rápido
    user_and_assistant_msgs = [m.dict() for m in chat_req.messages if m.role != "system"]
    if len(user_and_assistant_msgs) > 4:
        user_and_assistant_msgs = user_and_assistant_msgs[-4:]

    last_user_idx = -1
    for i in range(len(user_and_assistant_msgs) - 1, -1, -1):
        if user_and_assistant_msgs[i].get("role") == "user":
            last_user_idx = i
            break

    last_user_str = ""
    if last_user_idx >= 0 and isinstance(user_and_assistant_msgs[last_user_idx].get("content"), str):
        last_user_str = user_and_assistant_msgs[last_user_idx]["content"].lower()
    is_continuation_req = ("continúa" in last_user_str or "continua" in last_user_str) and ("donde te quedaste" in last_user_str or "sin repetir" in last_user_str)

    # Comprimir mensajes del asistente para no saturar nunca n_ctx
    compressed_history = []
    for idx, m in enumerate(user_and_assistant_msgs):
        is_last = (idx == len(user_and_assistant_msgs) - 1)
        if m.get("role") == "assistant" and isinstance(m.get("content"), str):
            is_prev_to_continue = is_continuation_req and (idx == last_user_idx - 1)
            if not is_last or is_prev_to_continue:
                m = {"role": "assistant", "content": _compress_assistant_text(m["content"], is_before_continuation=is_prev_to_continue)}
        compressed_history.append(m)

    # Guard final de presupuesto de caracteres para evitar n_prompt_tokens == n_ctx
    remaining_chars = max(2000, max_total_prompt_chars - len(system_text))
    kept_reversed = []
    for m in reversed(compressed_history):
        c = m.get("content", "")
        c_len = len(c) if isinstance(c, str) else 500
        if kept_reversed and c_len > remaining_chars:
            break
        if isinstance(c, str) and c_len > remaining_chars:
            m = {**m, "content": c[-remaining_chars:]}
            c_len = len(m["content"])
        kept_reversed.append(m)
        remaining_chars -= c_len

    final_history = list(reversed(kept_reversed))
    # Asegurar que el historial tras system no empiece en assistant si se recortó un user antiguo
    while len(final_history) > 1 and final_history[0].get("role") == "assistant":
        final_history.pop(0)

    for m in final_history:
        messages_payload.append(m)

    payload = {
        "messages": messages_payload,
        "temperature": chat_req.temperature,
        "top_p": chat_req.top_p,
        "max_tokens": chat_req.max_tokens if (chat_req.max_tokens is not None and chat_req.max_tokens > 0) else -1,
        "stream": True,
    }

    req_data = json.dumps(payload).encode("utf-8")
    
    def generate():
        start_t = time.time()
        first_token_t = None
        token_count = 0
        finish_reason = None
        
        try:
            if web_query_used:
                yield f"data: {json.dumps({'type': 'web_search_event', 'query': web_query_used})}\n\n"

            http_req = urllib.request.Request(
                target_url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(http_req, timeout=600) as resp:
                for line in resp:
                    line_str = line.decode("utf-8")
                    if not line_str.strip():
                        continue
                    if line_str.startswith("data: "):
                        data_part = line_str[6:].strip()
                        if data_part == "[DONE]":
                            total_time = max(time.time() - start_t, 0.001)
                            speed = round(token_count / total_time, 2)
                            ttft = round((first_token_t - start_t) * 1000, 1) if first_token_t else 0
                            
                            # Enviar paquete final con métricas completas
                            meta_event = {
                                "type": "meta",
                                "tokens": token_count,
                                "total_time_s": round(total_time, 2),
                                "tokens_per_sec": speed,
                                "ttft_ms": ttft,
                                "finish_reason": finish_reason or "stop"
                            }
                            yield f"data: {json.dumps(meta_event)}\n\n"
                            yield "data: [DONE]\n\n"
                            break
                        
                        try:
                            chunk = json.loads(data_part)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                finish = choices[0].get("finish_reason")
                                if finish:
                                    finish_reason = finish
                                content = delta.get("content", "")
                                reasoning = delta.get("reasoning_content", "")
                                if content or reasoning:
                                    token_count += 1
                                    if first_token_t is None:
                                        first_token_t = time.time()
                            yield f"data: {data_part}\n\n"
                        except Exception:
                            yield f"data: {data_part}\n\n"
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            err_data = json.dumps({"type": "error", "error": f"HTTP {e.code}: {err_body}"})
            yield f"data: {err_data}\n\n"
        except Exception as e:
            err_data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {err_data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# Servir archivos estáticos del frontend
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/style.css")
def get_style():
    return FileResponse(
        STATIC_DIR / "style.css", 
        media_type="text/css",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.get("/app.js")
def get_app():
    return FileResponse(
        STATIC_DIR / "app.js", 
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(
            content=index_file.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return HTMLResponse("<h1>HackingLLM Server Activo. Inicializando interfaz gráfica...</h1>")

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("  HackingLLM - GGUF High Performance Studio")
    print("  Optimizaciones activas para NVIDIA RTX 4050 & AMD Ryzen")
    print("="*60 + "\n")
    uvicorn.run("server:app", host="127.0.0.1", port=7860, reload=False)
