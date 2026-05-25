import asyncio
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langchain.tools import tool
from langchain_community.document_loaders import TextLoader

# --- CONFIGURACIÓN RAG ---
CHROMA_DIR = "./chroma_db_robotstudio"
COLLECTION_NAME = "manual_robotstudio"
ARCHIVOS_RAG = ["manual.txt", "modos.txt"]


def cargar_y_dividir_documentos(rutas_archivos: list):
    """Carga archivos usando rutas absolutas y divide en fragmentos más grandes para no cortar targets."""
    todos_los_documentos = []
    directorio_actual = os.path.dirname(os.path.abspath(__file__))

    for nombre_archivo in rutas_archivos:
        ruta_absoluta = os.path.join(directorio_actual, nombre_archivo)

        if os.path.exists(ruta_absoluta):
            print(f"[ÉXITO] Cargando información de: {ruta_absoluta}")
            loader = TextLoader(ruta_absoluta, encoding='utf-8')
            todos_los_documentos.extend(loader.load())
        else:
            print(f"[ERROR] Archivo NO encontrado en: {ruta_absoluta}")

    if not todos_los_documentos:
        print("[ALERTA] La base de datos estará vacía.")
        return []

    # Chunk_size a 400 caracteres lo puse porque "mxbai-embed-large" prefiere textos cortos para ser más preciso
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=50,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    chunks = splitter.split_documents(todos_los_documentos)
    print(f"[INFO] RAG generado con {len(chunks)} fragmentos.")
    return chunks


def crear_o_cargar_vectorstore(embeddings):
    if not os.path.exists(CHROMA_DIR):
        chunks = cargar_y_dividir_documentos(ARCHIVOS_RAG)
        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=CHROMA_DIR,
            collection_name=COLLECTION_NAME
        )
    else:
        vectorstore = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME
        )
    return vectorstore


@tool
def buscar_modos_celula(consulta: str) -> str:
    """Busca información sobre los modos de operación de la célula robotizada ABB.
    USA ESTA HERRAMIENTA para responder preguntas sobre:
    - Modos de operación: pick and place, apilar, desapilar, reposo.
    - Targets, sensores, señales (CajaOCinta, interuptorEstado, Alerta, etc.).
    - Parámetros: velocidad, maximoPiezas, contadorPiezas.
    - Comportamiento del robot en la célula: qué hace en cada modo, destinos, lógica.
    """
    embeddings = OllamaEmbeddings(
        model="mxbai-embed-large:latest", base_url="http://localhost:11434")
    vectorstore = Chroma(persist_directory=CHROMA_DIR,
                         embedding_function=embeddings, collection_name=COLLECTION_NAME)

    resultados = vectorstore.search(
        consulta,
        search_type="similarity",
        k=8
    )

    if not resultados:
        return "No se encontró información sobre ese modo o parámetro de la célula."

    # Filtramos preferentemente los fragmentos de modos.txt
    modos_results = [doc for doc in resultados if "modos" in doc.metadata.get('source', '').lower()]
    otros_results = [doc for doc in resultados if "modos" not in doc.metadata.get('source', '').lower()]
    ordenados = modos_results + otros_results

    print(f"\n[RAG DEBUG] buscar_modos_celula: {len(ordenados)} fragmentos para '{consulta}'")
    texto_final = "\n".join(
        [f"[Fuente: {os.path.basename(doc.metadata.get('source', 'desconocido'))}] {doc.page_content}" for doc in ordenados[:6]])
    return texto_final


@tool
def buscar_info_manual(consulta: str) -> str:
    """Busca información técnica genérica en el manual de RobotStudio ABB.
    USA ESTA HERRAMIENTA para responder preguntas sobre:
    - Cómo usar RobotStudio: crear señales, workobjects, configurar el controlador.
    - Conceptos generales de ABB: RAPID, FlexPendant, módulos, tareas.
    - Procedimientos de programación o configuración del entorno de simulación.
    NO la uses para preguntas sobre los modos de la célula (usa buscar_modos_celula).
    """
    embeddings = OllamaEmbeddings(
        model="mxbai-embed-large:latest", base_url="http://localhost:11434")
    vectorstore = Chroma(persist_directory=CHROMA_DIR,
                         embedding_function=embeddings, collection_name=COLLECTION_NAME)

    resultados = vectorstore.search(
        consulta,
        search_type="similarity",
        k=8
    )

    if not resultados:
        return "No se encontró información relevante en el manual."

    # Filtramos preferentemente los fragmentos de manual.txt
    manual_results = [doc for doc in resultados if "manual" in doc.metadata.get('source', '').lower()]
    otros_results = [doc for doc in resultados if "manual" not in doc.metadata.get('source', '').lower()]
    ordenados = manual_results + otros_results

    print(f"\n[RAG DEBUG] buscar_info_manual: {len(ordenados)} fragmentos para '{consulta}'")
    texto_final = "\n".join(
        [f"[Fuente: {os.path.basename(doc.metadata.get('source', 'desconocido'))}] {doc.page_content}" for doc in ordenados[:6]])
    return texto_final


