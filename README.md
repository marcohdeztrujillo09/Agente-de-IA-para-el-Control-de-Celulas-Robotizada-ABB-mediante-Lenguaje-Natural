# RobotStudio Command Center

**Control de célula robotizada ABB mediante lenguaje natural e inteligencia artificial**

Este proyecto integra un agente de IA conversacional sobre una célula robotizada ABB real simulada en RobotStudio, permitiendo al operario controlarla escribiendo órdenes en lenguaje natural. En lugar de interactuar con interfaces propietarias o programar en RAPID, el usuario puede escribir frases como *"pon el robot a apilar con un máximo de 5 cajas a 800 mm/s"* y el sistema las ejecuta automáticamente sobre el controlador del robot.

---

## Contexto del proyecto

Las células robotizadas industriales se operan habitualmente a través de teach pendants o software propietario que exige formación específica. Este proyecto explora cómo un agente de IA puede actuar como capa de abstracción entre el lenguaje humano y el sistema de control, reduciendo la barrera de operación y abriendo la puerta a interfaces más accesibles en entornos industriales.

La célula robotizada sobre la que opera el sistema consta de un brazo ABB con ventosa de succión, una cinta transportadora de entrada, una zona de apilado y dos mesas de descarga. El robot puede clasificar cajas por tamaño, apilar lotes y desapilarlos de forma autónoma.

---

## Arquitectura del sistema

```
Usuario (web) → API FastAPI → Agente LangChain (Ollama) → Tools MCP / RAG → Robot ABB
```

El sistema se divide en cuatro capas bien diferenciadas:

**Frontend React** — Interfaz web con panel de telemetría (velocidad, capacidad, estado) y botones de control directo, además de un chat para enviar comandos en lenguaje natural.

**API FastAPI (`web/main.py`)** — Actúa como puente entre el frontend y el agente. Gestiona el ciclo de vida del agente como subproceso persistente y expone el endpoint `POST /api/chat`.

**Agente LangChain (`AgenteRagRobos.py`)** — Núcleo del sistema. Razona sobre la intención del usuario y decide qué herramientas invocar, pudiendo encadenar varias acciones en una sola orden. Utiliza el modelo `qwen3` ejecutado localmente con Ollama y mantiene memoria de conversación entre turnos.

**Servidor MCP (`RobotStudio_PackAndGo.rspag`)** — Expone las herramientas de control del robot al agente mediante el protocolo MCP sobre SSE. Se comunica con el controlador ABB a través de su API REST integrada.

```
proyecto/
├── AgenteRagRobos.py            # Agente LangChain: lógica, RAG y tools
├── robostudioMCP.py             # Servidor MCP: herramientas de control del robot
├── web/
│   ├── main.py                  # API FastAPI: puente entre frontend y agente
│   └── static/                  # Frontend React compilado
│       ├── index.html
│       └── assets/
├── modos.txt                    # Documento RAG: lógica de modos de la célula
├── manual.txt                   # Documento RAG: manual genérico de RobotStudio
├── RobotStudio_PackAndGo.rspag  # Estación RobotStudio exportada (Pack & Go)
├── requirements.txt
```

---

## Componentes de IA

**Herramientas MCP disponibles para el agente:**

| Herramienta | Acción sobre el robot |
|---|---|
| `iniciar_robot(modo)` | Activa marcha y selecciona modo (apilar / pick and place) |
| `activar_reanudar()` | Pulsa el botón de reanudar tras completar la pila |
| `volver_reposo()` | Envía el robot a posición de reposo segura |
| `cambiar_maximo_piezas(n)` | Modifica la variable RAPID `maximoPiezas` (1-8) |
| `cambiar_velocidad_robot(v)` | Modifica la variable RAPID `vel` en mm/s (10-1000) |

**RAG (Retrieval-Augmented Generation):**

El agente dispone de una base de conocimiento vectorial construida sobre dos documentos: `modos.txt`, que describe la lógica operativa de la célula, y `manual.txt`, con documentación genérica de RobotStudio. La búsqueda se realiza por similitud semántica usando el modelo de embeddings `mxbai-embed-large` y ChromaDB como base de datos vectorial. La lógica crítica de la célula se inyecta directamente en el system prompt para garantizar precisión absoluta en las respuestas operativas.

---

## Tecnologías utilizadas

| Tecnología | Uso |
|---|---|
| Python 3.11+ | Backend y agente |
| LangChain / LangGraph | Agente con tools y memoria de conversación |
| Ollama | Ejecución local de LLMs (`qwen3`, `mxbai-embed-large`) |
| FastMCP | Servidor MCP de herramientas del robot |
| ChromaDB | Base de datos vectorial para el RAG |
| FastAPI | API REST y servidor del frontend |
| React | Interfaz web |
| RobotStudio ABB | Simulador y controlador del robot (API REST integrada) |

---

## Requisitos previos

- Python 3.11 o superior
- [Ollama](https://ollama.com/) instalado y en ejecución
- RobotStudio ABB con la estación cargada desde `RobotStudio_PackAndGo.rspag` y el servidor web del controlador activo en `127.0.0.1`

### Modelos Ollama necesarios

```bash
ollama pull qwen3
ollama pull mxbai-embed-large
```

---

## Instalación y ejecución en local

### 1. Clonar el repositorio

```bash
git clone https://github.com/marcohdeztrujillo09/Agente-de-IA-con-RobotStudio.git
cd Agente-de-IA-con-RobotStudio
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con los valores correspondientes (IP del robot, credenciales, etc.).

### 4. Cargar la estación en RobotStudio

Abrir RobotStudio, ir a **Archivo → Abrir → Pack & Go** y seleccionar `RobotStudio_PackAndGo.rspag`. Una vez cargada, asegurarse de que el controlador está en modo automático y el servidor web está activo.

### 5. Arrancar el servidor MCP

```bash
python robostudioMCP.py
```

El servidor quedará escuchando en `http://localhost:8000/sse`.

### 6. Arrancar la API web

```bash
cd web
uvicorn main:app --reload --port 8080
```

La API lanzará automáticamente el agente al arrancar.

### 7. Abrir la interfaz web

Navegar a `http://localhost:8080` en el navegador.

---

## Demostración

```
> Pon el robot en modo apilar con un máximo de 5 cajas a 800 mm/s
> Para el robot
> ¿Qué hace el modo pick and place?
> Reanuda la operación
```

---
