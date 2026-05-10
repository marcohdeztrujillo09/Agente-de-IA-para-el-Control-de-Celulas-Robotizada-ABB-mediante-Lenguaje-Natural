# RobotStudio Command Center — Agente IA para Control de Célula Robotizada ABB

## Descripción del problema

Las células robotizadas industriales se operan habitualmente mediante interfaces físicas (teach pendant, botoneras) o software propietario complejo. Esto obliga al operario a conocer en profundidad la programación RAPID y la interfaz de RobotStudio para realizar tareas tan simples como cambiar la velocidad, el modo de operación o el número máximo de piezas a apilar.

Este proyecto resuelve ese problema integrando un agente de IA conversacional que actúa como puente entre el lenguaje natural del operario y el controlador físico del robot ABB. El operario puede escribir órdenes como "pon el robot a apilar con un máximo de 5 cajas a 800 mm/s" y el sistema las ejecuta automáticamente sobre el robot real.

---

## Descripción del sistema

RobotStudio Command Center es una aplicación web que permite controlar una célula robotizada ABB mediante lenguaje natural. El sistema combina un agente LangChain con herramientas MCP para comunicarse con el controlador del robot, un RAG para responder preguntas técnicas sobre el sistema, y una interfaz web construida en React con una API FastAPI como backend.

La célula robotizada consta de:
- Un brazo robótico ABB con ventosa de succión
- Una cinta transportadora de entrada
- Una zona de apilado
- Dos mesas de descarga (caja pequeña a la izquierda, caja grande a la derecha)

---

## Cómo se integra la IA en el sistema

El agente de IA es el núcleo de la aplicación. No es un chat decorativo: cada mensaje del usuario es procesado por el agente, que decide qué herramientas ejecutar y en qué orden, pudiendo encadenar varias acciones en una sola orden.

El flujo es el siguiente:

```
Usuario (web) → API FastAPI → Agente LangChain (Ollama) → Tools MCP / RAG → Robot ABB
```

1. El usuario escribe un comando en la interfaz web React.
2. La petición llega al backend FastAPI, que la reenvía al subproceso del agente.
3. El agente (modelo `qwen3` via Ollama) razona sobre la intención del usuario.
4. Según la intención detectada, invoca las herramientas necesarias (MCP y/o RAG).
5. Las herramientas MCP envían señales HTTP directamente a la API REST del controlador ABB.
6. El agente devuelve una respuesta en texto plano confirmando las acciones ejecutadas.
7. La respuesta se muestra al usuario en la interfaz web.

---

## Arquitectura general

```
proyecto/
├── AgenteRagRobos.py       # Agente LangChain: lógica, RAG y tools
├── robostudioMCP.py        # Servidor MCP: herramientas de control del robot
├── web/
│   ├── main.py             # API FastAPI: puente entre frontend y agente
│   └── static/             # Frontend React compilado
│       ├── index.html
│       └── assets/
├── modos.txt               # Documento RAG: lógica de modos de la célula
├── manual.txt              # Documento RAG: manual genérico de RobotStudio
├── chroma_db_robotstudio/  # Base de datos vectorial persistente (Chroma)
├── requirements.txt
└── .env.example
```

### Componentes principales

**Agente LangChain (`AgenteRagRobos.py`)**
- Modelo LLM: `qwen3` via Ollama (local)
- Modelo de embeddings: `mxbai-embed-large` via Ollama
- Memoria de conversación: `InMemorySaver` (persistencia de sesión)
- Razona sobre la intención del usuario y decide qué herramientas invocar
- Puede encadenar múltiples herramientas en una sola orden

**Servidor MCP (`robostudioMCP.py`)**

Expone las siguientes herramientas al agente:

| Herramienta | Acción sobre el robot |
|---|---|
| `iniciar_robot(modo)` | Activa marcha y selecciona modo (apilar / pick and place) |
| `activar_reanudar()` | Pulsa el botón de reanudar tras completar la pila |
| `volver_reposo()` | Envía el robot a posición de reposo segura |
| `cambiar_maximo_piezas(n)` | Modifica la variable RAPID `maximoPiezas` (1-8) |
| `cambiar_velocidad_robot(v)` | Modifica la variable RAPID `vel` en mm/s (10-1000) |

