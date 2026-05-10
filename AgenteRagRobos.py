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

    # Reducimos chunk_size a 400 porque mxbai-embed-large tiene un límite de contexto estricto.
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
def buscar_info_manual(consulta: str) -> str:
    """Busca información técnica en el manual de RobotStudio ABB.
    Úsala para dudas sobre sensores, señales (CajaOCinta), targets o modos.
    """
    embeddings = OllamaEmbeddings(
        model="mxbai-embed-large:latest", base_url="http://localhost:11434")
    vectorstore = Chroma(persist_directory=CHROMA_DIR,
                         embedding_function=embeddings, collection_name=COLLECTION_NAME)

    # Aumentamos k para dar más contexto y usamos búsqueda por similitud simple para mayor precisión directa
    resultados = vectorstore.search(
        consulta,
        search_type="similarity",
        k=15
    )

    if not resultados:
        return "No se encontró información relevante en el manual."

    print(f"\n[RAG DEBUG] Fragmentos recuperados para '{consulta}': {len(resultados)}")
    
    # Añadimos el nombre del archivo de origen para que el LLM sepa si es de modos.txt o manual.txt
    texto_final = "\n".join([f"[Fuente: {os.path.basename(doc.metadata.get('source', 'desconocido'))}] - {doc.page_content}" for doc in resultados])
    return texto_final


