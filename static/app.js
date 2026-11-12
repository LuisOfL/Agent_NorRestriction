// ANTIGRAVITY STUDIO - VS CODE + GGUF ENGINE
document.addEventListener("DOMContentLoaded", () => {
  // Monaco Editor State
  let monacoEditor = null;
  let openTabs = new Map(); // path -> { model, isModified }
  let activeFilePath = null;
  let currentWorkspacePath = "";

  // Agente State
  let currentMode = "agent"; // "agent" (crear apps/archivos) o "chat" (pregunta normal)
  let isWebSearchEnabled = true; // Búsqueda web RAG activa por defecto
  let conversationHistory = [];
  let isGenerating = false;
  let abortController = null;
  let currentAttachedImageBase64 = null;
  let lastAssistantMsgContent = "";
  let lastAssistantThinking = "";
  let lastAssistantMsgDiv = null;

  // DOM Elements - Activity Bar & Sidebar
  const actExplorer = document.getElementById("act-explorer");
  const actSettings = document.getElementById("act-settings");
  const actToggleAgent = document.getElementById("act-toggle-agent");
  const viewExplorer = document.getElementById("view-explorer");
  const viewSettings = document.getElementById("view-settings");
  const agentPanel = document.getElementById("agent-panel");

  const workspaceFolderNameEl = document.getElementById("workspace-folder-name");
  const btnOpenWorkspace = document.getElementById("btn-open-workspace");
  const btnWelcomeOpenFolder = document.getElementById("btn-welcome-open-folder");
  const btnWelcomeAskAgent = document.getElementById("btn-welcome-ask-agent");
  const fileTreeContainer = document.getElementById("file-tree-container");
  const btnNewFile = document.getElementById("btn-new-file");
  const btnNewFolder = document.getElementById("btn-new-folder");
  const btnRefreshTree = document.getElementById("btn-refresh-tree");

  // Editor Area Elements
  const tabsBar = document.getElementById("tabs-bar");
  const breadcrumbPath = document.getElementById("breadcrumb-path");
  const btnSaveFile = document.getElementById("btn-save-file");
  const btnRunProject = document.getElementById("btn-run-project");
  const btnOpenPreview = document.getElementById("btn-open-preview");
  const welcomeScreen = document.getElementById("welcome-screen");

  // Agent Elements
  const modeAgentBtn = document.getElementById("mode-agent-btn");
  const modeChatBtn = document.getElementById("mode-chat-btn");
  const btnToggleWeb = document.getElementById("btn-toggle-web");
  const agentMessages = document.getElementById("agent-messages");
  const agentTextarea = document.getElementById("agent-textarea");
  const btnSendAgent = document.getElementById("btn-send-agent");
  const btnStopAgent = document.getElementById("btn-stop-agent");
  const btnClearAgentChat = document.getElementById("btn-clear-agent-chat");
  const continueBanner = document.getElementById("continue-banner");
  const btnContinueGen = document.getElementById("btn-continue-generation");
  const imageInput = document.getElementById("image-input");
  const btnUploadImage = document.getElementById("btn-upload-image");
  const imagePreviewBox = document.getElementById("image-preview-box");
  const imagePreviewImg = document.getElementById("image-preview-img");
  const btnCancelImage = document.getElementById("btn-cancel-image");

  // Hardware & Model Settings Elements
  const vramText = document.getElementById("vram-text");
  const vramPctText = document.getElementById("vram-pct-text");
  const vramFill = document.getElementById("vram-fill");
  const ramText = document.getElementById("ram-text");
  const ramFill = document.getElementById("ram-fill");
  const modelSelect = document.getElementById("model-select");
  const mmprojSelect = document.getElementById("mmproj-select");
  const enableMmproj = document.getElementById("enable-mmproj");
  const gpuLayersSlider = document.getElementById("gpu-layers-slider");
  const gpuLayersBadge = document.getElementById("gpu-layers-badge");
  const ctxSizeSelect = document.getElementById("ctx-size-select");
  const btnLoadModel = document.getElementById("btn-load-model");
  const btnUnloadModel = document.getElementById("btn-unload-model");
  const btnPurgeVram = document.getElementById("btn-purge-vram-side");

  // Status Bar Elements
  const statusActiveFile = document.getElementById("status-active-file");
  const statusVramText = document.getElementById("status-vram-text");
  const statusSpeedText = document.getElementById("status-speed-text");

  // Modal Folder Picker Elements
  const folderPickerModal = document.getElementById("folder-picker-modal");
  const modalBtnClose = document.getElementById("modal-btn-close");
  const modalBtnCancel = document.getElementById("modal-btn-cancel");
  const modalPathInput = document.getElementById("modal-path-input");
  const modalBtnUp = document.getElementById("modal-btn-up");
  const modalBtnGo = document.getElementById("modal-btn-go");
  const modalShortcutsContainer = document.getElementById("modal-shortcuts-container");
  const modalSubfoldersContainer = document.getElementById("modal-subfolders-container");
  const modalBtnConfirm = document.getElementById("modal-btn-confirm");
  const modalBtnCreateSubfolder = document.getElementById("modal-btn-create-subfolder");
  const modalBtnNativeDialog = document.getElementById("modal-btn-native-dialog");

  let modalParentPath = null;

  // 1. INICIALIZAR MONACO EDITOR (VS CODE)
  require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
  require(['vs/editor/editor.main'], function() {
    monacoEditor = monaco.editor.create(document.getElementById('monaco-container'), {
      value: "",
      language: "javascript",
      theme: "vs-dark",
      automaticLayout: true,
      fontSize: 13,
      fontFamily: "'Fira Code', Consolas, 'Courier New', monospace",
      minimap: { enabled: true },
      lineNumbers: "on",
      roundedSelection: true,
      scrollBeyondLastLine: false,
      tabSize: 2,
    });

    // Atajo Ctrl+S en el editor para guardar
    monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      saveActiveFile();
    });

    // Detectar cambios no guardados
    monacoEditor.onDidChangeModelContent(() => {
      if (activeFilePath && openTabs.has(activeFilePath)) {
        const tabInfo = openTabs.get(activeFilePath);
        tabInfo.isModified = true;
        updateTabVisuals();
      }
    });

    // Cargar workspace inicial
    loadWorkspace();
  });

  // 2. NAVEGACIÓN DE LA BARRA DE ACTIVIDAD
  actExplorer.addEventListener("click", () => switchSidebarView("explorer"));
  actSettings.addEventListener("click", () => switchSidebarView("settings"));
  actToggleAgent.addEventListener("click", () => {
    agentPanel.classList.toggle("hidden");
    if (monacoEditor) monacoEditor.layout();
  });

  function switchSidebarView(view) {
    if (view === "explorer") {
      actExplorer.classList.add("active");
      actSettings.classList.remove("active");
      viewExplorer.classList.remove("hidden");
      viewSettings.classList.add("hidden");
    } else {
      actSettings.classList.add("active");
      actExplorer.classList.remove("active");
      viewSettings.classList.remove("hidden");
      viewExplorer.classList.add("hidden");
    }
  }

  // 3. GESTIÓN DEL WORKSPACE & ÁRBOL DE ARCHIVOS
  async function loadWorkspace() {
    try {
      const res = await fetch("/api/workspace/tree");
      const data = await res.json();
      currentWorkspacePath = data.root;
      workspaceFolderNameEl.textContent = data.name || "Proyecto";
      renderFileTree(data.tree, fileTreeContainer);
    } catch (e) {
      console.error("Error al cargar workspace:", e);
    }
  }

  // Abrir carpeta: mostramos el modal interactivo
  btnOpenWorkspace.addEventListener("click", () => openFolderPickerModal());
  if (btnWelcomeOpenFolder) btnWelcomeOpenFolder.addEventListener("click", () => openFolderPickerModal());

  modalBtnClose.addEventListener("click", () => folderPickerModal.classList.add("hidden"));
  modalBtnCancel.addEventListener("click", () => folderPickerModal.classList.add("hidden"));

  async function openFolderPickerModal(targetPath = "") {
    folderPickerModal.classList.remove("hidden");
    await navigateFolderModal(targetPath);
  }

  async function navigateFolderModal(path = "") {
    modalSubfoldersContainer.innerHTML = '<div style="padding:10px; color:#858585;">Cargando carpetas...</div>';
    try {
      const url = path ? `/api/workspace/browse-folders?path=${encodeURIComponent(path)}` : "/api/workspace/browse-folders";
      const res = await fetch(url);
      const data = await res.json();

      modalPathInput.value = data.current_path;
      modalParentPath = data.parent_path;

      // Renderizar accesos directos
      modalShortcutsContainer.innerHTML = "";
      data.shortcuts.forEach(sc => {
        const pill = document.createElement("button");
        pill.className = "shortcut-pill";
        pill.innerHTML = `<i class="fa-solid fa-folder"></i> <span>${sc.name}</span>`;
        pill.addEventListener("click", () => navigateFolderModal(sc.path));
        modalShortcutsContainer.appendChild(pill);
      });

      // Renderizar subcarpetas
      modalSubfoldersContainer.innerHTML = "";
      if (data.subfolders && data.subfolders.length > 0) {
        data.subfolders.forEach(sf => {
          const item = document.createElement("div");
          item.className = "subfolder-item";
          item.innerHTML = `<i class="fa-solid fa-folder"></i> <span>${sf.name}</span>`;
          item.addEventListener("click", () => {
            modalPathInput.value = sf.path;
          });
          item.addEventListener("dblclick", () => {
            navigateFolderModal(sf.path);
          });
          modalSubfoldersContainer.appendChild(item);
        });
      } else {
        modalSubfoldersContainer.innerHTML = '<div style="padding:10px; color:#858585; font-size:11px;">(No hay subcarpetas en este directorio)</div>';
      }
    } catch (e) {
      modalSubfoldersContainer.innerHTML = `<div style="padding:10px; color:var(--vsc-rose);">Error: ${e.message}</div>`;
    }
  }

  modalBtnUp.addEventListener("click", () => {
    if (modalParentPath) navigateFolderModal(modalParentPath);
  });

  modalBtnGo.addEventListener("click", () => {
    const val = modalPathInput.value.trim();
    if (val) navigateFolderModal(val);
  });

  modalPathInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const val = modalPathInput.value.trim();
      if (val) navigateFolderModal(val);
    }
  });

  // Confirmar selección de carpeta
  modalBtnConfirm.addEventListener("click", async () => {
    const chosenPath = modalPathInput.value.trim();
    if (!chosenPath) return;

    try {
      const res = await fetch("/api/workspace/set-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: chosenPath })
      });
      const data = await res.json();
      if (data.success) {
        folderPickerModal.classList.add("hidden");
        // Cerrar pestañas viejas y cargar nuevo workspace
        openTabs.clear();
        activeFilePath = null;
        tabsBar.innerHTML = "";
        welcomeScreen.classList.remove("hidden");
        await loadWorkspace();
      } else {
        alert(data.detail || data.message || "No se pudo abrir esa carpeta.");
      }
    } catch (e) {
      alert("Error: " + e.message);
    }
  });

  // Crear nueva subcarpeta desde el modal y seleccionarla inmediatamente como proyecto activo
  modalBtnCreateSubfolder.addEventListener("click", async () => {
    const name = prompt("Nombre de la nueva carpeta para tu proyecto:");
    if (!name || !name.trim()) return;
    const parentPath = modalPathInput.value.trim();
    try {
      const fullPath = parentPath + (parentPath.endsWith("\\") || parentPath.endsWith("/") ? "" : "\\") + name.trim();
      const res = await fetch("/api/workspace/set-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: fullPath })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.detail || data.message || "No se pudo crear la carpeta");
      }
      folderPickerModal.classList.add("hidden");
      openTabs.clear();
      activeFilePath = null;
      tabsBar.innerHTML = "";
      welcomeScreen.classList.remove("hidden");
      await loadWorkspace();
    } catch (e) {
      alert("Error al crear carpeta: " + e.message);
    }
  });

  // Selector nativo de Windows (con TopMost al frente)
  modalBtnNativeDialog.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/workspace/select-folder", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        folderPickerModal.classList.add("hidden");
        openTabs.clear();
        activeFilePath = null;
        tabsBar.innerHTML = "";
        welcomeScreen.classList.remove("hidden");
        await loadWorkspace();
      } else if (data.message) {
        alert(data.message);
      }
    } catch (e) {
      alert("Error en el selector nativo: " + e.message);
    }
  });

  btnRefreshTree.addEventListener("click", loadWorkspace);

  // Crear Nuevo Archivo
  btnNewFile.addEventListener("click", async () => {
    const filename = prompt("Nombre del archivo (ejemplo: app.py, index.html):");
    if (!filename) return;
    try {
      await fetch("/api/workspace/item/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filename, is_directory: false, workspace_path: currentWorkspacePath })
      });
      await loadWorkspace();
      openFileInEditor(filename);
    } catch (e) {
      alert("Error creando archivo: " + e.message);
    }
  });

  // Crear Nueva Carpeta y entrar en ella como carpeta activa del proyecto
  btnNewFolder.addEventListener("click", async () => {
    const foldername = prompt("Nombre de la nueva carpeta de proyecto:");
    if (!foldername || !foldername.trim()) return;
    try {
      const res = await fetch("/api/workspace/item/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: foldername.trim(),
          is_directory: true,
          workspace_path: currentWorkspacePath,
          switch_to_folder: true
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo crear la carpeta");
      openTabs.clear();
      activeFilePath = null;
      tabsBar.innerHTML = "";
      welcomeScreen.classList.remove("hidden");
      await loadWorkspace();
    } catch (e) {
      alert("Error creando carpeta: " + e.message);
    }
  });

  function renderFileTree(nodes, container, depth = 0) {
    container.innerHTML = "";
    if (!nodes || nodes.length === 0) {
      const emptyDiv = document.createElement("div");
      emptyDiv.style.padding = "8px 14px";
      emptyDiv.style.fontSize = "11px";
      emptyDiv.style.color = "var(--vsc-text-muted)";
      emptyDiv.textContent = "Carpeta vacía. Pídele al Agente que cree una app.";
      container.appendChild(emptyDiv);
      return;
    }

    nodes.forEach(node => {
      const item = document.createElement("div");
      item.className = "tree-item";
      item.style.paddingLeft = `${12 + depth * 14}px`;

      if (node.type === "directory") {
        item.innerHTML = `<i class="fa-solid fa-folder folder-icon"></i> <span>${node.name}</span>`;
        container.appendChild(item);

        const subContainer = document.createElement("div");
        renderFileTree(node.children, subContainer, depth + 1);
        container.appendChild(subContainer);

        item.addEventListener("click", () => {
          subContainer.classList.toggle("hidden");
          const icon = item.querySelector("i");
          if (subContainer.classList.contains("hidden")) {
            icon.className = "fa-solid fa-folder folder-icon";
          } else {
            icon.className = "fa-solid fa-folder-open folder-icon";
          }
        });
      } else {
        const iconClass = getFileIconClass(node.name);
        item.innerHTML = `<i class="${iconClass}"></i> <span>${node.name}</span>`;
        item.addEventListener("click", () => openFileInEditor(node.path));
        container.appendChild(item);
      }
    });
  }

  function getFileIconClass(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    switch (ext) {
      case "html": return "fa-brands fa-html5 html-icon";
      case "css": return "fa-brands fa-css3-alt css-icon";
      case "js": return "fa-brands fa-js js-icon";
      case "py": return "fa-brands fa-python py-icon";
      case "json": return "fa-solid fa-code json-icon";
      case "md": return "fa-solid fa-circle-info md-icon";
      default: return "fa-regular fa-file-code";
    }
  }

  function getMonacoLanguage(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    switch (ext) {
      case "html": return "html";
      case "css": return "css";
      case "js": return "javascript";
      case "ts": return "typescript";
      case "py": return "python";
      case "json": return "json";
      case "md": return "markdown";
      case "bat": return "bat";
      case "sh": return "shell";
      case "sql": return "sql";
      default: return "plaintext";
    }
  }

  // 4. EDICIÓN, PESTAÑAS Y MONACO
  async function openFileInEditor(path, forceReload = false) {
    welcomeScreen.classList.add("hidden");

    if (openTabs.has(path) && !forceReload) {
      setActiveTab(path);
      return;
    }

    try {
      const res = await fetch(`/api/workspace/file/read?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error leyendo archivo");

      if (openTabs.has(path) && forceReload) {
        const tabInfo = openTabs.get(path);
        if (tabInfo && tabInfo.model) {
          tabInfo.model.setValue(data.content);
          tabInfo.isModified = false;
        }
        setActiveTab(path);
        return;
      }

      const lang = getMonacoLanguage(path);
      const model = monaco.editor.createModel(data.content, lang);

      openTabs.set(path, { model: model, isModified: false });
      createTabElement(path);
      setActiveTab(path);
    } catch (e) {
      console.error("Error al abrir archivo:", e);
    }
  }

  function createTabElement(path) {
    const filename = path.split("/").pop();
    const tab = document.createElement("div");
    tab.className = "tab-item";
    tab.dataset.path = path;
    tab.innerHTML = `
      <i class="${getFileIconClass(filename)}"></i>
      <span class="tab-title">${filename}</span>
      <span class="tab-close">&times;</span>
    `;

    tab.addEventListener("click", (e) => {
      if (e.target.classList.contains("tab-close")) {
        closeTab(path);
      } else {
        setActiveTab(path);
      }
    });

    tabsBar.appendChild(tab);
  }

  const agentContextFilename = document.getElementById("agent-context-filename");

  function setActiveTab(path) {
    activeFilePath = path;
    const tabInfo = openTabs.get(path);
    if (!tabInfo) return;

    monacoEditor.setModel(tabInfo.model);
    breadcrumbPath.textContent = path;
    statusActiveFile.innerHTML = `<span>${path}</span>`;
    if (agentContextFilename) {
      agentContextFilename.textContent = path;
    }

    // Vista previa si es HTML
    if (path.endsWith(".html")) {
      btnOpenPreview.classList.remove("hidden");
    } else {
      btnOpenPreview.classList.add("hidden");
    }

    // Actualizar clases activas en tabs
    tabsBar.querySelectorAll(".tab-item").forEach(t => {
      if (t.dataset.path === path) t.classList.add("active");
      else t.classList.remove("active");
    });
  }

  function closeTab(path) {
    const tabInfo = openTabs.get(path);
    if (tabInfo && tabInfo.model) tabInfo.model.dispose();
    openTabs.delete(path);

    const tabEl = tabsBar.querySelector(`.tab-item[data-path="${path}"]`);
    if (tabEl) tabEl.remove();

    if (activeFilePath === path) {
      const remainingPaths = Array.from(openTabs.keys());
      if (remainingPaths.length > 0) {
        setActiveTab(remainingPaths[remainingPaths.length - 1]);
      } else {
        activeFilePath = null;
        breadcrumbPath.textContent = "Sin archivo abierto";
        statusActiveFile.innerHTML = `<span>Sin archivo activo</span>`;
        if (agentContextFilename) agentContextFilename.textContent = "Ninguno (Abre un archivo para que lo analice)";
        welcomeScreen.classList.remove("hidden");
      }
    }
  }

  function updateTabVisuals() {
    tabsBar.querySelectorAll(".tab-item").forEach(t => {
      const p = t.dataset.path;
      const tabInfo = openTabs.get(p);
      const titleSpan = t.querySelector(".tab-title");
      if (tabInfo && tabInfo.isModified) {
        if (!titleSpan.textContent.endsWith(" •")) {
          titleSpan.textContent = titleSpan.textContent + " •";
        }
      } else {
        titleSpan.textContent = p.split("/").pop();
      }
    });
  }

  async function saveActiveFile() {
    if (!activeFilePath || !openTabs.has(activeFilePath)) return;
    const content = monacoEditor.getValue();

    try {
      const res = await fetch("/api/workspace/file/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: activeFilePath, content: content, workspace_path: currentWorkspacePath })
      });
      const data = await res.json();
      if (data.success) {
        const tabInfo = openTabs.get(activeFilePath);
        tabInfo.isModified = false;
        updateTabVisuals();
      }
    } catch (e) {
      alert("Error al guardar archivo: " + e.message);
    }
  }

  btnSaveFile.addEventListener("click", saveActiveFile);

  if (btnRunProject) {
    btnRunProject.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/workspace/run", { method: "POST" });
        const d = await res.json();
        if (!d.success) {
          alert(d.message);
        }
      } catch (e) {
        alert("Error ejecutando proyecto: " + e.message);
      }
    });
  }

  // Previsualizar app web si es HTML
  btnOpenPreview.addEventListener("click", () => {
    if (activeFilePath && activeFilePath.endsWith(".html")) {
      window.open(`file:///${currentWorkspacePath.replace(/\\/g, "/")}/${activeFilePath}`, "_blank");
    }
  });

  // 5. AGENTE IA ANTIGRAVITY (CREADOR DE APLICACIONES)
  modeAgentBtn.addEventListener("click", () => {
    currentMode = "agent";
    modeAgentBtn.classList.add("active");
    modeChatBtn.classList.remove("active");
    agentTextarea.placeholder = "Pide una app (ej. 'Crea un juego de Snake en HTML') o modificar código...";
  });

  modeChatBtn.addEventListener("click", () => {
    currentMode = "chat";
    modeChatBtn.classList.add("active");
    modeAgentBtn.classList.remove("active");
    agentTextarea.placeholder = "Haz una pregunta normal o consulta técnica...";
  });

  // Toggle Búsqueda Web
  if (btnToggleWeb) {
    btnToggleWeb.addEventListener("click", () => {
      isWebSearchEnabled = !isWebSearchEnabled;
      if (isWebSearchEnabled) {
        btnToggleWeb.classList.add("active");
        btnToggleWeb.innerHTML = '<i class="fa-solid fa-globe"></i> <span>Web ON</span>';
      } else {
        btnToggleWeb.classList.remove("active");
        btnToggleWeb.innerHTML = '<i class="fa-solid fa-globe"></i> <span>Web OFF</span>';
      }
    });
  }

  // Sample prompt buttons
  document.querySelectorAll(".sample-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      agentTextarea.value = btn.dataset.prompt;
      handleAgentSend();
    });
  });

  if (btnWelcomeAskAgent) {
    btnWelcomeAskAgent.addEventListener("click", () => {
      agentTextarea.focus();
    });
  }

  // Soporte de imágenes
  btnUploadImage.addEventListener("click", () => imageInput.click());
  imageInput.addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) handleImageFile(f);
  });
  btnCancelImage.addEventListener("click", () => {
    currentAttachedImageBase64 = null;
    imageInput.value = "";
    imagePreviewBox.classList.add("hidden");
  });
  agentTextarea.addEventListener("paste", (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (const item of items) {
      if (item.type.indexOf("image") === 0) {
        handleImageFile(item.getAsFile());
        break;
      }
    }
  });

  function handleImageFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      currentAttachedImageBase64 = e.target.result;
      imagePreviewImg.src = currentAttachedImageBase64;
      imagePreviewBox.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  }

  // Enviar mensaje al Agente
  btnSendAgent.addEventListener("click", handleAgentSend);
  agentTextarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAgentSend();
    }
  });

  function handleAgentSend() {
    if (isGenerating) return;
    const text = agentTextarea.value.trim();
    if (!text && !currentAttachedImageBase64) return;

    continueBanner.classList.add("hidden");

    let historyItem;
    if (currentAttachedImageBase64) {
      appendAgentMsg("user", text || "Analiza esta imagen adjunta.", currentAttachedImageBase64);
      historyItem = {
        role: "user",
        content: [
          { type: "text", text: text || "Analiza esta imagen con tu proyector multimodal." },
          { type: "image_url", image_url: { url: currentAttachedImageBase64 } }
        ]
      };
      currentAttachedImageBase64 = null;
      imageInput.value = "";
      imagePreviewBox.classList.add("hidden");
    } else {
      appendAgentMsg("user", text);
      historyItem = { role: "user", content: text };
    }

    conversationHistory.push(historyItem);
    agentTextarea.value = "";
    agentTextarea.style.height = "auto";

    startAgentGeneration();
  }

  btnContinueGen.addEventListener("click", () => {
    continueBanner.classList.add("hidden");
    conversationHistory.push({
      role: "user",
      content: "Continúa generando el código o respuesta exactamente desde donde te quedaste. No repitas lo anterior."
    });
    startAgentGeneration(true, 0);
  });

  async function startAgentGeneration(isContinuation = false, autoContinueCount = 0) {
    isGenerating = true;
    btnSendAgent.classList.add("hidden");
    btnStopAgent.classList.remove("hidden");
    statusSpeedText.textContent = isContinuation ? "Continuando respuesta..." : "Generando...";

    abortController = new AbortController();
    let willAutoContinue = false;
    let streamFinishReason = null;
    let chunkContentChars = 0;

    let bubble;
    if (isContinuation && lastAssistantMsgDiv) {
      bubble = lastAssistantMsgDiv.querySelector(".msg-bubble-content");
    } else {
      lastAssistantMsgContent = "";
      lastAssistantThinking = "";
      const divInfo = appendAgentMsg("assistant", "");
      lastAssistantMsgDiv = divInfo.wrapper;
      bubble = divInfo.bubble;
      // Mostrar indicador visual animado de inmediato para que nunca se vea "en blanco"
      bubble.innerHTML = '<div class="thinking-loader"><i class="fa-solid fa-circle-notch fa-spin"></i> <span>Analizando proyecto y procesando consulta...</span></div>';
    }

    // Contexto de Antigravity: Archivo activo en pantalla y lista de archivos del proyecto
    let activeFileInfo = null;
    if (activeFilePath && monacoEditor) {
      activeFileInfo = {
        path: activeFilePath,
        content: monacoEditor.getValue()
      };
    }

    const projectFiles = [];
    document.querySelectorAll(".tree-item span").forEach(el => {
      const name = el.textContent.trim();
      if (name && !projectFiles.includes(name)) projectFiles.push(name);
    });

    const payload = {
      messages: conversationHistory,
      mode: currentMode,
      web_search: isWebSearchEnabled,
      active_file: activeFileInfo,
      project_files: projectFiles,
      workspace_path: currentWorkspacePath,
      max_tokens: -1, // Ilimitado: genera hasta completar la respuesta completa
      temperature: 0.7,
      stream: true
    };

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: abortController.signal
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Error en el servidor");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const dataStr = trimmed.slice(6);
          if (dataStr === "[DONE]") break;

          try {
            const parsed = JSON.parse(dataStr);

            if (parsed.type === "web_search_event") {
              const existingBadge = bubble.querySelector(".web-search-badge");
              if (!existingBadge) {
                const badge = document.createElement("div");
                badge.className = "web-search-badge";
                badge.innerHTML = `<i class="fa-solid fa-globe"></i> Búsqueda en tiempo real de Internet aplicada`;
                bubble.insertBefore(badge, bubble.firstChild);
              }
              continue;
            }

            if (parsed.type === "error") {
              bubble.innerHTML += `<div style="color:var(--vsc-rose); margin-top:8px; padding:8px 12px; background:rgba(244,71,71,0.1); border-left:3px solid var(--vsc-rose); border-radius:4px;"><i class="fa-solid fa-circle-exclamation"></i> <b>Error:</b> ${parsed.error}</div>`;
              continue;
            }

            if (parsed.type === "meta") {
              statusSpeedText.textContent = `${parsed.tokens_per_sec} t/s`;
              streamFinishReason = parsed.finish_reason;
              continue;
            }

            const delta = parsed.choices?.[0]?.delta?.content || "";
            const reasoning = parsed.choices?.[0]?.delta?.reasoning_content || "";

            if (reasoning) lastAssistantThinking += reasoning;
            if (delta) {
              lastAssistantMsgContent += delta;
              chunkContentChars += delta.length;
            }

            if (delta || reasoning) {
              renderAgentBubble(bubble, lastAssistantThinking, lastAssistantMsgContent);
              agentMessages.scrollTop = agentMessages.scrollHeight;
            }
          } catch (e) {}
        }
      }

      // Sincronizar historial manteniendo alternancia válida user -> assistant
      if (isContinuation) {
        if (conversationHistory.length > 0 && conversationHistory[conversationHistory.length - 1].role === "user") {
          conversationHistory.pop();
        }
        if (conversationHistory.length > 0 && conversationHistory[conversationHistory.length - 1].role === "assistant") {
          conversationHistory[conversationHistory.length - 1].content = lastAssistantMsgContent;
        } else {
          conversationHistory.push({ role: "assistant", content: lastAssistantMsgContent });
        }
      } else {
        conversationHistory.push({ role: "assistant", content: lastAssistantMsgContent });
      }

      // Auto-continuar sin pausa si llama-server reportó límite de longitud y generó avance real
      if (streamFinishReason === "length" && !abortController.signal.aborted && chunkContentChars > 30 && autoContinueCount < 3) {
        willAutoContinue = true;
        conversationHistory.push({
          role: "user",
          content: "Continúa generando el código o respuesta exactamente desde donde te quedaste. No repitas lo anterior."
        });
      } else {
        if (streamFinishReason === "length") {
          continueBanner.classList.remove("hidden");
        }
        // Procesar y guardar en disco automáticamente los archivos generados en modo Agente
        if (currentMode === "agent") {
          await extractAndSaveAgentFiles(lastAssistantMsgContent, bubble);
        }
        addManualSaveButton(bubble, lastAssistantMsgContent);
      }

    } catch (err) {
      if (err.name === "AbortError") {
        bubble.innerHTML += ` *[Generación detenida]*`;
      } else {
        bubble.innerHTML += `<div style="color:var(--vsc-rose); margin-top:6px;"><b>Error:</b> ${err.message}</div>`;
      }
    } finally {
      if (!willAutoContinue) {
        isGenerating = false;
        btnSendAgent.classList.remove("hidden");
        btnStopAgent.classList.add("hidden");
      }
    }

    if (willAutoContinue) {
      await startAgentGeneration(true, autoContinueCount + 1);
    }
  }

  btnStopAgent.addEventListener("click", () => {
    if (abortController) abortController.abort();
  });

  function renderAgentBubble(bubble, thinking, content) {
    let html = "";
    if (thinking) {
      html += `<details class="thought-box" open><summary><i class="fa-solid fa-brain"></i> Proceso de Pensamiento</summary><div class="thought-content">${marked.parse(thinking)}</div></details>`;
    }
    if (content) {
      html += marked.parse(content);
    }
    bubble.innerHTML = html;
  }

  // EXTRACTOR Y GUARDADOR AUTOMÁTICO DE ARCHIVOS (ESTILO ANTIGRAVITY)
  async function extractAndSaveAgentFiles(fullText, bubbleContainer) {
    const detectedFiles = parseCodeBlocks(fullText);

    if (detectedFiles.length === 0) return;

    let savedFiles = [];
    for (const file of detectedFiles) {
      try {
        const res = await fetch("/api/workspace/file/write", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: file.path, content: file.content, workspace_path: currentWorkspacePath })
        });
        const data = await res.json();
        if (data.success) {
          savedFiles.push({
            path: file.path,
            patched: !!data.patched,
            patches_applied: data.patches_applied || 1
          });
        } else {
          // Si el parche parcial no coincidió exactamente, dar opción con un clic de forzar el guardado
          const failCard = document.createElement("div");
          failCard.className = "file-action-card file-action-warning";
          failCard.style.borderColor = "var(--vsc-yellow)";
          failCard.innerHTML = `
            <div class="file-action-info">
              <i class="fa-solid fa-triangle-exclamation" style="color:var(--vsc-yellow); font-size:16px;"></i>
              <div class="file-action-text">
                <span class="file-action-name">${file.path}</span>
                <span class="file-action-status" style="color:var(--vsc-foreground-muted);">${data.message || "No se pudo aplicar automáticamente"}</span>
              </div>
            </div>
            <button class="file-action-btn btn-force-write"><i class="fa-solid fa-floppy-disk"></i> Forzar Guardado</button>
          `;
          failCard.querySelector(".btn-force-write").addEventListener("click", async (e) => {
            const btnEl = e.currentTarget;
            btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Guardando...';
            try {
              const fRes = await fetch("/api/workspace/file/write", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: file.path, content: file.content, force: true, workspace_path: currentWorkspacePath })
              });
              const fData = await fRes.json();
              if (fData.success) {
                btnEl.innerHTML = '<i class="fa-solid fa-check"></i> ¡Guardado en disco!';
                await loadWorkspace();
                if (openTabs.has(file.path)) openFileInEditor(file.path, true);
              }
            } catch (err) {
              btnEl.innerHTML = '<i class="fa-solid fa-xmark"></i> Error';
            }
          });
          bubbleContainer.appendChild(failCard);
        }
      } catch (e) {
        console.error("Error guardando archivo:", file.path, e);
      }
    }

    if (savedFiles.length > 0) {
      // Recargar árbol de archivos en el explorador
      await loadWorkspace();

      // Renderizar tarjetas interactivas de Antigravity en el chat
      savedFiles.forEach((fileObj, idx) => {
        const fPath = fileObj.path;
        // Evitar duplicar tarjeta si ya existe
        const existingCard = bubbleContainer.querySelector(`.file-action-card[data-file="${fPath}"]`);
        if (existingCard) return;

        const card = document.createElement("div");
        card.className = "file-action-card";
        card.dataset.file = fPath;

        const statusHtml = fileObj.patched
          ? `<i class="fa-solid fa-wand-magic-sparkles" style="color:var(--vsc-blue);"></i> Modificación aplicada en disco (${fileObj.patches_applied} cambio(s))`
          : `<i class="fa-solid fa-check"></i> Archivo creado y guardado en disco`;

        card.innerHTML = `
          <div class="file-action-info">
            <i class="fa-solid fa-file-code"></i>
            <div class="file-action-text">
              <span class="file-action-name">${fPath}</span>
              <span class="file-action-status">${statusHtml}</span>
            </div>
          </div>
          <button class="file-action-btn"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en Editor</button>
        `;
        card.querySelector(".file-action-btn").addEventListener("click", () => {
          openFileInEditor(fPath);
        });
        bubbleContainer.appendChild(card);

        // Si ya está abierto en pestaña, recargarlo en vivo; si no, abrirlo si es el primer archivo
        if (openTabs.has(fPath)) {
          openFileInEditor(fPath, true);
        } else if (idx === 0) {
          openFileInEditor(fPath);
        }
      });
    }
  }

  function parseCodeBlocks(text) {
    const files = [];
    const knownFiles = Array.from(document.querySelectorAll("#file-tree .tree-label")).map(el => el.textContent.trim());

    // 1. Regex universal que captura cualquier bloque de código ```tag ... ```
    const blockRegex = /```([^\r\n]*)\s*[\r\n]+([\s\S]*?)```/g;
    let match;
    let unnamedCount = 1;

    while ((match = blockRegex.exec(text)) !== null) {
      const rawHeader = match[1].trim();
      const content = match[2].trim();
      const matchIndex = match.index;

      if (!content || content.length < 5) continue;

      let filename = null;
      let isExplicitFile = false;
      const isPatchBlock = /<{3,10}\s*SEARCH/i.test(content) && /={3,10}/.test(content);
      const headerLang = rawHeader.toLowerCase().split(/[\s:]+/)[0];
      const validCodeExts = new Set([
        "py", "js", "ts", "jsx", "tsx", "html", "htm", "css", "scss",
        "json", "sql", "sh", "bat", "ps1", "yaml", "yml", "toml", "ini",
        "cfg", "md", "txt", "c", "cpp", "h", "hpp", "java", "go", "rs",
        "php", "rb", "xml"
      ]);
      const hasValidExt = (fname) => {
        if (!fname || !fname.includes(".")) return false;
        const ext = fname.split(".").pop().toLowerCase();
        return validCodeExts.has(ext);
      };

      // A. Coincidencias tipo: file:nombre.ext o file="nombre.ext"
      const fileHeaderMatch = rawHeader.match(/(?:file[:=\s]+)([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+)/i);
      if (fileHeaderMatch) {
        const candidate = fileHeaderMatch[1].replace(/^[.\/\\]+/, "").trim();
        if (hasValidExt(candidate)) {
          filename = candidate;
          isExplicitFile = true;
        }
      }

      // B. El encabezado mismo contiene el nombre del archivo (ej. ```main.py, ```sniffer.py o ```python:main.py)
      if (!filename && rawHeader.includes(".")) {
        const parts = rawHeader.split(/[:\s]+/);
        for (const p of parts) {
          const cleanP = p.replace(/^[.\/\\]+/, "").trim();
          if (cleanP.includes(".") && !cleanP.startsWith("-") && /^[a-zA-Z0-9_\-\/]+\.[a-zA-Z0-9]+$/.test(cleanP) && hasValidExt(cleanP)) {
            filename = cleanP;
            isExplicitFile = true;
            break;
          }
        }
      }

      // Ignorar bloques sin lenguaje (salidas de consola), bash, texto plano o comandos sueltos
      const nonFileLangs = new Set([
        "", "bash", "sh", "shell", "zsh", "fish", "cmd", "bat", "batch",
        "powershell", "ps1", "console", "terminal", "text", "plaintext",
        "txt", "output", "log", "diff", "markdown", "md"
      ]);
      if (!isExplicitFile && !isPatchBlock) {
        if (nonFileLangs.has(headerLang)) continue;
        const trimmedLines = content.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
        const looksLikeCliOrBanner = (
          (trimmedLines.length <= 4 && trimmedLines.every(l =>
            /^(?:\$\s*)?(?:pip3?|python3?|py|uvicorn|flask|npm|npx|node|cd|ls|dir|mkdir|curl|git|pytest|sudo)\b/i.test(l)
          )) ||
          content.includes("==================================================")
        );
        if (looksLikeCliOrBanner) continue;
      }

      // C. Buscar en las primeras 5 líneas de código por comentarios (# main.py, // app.js, etc.)
      if (!filename) {
        const lines = content.split("\n").slice(0, 5);
        for (const line of lines) {
          const trimmed = line.trim();
          const m = trimmed.match(/^(?:#|\/\/|\/\*|<!--|--)\s*(?:archivo:|file:)?\s*([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+)/i);
          if (m) {
            const candidate = m[1].replace(/^[.\/\\]+/, "").trim();
            if (hasValidExt(candidate)) {
              filename = candidate;
              isExplicitFile = true;
              break;
            }
          }
        }
      }

      // D. Buscar si en el texto inmediatamente anterior (hasta 200 caracteres antes del bloque) se menciona un archivo válido
      if (!filename && matchIndex > 0) {
        const precedingText = text.slice(Math.max(0, matchIndex - 200), matchIndex);
        
        // Coincidencia con archivos que realmente existen en el explorador
        for (const kf of knownFiles) {
          if (kf && kf.includes(".") && precedingText.toLowerCase().includes(kf.toLowerCase())) {
            filename = kf;
            break;
          }
        }

        // Patrón tipo "en main.py:", "código para sniffer.py", "### database.py" con extensión válida
        if (!filename) {
          const preMatch = precedingText.match(/(?:archivo|file|modific(?:ar|aci[oó]n|a)|actualiz(?:ar|a)|c[oó]digo\s+(?:de|para)|#{1,4})\s*[`*"']*([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+)/i);
          if (preMatch && hasValidExt(preMatch[1].trim())) {
            filename = preMatch[1].trim();
          }
        }
      }

      // E. Si el usuario tiene un archivo abierto en Monaco Editor (activeFilePath)
      // y el bloque de código coincide con el lenguaje o es un bloque SEARCH/REPLACE
      if (!filename && activeFilePath) {
        const activeExt = activeFilePath.split(".").pop().toLowerCase();
        const cleanLang = rawHeader.toLowerCase();
        const matchesLang = (cleanLang.includes("py") && activeExt === "py") ||
                            (cleanLang.includes("js") && (activeExt === "js" || activeExt === "ts")) ||
                            (cleanLang.includes("html") && activeExt === "html") ||
                            (cleanLang.includes("css") && activeExt === "css") ||
                            (cleanLang.includes("json") && activeExt === "json") ||
                            (isPatchBlock && !cleanLang);
        if (matchesLang) {
          filename = activeFilePath;
        }
      }

      // F. Fallback solo cuando el proyecto está vacío (creación de app nueva desde cero), sin inventar module_1.py ni code_1.txt
      if (!filename && knownFiles.length === 0) {
        const cleanHeader = rawHeader.toLowerCase();
        if (cleanHeader.includes("python") || cleanHeader.includes("py")) {
          if (!files.some(f => f.path === "main.py")) filename = "main.py";
        } else if (cleanHeader.includes("html") || content.includes("<!DOCTYPE") || content.includes("<html")) {
          if (!files.some(f => f.path === "index.html")) filename = "index.html";
        } else if (cleanHeader.includes("css")) {
          if (!files.some(f => f.path === "style.css")) filename = "style.css";
        } else if (cleanHeader.includes("javascript") || cleanHeader.includes("js")) {
          if (!files.some(f => f.path === "app.js")) filename = "app.js";
        }
      }

      if (filename && hasValidExt(filename) && !files.some(f => f.path === filename && f.content === content)) {
        // Evitar que un bloque inferido sin file: sobrescriba un parche o archivo explícito en el mismo mensaje
        const alreadyTargeted = files.find(f => f.path === filename);
        if (alreadyTargeted && !isExplicitFile && !isPatchBlock) {
          continue;
        }
        files.push({ path: filename, content: content, explicit: isExplicitFile, isPatch: isPatchBlock });
      }
    }

    return files;
  }

  function addManualSaveButton(bubbleContainer, text) {
    if (!text.includes("```")) return;
    if (bubbleContainer.querySelector(".btn-sync-all-files")) return;

    const detected = parseCodeBlocks(text);
    if (detected.length === 0) return;

    const fileNamesStr = detected.map(f => f.path).join(", ");
    const btn = document.createElement("button");
    btn.className = "btn-sync-all-files";
    btn.innerHTML = `<i class="fa-solid fa-bolt"></i> ⚡ Reemplazar y Guardar en Proyecto (${fileNamesStr})`;
    btn.addEventListener("click", async () => {
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Reemplazando archivos en disco...';
      await extractAndSaveAgentFiles(text, bubbleContainer);
      btn.innerHTML = '<i class="fa-solid fa-check"></i> ¡Archivos actualizados en disco!';
      setTimeout(() => {
        btn.remove();
      }, 3500);
    });
    bubbleContainer.appendChild(btn);
  }

  function appendAgentMsg(role, content, imgSrc = null) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-msg ${role}`;

    let imgHtml = "";
    if (imgSrc) {
      imgHtml = `<div style="margin-bottom:8px;"><img src="${imgSrc}" style="max-width:240px; border-radius:4px; border:1px solid #333; display:block;"></div>`;
    }

    const icon = role === "user" ? "fa-user" : "fa-robot";
    msgDiv.innerHTML = `
      <div class="msg-avatar"><i class="fa-solid ${icon}"></i></div>
      <div class="msg-bubble">
        ${imgHtml}
        <div class="msg-bubble-content">${marked.parse(content)}</div>
      </div>
    `;

    agentMessages.appendChild(msgDiv);
    agentMessages.scrollTop = agentMessages.scrollHeight;

    return {
      wrapper: msgDiv,
      bubble: msgDiv.querySelector(".msg-bubble-content")
    };
  }

  btnClearAgentChat.addEventListener("click", () => {
    if (confirm("¿Reiniciar la conversación del agente?")) {
      conversationHistory = [];
      agentMessages.innerHTML = `
        <div class="agent-welcome">
          <div class="agent-avatar-welcome"><i class="fa-solid fa-robot"></i></div>
          <h4>Conversación reiniciada</h4>
          <p>¿Qué aplicación o código deseas que construya ahora?</p>
        </div>
      `;
    }
  });

  // 6. TELEMETRÍA Y CONTROL DE HARDWARE (RTX 4050)
  async function updateTelemetry() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();

      if (data.gpu && data.gpu.has_gpu) {
        const totalGb = (data.gpu.total_mb / 1024).toFixed(1);
        const usedGb = (data.gpu.used_mb / 1024).toFixed(1);
        const pct = Math.round((data.gpu.used_mb / data.gpu.total_mb) * 100);

        vramText.textContent = `${usedGb} / ${totalGb} GB`;
        vramPctText.textContent = `${pct}%`;
        vramFill.style.width = `${pct}%`;
        statusVramText.textContent = `RTX 4050 (${usedGb}/${totalGb} GB)`;
      }

      if (data.system) {
        ramText.textContent = `${data.system.ram_used_gb} / ${data.system.ram_total_gb} GB`;
        ramFill.style.width = `${data.system.ram_pct}%`;
      }

      if (data.model_loaded) {
        btnLoadModel.classList.add("hidden");
        btnUnloadModel.classList.remove("hidden");
      } else {
        btnLoadModel.classList.remove("hidden");
        btnUnloadModel.classList.add("hidden");
      }
    } catch (e) {}
  }

  async function loadModelsList() {
    try {
      const res = await fetch("/api/models/list");
      const data = await res.json();

      modelSelect.innerHTML = "";
      mmprojSelect.innerHTML = "";

      if (data.models && data.models.length > 0) {
        data.models.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m.path;
          opt.textContent = `${m.name} (${m.size_gb} GB)`;
          opt.dataset.mmproj = m.suggested_mmproj || "";
          modelSelect.appendChild(opt);
        });
      }

      if (data.mmprojs && data.mmprojs.length > 0) {
        data.mmprojs.forEach(mm => {
          const opt = document.createElement("option");
          opt.value = mm.path;
          opt.textContent = `${mm.name} (${mm.size_gb} GB)`;
          mmprojSelect.appendChild(opt);
        });
        enableMmproj.checked = true;
      }
    } catch (e) {}
  }

  gpuLayersSlider.addEventListener("input", (e) => {
    gpuLayersBadge.textContent = e.target.value;
  });

  btnLoadModel.addEventListener("click", async () => {
    const selectedModel = modelSelect.value;
    if (!selectedModel) return alert("Selecciona un modelo GGUF");

    btnLoadModel.disabled = true;
    btnLoadModel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Inyectando en VRAM RTX 4050...';

    const payload = {
      model_path: selectedModel,
      n_gpu_layers: parseInt(gpuLayersSlider.value),
      ctx_size: parseInt(ctxSizeSelect.value),
      threads: 6,
      flash_attn: true,
      cache_type_k: "q4_0",
      cache_type_v: "q4_0"
    };

    if (enableMmproj.checked && mmprojSelect.value) {
      payload.mmproj_path = mmprojSelect.value;
    }

    try {
      const res = await fetch("/api/models/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      await updateTelemetry();
      alert("Modelo inyectado con éxito en GPU con soporte multimodal!");
    } catch (e) {
      alert("Error cargando modelo: " + e.message);
    } finally {
      btnLoadModel.disabled = false;
      btnLoadModel.innerHTML = '<i class="fa-solid fa-bolt"></i> Iniciar e Inyectar en GPU';
    }
  });

  btnUnloadModel.addEventListener("click", async () => {
    await fetch("/api/models/unload", { method: "POST" });
    await updateTelemetry();
  });

  btnPurgeVram.addEventListener("click", async () => {
    const res = await fetch("/api/gpu/purge", { method: "POST" });
    const d = await res.json();
    await updateTelemetry();
    alert(d.message);
  });

  // Inicializar
  loadModelsList();
  updateTelemetry();
  setInterval(updateTelemetry, 2500);
});
