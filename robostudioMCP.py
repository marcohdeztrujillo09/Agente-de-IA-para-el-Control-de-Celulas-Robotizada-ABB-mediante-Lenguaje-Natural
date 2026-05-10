from mcp.server.fastmcp import FastMCP
import requests
from requests.auth import HTTPDigestAuth
import time

# -----------------------------
# CONFIGURACIÓN ROBOT
# -----------------------------
ROBOT_IP = "127.0.0.1"
USERNAME = "Default User"
PASSWORD = "robotics"

mcp = FastMCP("robotstudio-mcp")


# FUNCIÓN BASE

def set_senal(nombre_senal: str, valor: int):
    url = f"http://{ROBOT_IP}/rw/iosystem/signals/{nombre_senal}?action=set"

    try:
        r = requests.post(
            url,
            data={"lvalue": str(valor)},
            auth=HTTPDigestAuth(USERNAME, PASSWORD),
            timeout=5
        )

        if r.status_code == 204:
            return f"OK → {nombre_senal} = {valor}"
        else:
            return f"ERROR → {r.status_code} {r.text}"

    except Exception as e:
        return f"ERROR conexión → {str(e)}"


@mcp.tool()
def iniciar_robot(modo: str):
    """
    Control simple del robot:
    - apilar
    - pick (o pick and place)
    """

    # Activar marcha
    set_senal("marca_marcha", 1)

    # Selección de modo
    if modo == "apilar":
        set_senal("interuptorEstado", 1)

    elif modo in ["pick", "pick and place"]:
        set_senal("interuptorEstado", 0)

    else:
        return "ERROR → modo inválido (usa apilar, pick o pick and place)"

    return f"OK → robot en modo {modo}"


@mcp.tool()
def activar_reanudar():
    return set_senal("PulsadorReanudar", 1)


@mcp.tool()
def volver_reposo():
    """
    Fuerza al robot a ir a posición de reposo y esperar marcha
    """
    set_senal("marca_marcha", 0)
    time.sleep(0.1)
    set_senal("modo_reposo", 1)
    return "OK → robot enviado a reposo"


@mcp.tool()
def cambiar_maximo_piezas(cantidad: int):
    """
    Modifica la variable PERS maximoPiezas en el código RAPID.
    Determina cuántas cajas se van a apilar como máximo.
    """
    # Aseguramos que la cantidad esté dentro de los límites del robot (ej. entre 1 y 8)
    if cantidad < 1 or cantidad > 8:
        return "Error: La cantidad de piezas debe estar entre 1 y 8."

    # URL directa a la variable en RAPID (Tarea: T_ROB1, Módulo: Module1, Variable: maximoPiezas)
    url_var = f"http://{ROBOT_IP}/rw/rapid/symbol/data/RAPID/T_ROB1/Module1/maximoPiezas?action=set"

    # Enviamos el nuevo valor
    payload = {"value": str(cantidad)}

    try:
        res = requests.post(url_var, data=payload,
                            auth=HTTPDigestAuth(USERNAME, PASSWORD),
                            timeout=5)
        if res.status_code < 300:
            return f"Éxito: El máximo de cajas a apilar se ha cambiado a {cantidad}."
        else:
            return f"Fallo al cambiar la variable en el robot. Código HTTP: {res.status_code}"
    except Exception as e:
        return f"Error de conexión: {str(e)}"


@mcp.tool()
def cambiar_velocidad_robot(valor: int):
    """
    Modifica la variable PERS vel en RAPID. 
    Ajusta la velocidad de movimiento del robot (TCP).
    """
    # Validamos un rango seguro (ejemplo: de 10 a 1000 mm/s)
    if valor < 10 or valor > 1000:
        return "Error: La velocidad debe estar entre 10 y 1000 mm/s por seguridad."

    # URL a la variable 'vel'
    url_vel = f"http://{ROBOT_IP}/rw/rapid/symbol/data/RAPID/T_ROB1/Module1/vel?action=set"

    payload = {"value": str(valor)}

    try:
        res = requests.post(url_vel, data=payload,
                            auth=HTTPDigestAuth(USERNAME, PASSWORD),
                            timeout=5)
        if res.status_code < 300:
            return f"Velocidad actualizada: El robot ahora se moverá a {valor} mm/s."
        else:
            return f"Error al comunicar con el controlador: {res.status_code}"
    except Exception as e:
        return f"Error de red: {str(e)}"


if __name__ == "__main__":
    print("Servidor MCP funcionando (modo simple)")
    mcp.run(transport="sse")