async def main():
    # Se inicializa el vectorstore RAG (modos.txt + manual.txt indexados en Chroma)
    embeddings = OllamaEmbeddings(
        model="mxbai-embed-large:latest", base_url="http://localhost:11434")
    crear_o_cargar_vectorstore(embeddings)

    # Reintentos para el cliente MCP (por si el servidor aún está arrancando)
    client = None
    mcp_tools = []

    # protocolo de comunicación entre robot y agente
    print("[INFO] Conectando con el servidor MCP...")
    for i in range(5):
        try:
            client = MultiServerMCPClient(
                {"robot": {"transport": "sse", "url": "http://localhost:8000/sse"}}
            )
            mcp_tools = await client.get_tools()
            print(
                f"[ÉXITO] MCP conectado. Herramientas encontradas: {len(mcp_tools)}")
            break
        except Exception as e:
            print(f"[REINTENTO {i+1}/5] Error conectando a MCP: {e}")
            if i < 4:
                await asyncio.sleep(2)
            else:
                print("[ERROR CRÍTICO] No se pudo conectar con el servidor MCP.")
                # No salimos, intentamos seguir solo con el RAG si es posible,
                # o el agente fallará más tarde al inicializarse.

    todas_las_tools = mcp_tools + [buscar_modos_celula, buscar_info_manual]

    SYSTEM_PROMPT = """
Eres el sistema de control de una celula robotizada ABB con RobotStudio. Recibes ordenes del operario y las ejecutas usando las herramientas disponibles.

== REGLA ABSOLUTA DE FORMATO ==
TEXTO PLANO UNICAMENTE. Prohibido emojis, exclamaciones (!), emoticones o cualquier simbolo grafico.
Prohibido mencionar nombres de herramientas internas al usuario.
Responde siempre en espanol.

== CLASIFICACION DE MENSAJES ==

TIPO A - ORDEN DE CONTROL (actua de inmediato con la herramienta correcta):
- "pick and place" | "modo pick" | "iniciar pick" | "modo clasificacion" -> llama a iniciar_robot(modo="pick")
- "apilar" | "modo apilar" | "modo apilado" | "iniciar apilar" -> llama a iniciar_robot(modo="apilar")
- "reposo" | "parar" | "stop" | "detener" | "paro" -> llama a volver_reposo()
- "reanudar" | "continuar" | "seguir" -> llama a activar_reanudar()
- "velocidad a X" | "pon velocidad X" | "cambia velocidad a X" -> llama a cambiar_velocidad_robot(X)
- "maximo X" | "maximo piezas X" | "cambia maximo a X" -> llama a cambiar_maximo_piezas(X)

TIPO B - CONSULTA SOBRE LA CELULA (usa buscar_modos_celula):
- Preguntas sobre que hace cada modo, targets, sensores, senales, parametros de la celula.
- Ejemplos: "que hace el modo apilar", "donde va la caja naranja", "que es Target_90".

TIPO C - CONSULTA TECNICA DE ROBOTSTUDIO (usa buscar_info_manual):
- Preguntas sobre como usar RobotStudio, RAPID, configuracion del entorno.
- Ejemplos: "como creo una senal", "que es un workobject".

== REGLA CRITICA: ORDENES DIRECTAS ==
Si el mensaje es un nombre de modo o accion directa SIN signos de pregunta, es SIEMPRE una ORDEN.
Ejemplos de ordenes directas: "pick and place", "apilar", "reposo", "parar", "reanudar".
Antes de responder con texto, ejecuta SIEMPRE la herramienta correspondiente.

== REGLA CRITICA: PREGUNTAS ==
Si el mensaje contiene "?", "como", "que", "explica", "dime" -> es una CONSULTA.
En consultas: NUNCA ejecutes herramientas de control del robot (iniciar_robot, volver_reposo, activar_reanudar).
Usa solo las herramientas RAG (buscar_modos_celula o buscar_info_manual) para obtener informacion.

== FORMATO DE RESPUESTA ==
- Tras ejecutar una herramienta de control: confirma brevemente la accion realizada (1-2 lineas).
- Tras consultar el RAG: responde de forma tecnica y concisa con la informacion obtenida.
- Si no encuentras informacion: indica que no consta en el sistema.
- NUNCA devuelvas una respuesta vacia. Si no hay nada que decir, confirma el estado actual.
"""

    agente = create_agent(
        model=ChatOllama(
            model="qwen3:latest",
            base_url="http://localhost:11434",
            temperature=0,
            num_ctx=8192,
        ),
        tools=todas_las_tools,
        checkpointer=InMemorySaver(),
        system_prompt=SYSTEM_PROMPT
    )

    config = {"configurable": {"thread_id": "sesion_robot_01"}}

    while True:
        user_input = input("> ")
        if user_input.lower() in ["end", "salir"]:
            break

        try:
            resultado = await asyncio.wait_for(
                agente.ainvoke(
                    {"messages": [HumanMessage(user_input)]},
                    config=config),
                timeout=240
            )
            respuesta = resultado['messages'][-1].content.strip()
            if not respuesta:
                respuesta = "Comando ejecutado en la celula."
        except asyncio.TimeoutError:
            respuesta = "Tiempo de espera superado. Si se envio una orden de control, el robot puede haberla ejecutado. Consulte el estado actual del sistema."

        print(f"\n{respuesta}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