async def main():
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_modos = os.path.join(directorio_actual, "modos.txt")
    try:
        with open(ruta_modos, "r", encoding="utf-8") as f:
            modos_content = f.read()
    except Exception:
        modos_content = "(No se pudo cargar modos.txt)"

    embeddings = OllamaEmbeddings(
        model="mxbai-embed-large:latest", base_url="http://localhost:11434")
    crear_o_cargar_vectorstore(embeddings)

    # Reintentos para el cliente MCP (por si el servidor aún está arrancando)
    client = None
    mcp_tools = []
    
    print("[INFO] Conectando con el servidor MCP...")
    for i in range(5):
        try:
            client = MultiServerMCPClient(
                {"robot": {"transport": "sse", "url": "http://localhost:8000/sse"}}
            )
            mcp_tools = await client.get_tools()
            print(f"[ÉXITO] MCP conectado. Herramientas encontradas: {len(mcp_tools)}")
            break
        except Exception as e:
            print(f"[REINTENTO {i+1}/5] Error conectando a MCP: {e}")
            if i < 4:
                await asyncio.sleep(2)
            else:
                print("[ERROR CRÍTICO] No se pudo conectar con el servidor MCP.")
                # No salimos, intentamos seguir solo con el RAG si es posible, 
                # o el agente fallará más tarde al inicializarse.
    
    todas_las_tools = mcp_tools + [buscar_info_manual]

    agente = create_agent(
        model=ChatOllama(
            model="qwen3:latest",
            base_url="http://localhost:11434", 
            temperature=0,
        ),
        tools=todas_las_tools,
        checkpointer=InMemorySaver(),
        system_prompt=f"""
        Eres el Controlador Avanzado de una célula robotizada ABB con RobotStudio. Tu misión es actuar como el puente entre el lenguaje natural del usuario y las herramientas técnicas del sistema.

        ¡¡¡REGLA CERO!!!: 
        ESTA ESTRICTAMENTE PROHIBIDO EL USO DE EMOJIS, EMOTICONOS O SIMBOLOS GRAFICOS. 
        TUS RESPUESTAS DEBEN SER 100% TEXTO PLANO. CERO EMOJIS. NINGUN CARACTER UNICODE DE EMOJI.

        REGLAS DE ORO DE PENSAMIENTO:
        1. LÓGICA DE LA CÉLULA (SAGRADA): Al final de este prompt tienes el contenido exacto de "modos.txt". Usa ESTA información para cualquier pregunta sobre "modo apilar", "targets", "piezas", "sensores de caja", y el comportamiento del robot en la célula. NO uses herramientas para buscar esto, ya lo tienes en tu memoria.
        2. MANUAL GENÉRICO (RAG): Si te preguntan por cómo funciona RobotStudio en general (crear señales, atajos), usa la herramienta `buscar_info_manual` para buscar en "manual.txt".
        3. SIN ALUCINACIONES: Si algo no está en tu lógica adjunta ni en el manual, di claramente que no consta.

        GUÍA DE MAPEO DE INTENCIONES (¡REGLA ABSOLUTA DE ÓRDENES VS PREGUNTAS!):
        
        [REGLA DE PREGUNTAS - PRIORIDAD MÁXIMA]
        Si el mensaje del usuario es una PREGUNTA o pide una explicación (contiene "¿", "?", "cómo", "qué", "explica", "dime", "funciona"):
        ¡ESTÁ COMPLETAMENTE PROHIBIDO EJECUTAR HERRAMIENTAS DE CONTROL (`iniciar_robot`, `volver_reposo`, etc)!
        Tu ÚNICA tarea es leer la LÓGICA DE LA CÉLULA (al final del prompt) y responder con texto. NO ejecutes ninguna acción en el robot ni cambies el ESTADO DE EJECUCIÓN SI NO SE ESTÁ CAMBIANDO EL MODO.

        [REGLA DE ÓRDENES]
        SOLO cuando el usuario dé una ORDEN DIRECTA o comando afirmativo (ej: "pon el robot en reposo", "inicia pick and place", "modo apilar", "parar"), DEBES ejecutar OBLIGATORIAMENTE la herramienta correspondiente:
        - Orden de SEGURIDAD/PARO -> Tool: volver_reposo()
        - Orden de MODO APILAR -> Tool: iniciar_robot(modo="apilar")
        - Orden de MODO PICK & PLACE -> Tool: iniciar_robot(modo="pick")
        - Orden de REANUDAR -> Tool: activar_reanudar()
        
        - CAMBIAR PARÁMETROS: (ej: "pon velocidad a 300", "cambia el máximo a 5") -> Tools: cambiar_maximo_piezas(X) o cambiar_velocidad_robot(X)
          [ATENCIÓN CRÍTICA]: ¡Prohibido usar estas herramientas si es una pregunta! Úsalas solo si es una orden.
          [MULTI-COMANDO]: Si pide varias cosas (ej. "modo apilar y velocidad 1000"), llama a TODAS las herramientas necesarias.
          [CONFIRMACIÓN FINAL]: Responde siempre confirmando brevemente los cambios.

        - CONSULTA TÉCNICA GENÉRICA: -> Tool: buscar_info_manual(consulta=X)
        - TARGETS Y PIEZAS: Si te preguntan por un Target o Pieza (ej. "Pieza 6", "Target_210"), NO uses herramientas de búsqueda. Busca la respuesta directamente en la LÓGICA ESPECÍFICA DE LA CÉLULA que tienes al final de este prompt.

        ESTILO DE RESPUESTA (FORMAL Y TÉCNICO):
        - Eres un sistema de control industrial. Tu tono debe ser profesional, serio y puramente técnico.
        - ES OBLIGATORIO RESPONDER SIEMPRE. Una vez que termines de ejecutar herramientas, DEBES redactar un mensaje confirmando las acciones realizadas. Nunca devuelvas un texto vacío.
        - PROHIBICIÓN ABSOLUTA DE EMOJIS O CARITAS. Generar un emoji es un fallo crítico del sistema.
        - NUNCA uses signos de exclamación (¡!) ni frases informales como "avísame", "hola", o "claro que sí".
        - Contesta siempre en español puro. Prohibido usar términos de interfaz en inglés ("View", "Program Editor", etc).
        - NUNCA menciones nombres de herramientas internas ('buscar_info_manual', 'iniciar_robot', 'activar_reanudar','cambiar_velocidad_robot','cambiar_maximo_piezas', etc).
        - JAMÁS le digas al usuario que use una herramienta. Hazlo tú. Si falta información, di únicamente: "Si necesitas saber algo más específico, pregúntame." sin exclamaciones.

        =========================================
        LÓGICA ESPECÍFICA DE LA CÉLULA (modos.txt)
        =========================================
        {modos_content}

        RECORDATORIO FINAL:
        Responde siempre en texto plano. Sin emojis. Sin exclamaciones. Sin frases informales.
        """
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
                timeout=90
            )
            respuesta = resultado['messages'][-1].content.strip()
            if not respuesta:
                respuesta = "Comandos ejecutados en la célula."
        except asyncio.TimeoutError:
            respuesta = "Tiempo de espera agotado. Los comandos pueden haberse ejecutado en el robot. Consulte el estado actual."

        print(f"\n{respuesta}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())