**RAG (Chroma + mxbai-embed-large)**
- Dos documentos indexados: `modos.txt` (lógica de la célula) y `manual.txt` (manual genérico)
- Chunks de 400 tokens con solapamiento de 50
- Búsqueda por similitud con k=15 fragmentos
- La herramienta `buscar_info_manual` es invocada por el agente cuando detecta una consulta técnica genérica

**API FastAPI (`web/main.py`)**
- Gestiona el ciclo de vida del subproceso del agente
- Endpoint `POST /api/chat` recibe el mensaje y devuelve la respuesta
- Sirve el frontend React como archivos estáticos

**Frontend React (`web/static/`)**
- Interfaz de chat en tiempo real
- Panel de telemetría: velocidad nominal, capacidad máxima, estado de ejecución
- Botones de control directo: Modo Apilado, Pick and Place, Reanudar, Paro/Reposo

---

## Tecnologías utilizadas

| Tecnología | Uso |
|---|---|
| Python 3.11+ | Backend y agente |
| LangChain / LangGraph | Agente con tools y memoria |
| Ollama | Ejecución local de LLMs (`qwen3`, `mxbai-embed-large`) |
| FastMCP | Servidor MCP de herramientas del robot |
| ChromaDB | Base de datos vectorial para el RAG |
| FastAPI | API REST y servidor del frontend |
| React | Interfaz web |
| RobotStudio ABB | Simulador del robot (API REST integrada) |

---

## Requisitos previos

- Python 3.11 o superior
- Node.js 18+ (solo si se quiere recompilar el frontend)
- [Ollama](https://ollama.com/) instalado y en ejecución
- RobotStudio ABB con la estación configurada y el servidor web del controlador activo en `127.0.0.1`

### Modelos Ollama necesarios

```bash
ollama pull qwen3
ollama pull mxbai-embed-large
```

---

## Instalación y ejecución en local

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/robotstudio-command-center.git
cd robotstudio-command-center
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

### 4. Arrancar el servidor MCP

```bash
python robostudioMCP.py
```

El servidor MCP quedará escuchando en `http://localhost:8000/sse`.

### 5. Arrancar la API web (lanza el agente automáticamente)

```bash
cd web
uvicorn main:app --reload --port 8080
```

La API FastAPI lanzará automáticamente el agente como subproceso al arrancar.

### 6. Abrir la interfaz web

Navegar a `http://localhost:8080` en el navegador.

> **Nota:** RobotStudio debe estar abierto con la estación cargada y el controlador en modo automático antes de arrancar el sistema.

---

## Ejemplos de uso

```
> Pon el robot en modo apilar con un máximo de 5 cajas y velocidad 800
> Para el robot
> ¿Cuántas cajas puede apilar como máximo?
> Reanuda la operación
> ¿Qué hace el modo pick and place?
> Cambia la velocidad a 300 mm/s
```

---

## Mejoras futuras

- **Multiagente:** separar un agente router de agentes especializados (uno para control, otro para consultas RAG), lo que permitiría usar un modelo más ligero para las consultas y reservar el modelo principal para el razonamiento de control.
- **TTS/STT:** integrar reconocimiento de voz (Whisper) y síntesis de voz para operar el robot con comandos de audio, útil en entornos industriales con las manos ocupadas.
- **Telemetría en tiempo real:** conectar el panel de telemetría directamente a la API REST del controlador para mostrar el estado real del robot en lugar de valores estimados.
- **Persistencia de sesión:** usar una base de datos (SQLite o similar) para guardar el historial de comandos y poder auditar las operaciones realizadas sobre el robot.
- **Autenticación:** añadir un sistema de login para controlar quién puede enviar comandos al robot.
- **Despliegue dockerizado:** empaquetar el sistema completo en contenedores Docker para facilitar la puesta en marcha sin depender del entorno local.
