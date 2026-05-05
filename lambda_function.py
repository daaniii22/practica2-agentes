"""
Handler principal de la skill de Alexa para consulta de datos de películas.

Flujo
--------------------
1. Alexa invoca esta función con un JSON que contiene el intent y el slot
   con el nombre de la película que el usuario ha pedido.
2. Antes de lanzar el scrapper, consultamos DynamoDB. Si la película ya
   está cacheada, devolvemos el resultado.
3. Si no está en caché, ejecutamos el scrapper, guardamos el resultado
   en DynamoDB y devolvemos la respuesta a Alexa.

Intents
--------------------
- ConsultarDatoIntent: el usuario pregunta por un campo concreto
  (nota, votos, sinopsis, director o duración) de una película.
- ConsultarTodoIntent: el usuario pide toda la información disponible
  sobre una película de golpe.

Caché
--------------------
Se usa DynamoDB para evitar scrapping constante de la misma película.
La clave de la tabla es 'movie_name' en minúsculas para normalizar
variantes como "Matrix" y "matrix".
La tabla debe crearse en AWS con el nombre 'peliculas-cache' y
clave de partición 'movie_name' (String).

Formato de respuesta
--------------------
Se construye el JSON de respuesta manualmente (sin ASK SDK) para
mantener el contenedor Docker ligero y sin dependencias extra.
El campo shouldEndSession=True cierra la sesión tras responder,
evitando que Alexa se quede esperando más input.
"""


import asyncio
import json
import logging
import unicodedata
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from scrapper import scrapper_pelicula

# Logging
# En Lambda los logs van automáticamente a CloudWatch.
# Nivel INFO en producción: muestra el flujo principal pero no el detalle
# del scrapper (que ya tiene su propio logger en scrapper.py).

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB
# El recurso se crea fuera del handler para reutilizar la conexión entre
# invocaciones de Lambda (el contenedor permanece vivo un tiempo).
dynamodb = boto3.resource("dynamodb")
tabla = dynamodb.Table("peliculas-cache")


def obtener_de_cache(movie_name: str) -> dict | None:
    """
    Consulta DynamoDB por el nombre de la película.

    Args:
        movie_name: Nombre de la película en minúsculas.

    Returns:
        Diccionario con los datos si existe en caché, None si no.
    """
    try:
        resp = tabla.get_item(Key={"movie_name": movie_name})
        item = resp.get("Item")
        if item:
            logger.info("Cache hit: %s", movie_name)
        return item
    except (BotoCoreError, ClientError) as e:
        # Si DynamoDB falla, continuamos con el scraper
        logger.warning("Error consultando DynamoDB: %s", e)
        return None


def guardar_en_cache(movie_name: str, datos: dict) -> None:
    """
    Guarda los datos de una película en DynamoDB.

    Args:
        movie_name: Nombre de la película en minúsculas (clave).
        datos:      Diccionario devuelto por scrapper_pelicula.
    """
    try:
        tabla.put_item(Item={"movie_name": movie_name, **datos})
        logger.info("Guardado en caché: %s", movie_name)
    except (BotoCoreError, ClientError) as e:
        # Si falla el guardado, la respuesta al usuario no cambia
        logger.warning("Error guardando en DynamoDB: %s", e)


def _obtener_datos(movie_name: str) -> dict:
    """
    Función auxiliar compartida por ambos intents.
    Consulta caché y lanza el scraper si es necesario.

    Args:
        movie_name: Nombre de la película tal como lo dijo el usuario.

    Returns:
        Diccionario con los datos de la película, o {'error': '...'} si falla.
    """
    movie_name_lower = normalizar(movie_name)
    datos = obtener_de_cache(movie_name_lower)

    if not datos:
        logger.info("Cache miss, lanzando scraper para: %s", movie_name)
        datos = asyncio.run(scrapper_pelicula(movie_name))
        if "error" not in datos:
            guardar_en_cache(movie_name_lower, datos)

    return datos


# Handler principal
def lambda_handler(event, context):
    """
    Punto de entrada de AWS Lambda.

    Args:
        event:   JSON enviado por Alexa con el intent y los slots.

    Returns:
        Diccionario con la respuesta en el formato que Alexa espera.
    """
    # Logueamos el evento completo para poder depurar en CloudWatch
    # si el nombre del slot no coincide con lo que esperamos.
    # Incluímos context aunque no lo usemos, porque AWS Lambda lo pasa por defecto.
    logger.info("Evento recibido: %s", json.dumps(event))

    if event["request"]["type"] == "LaunchRequest":
        return _respuesta_abierta("Bienvenido a Películas Cine. Puedes preguntarme por la nota, sinopsis, director, duración o votos de cualquier película, o pedirme toda la información de golpe.")

    # Intents de salida — Alexa los dispara cuando el usuario dice
    # "para", "cancela", "adiós", "no gracias", "salir", etc.
    intent_name = event["request"].get("intent", {}).get("name", "")
    if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NoIntent"):
        return _respuesta("Hasta luego. ¡Que disfrutes de la película!")

    # ConsultarTodoIntent
    # El usuario pide toda la información sobre una película de golpe.
    if intent_name == "ConsultarTodoIntent":
        try:
            movie_name = event["request"]["intent"]["slots"]["pelicula"]["value"]
            if not movie_name:
                raise ValueError("Slot vacío")
        except (KeyError, TypeError, ValueError):
            logger.warning("No se pudo extraer el slot 'pelicula' en ConsultarTodoIntent.")
            return _respuesta_abierta("No he entendido el nombre de la película. ¿Puedes repetirlo?")

        datos = _obtener_datos(movie_name)

        if "error" in datos:
            logger.error("Error en el scraper: %s", datos["error"])
            return _respuesta_abierta(f"No encontré información sobre {movie_name}. Inténtalo de nuevo.")

        texto = (
            f"{datos.get('titulo', movie_name)} está dirigida por {datos.get('director', 'director desconocido')}, "
            f"dura {datos.get('duracion', 'duración desconocida')} "
            f"y tiene una nota de {datos.get('nota', 'desconocida')} sobre diez "
            f"con {datos.get('votos', 'un número desconocido de')} votos. "
            f"Su sinopsis es: {datos.get('sinopsis', 'no disponible')}."
        )
        return _respuesta_abierta(texto + " ¿Quieres saber algo más?")

    # ConsultarDatoIntent
    # El usuario pregunta por un campo concreto de una película.
    if intent_name == "ConsultarDatoIntent":
        try:
            movie_name = event["request"]["intent"]["slots"]["pelicula"]["value"]
            campo = event["request"]["intent"]["slots"]["campo"]["value"]
            if not movie_name:
                raise ValueError("Slot vacío")
        except (KeyError, TypeError, ValueError):
            logger.warning("No se pudo extraer los slots en ConsultarDatoIntent.")
            return _respuesta_abierta("No he entendido la pregunta. Puedes preguntarme por la nota, sinopsis, director, duración o votos de una película.")

        datos = _obtener_datos(movie_name)

        if "error" in datos:
            logger.error("Error en el scraper: %s", datos["error"])
            return _respuesta_abierta(f"No encontré información sobre {movie_name}. Inténtalo de nuevo.")

        # Mapeamos el campo al dato correspondiente
        respuestas = {
            "nota":     f"{datos.get('titulo', movie_name)} tiene una nota de {datos.get('nota', 'desconocida')} sobre diez.",
            "votos":    f"{datos.get('titulo', movie_name)} tiene {datos.get('votos', 'un número desconocido de')} votos.",
            "sinopsis": f"La sinopsis de {datos.get('titulo', movie_name)} es: {datos.get('sinopsis', 'no disponible')}.",
            "director": f"{datos.get('titulo', movie_name)} está dirigida por {datos.get('director', 'director desconocido')}.",
            "duracion": f"{datos.get('titulo', movie_name)} dura {datos.get('duracion', 'duración desconocida')}.",
        }

        texto = respuestas.get(
            campo,
            f"No sé cómo responder sobre '{campo}'. Puedes preguntarme por la nota, sinopsis, director, duración o votos."
        )
        return _respuesta_abierta(texto + " ¿Quieres saber algo más?")

    # Intent no reconocido
    logger.warning("Intent no reconocido: %s", intent_name)
    return _respuesta_abierta("No he entendido la pregunta. Puedes pedirme la nota, sinopsis, director, duración o votos de cualquier película.")


def normalizar(texto: str) -> str:
    """
    Normaliza el nombre para maximizar los hits de caché.
    Elimina tildes, artículos iniciales, signos de puntuación
    y colapsa espacios.
    """
    # Minúsculas
    texto = texto.lower().strip()
    # Eliminar tildes
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    # Eliminar artículos iniciales comunes
    for articulo in ("el ", "la ", "los ", "las ", "the ", "un ", "una "):
        if texto.startswith(articulo):
            texto = texto[len(articulo):]
            break
    # Eliminar puntuación
    texto = re.sub(r"[^\w\s]", "", texto)
    # Colapsar espacios
    return " ".join(texto.split())


# Helpers
def _respuesta(texto: str) -> dict:
    """
    Construye el JSON de respuesta en el formato que Alexa espera.

    shouldEndSession=True cierra la sesión tras la respuesta, evitando
    que el dispositivo Alexa se quede esperando más input del usuario.

    Args:
        texto: Frase que Alexa leerá en voz alta.

    Returns:
        Diccionario con la estructura de respuesta de Alexa.
    """
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": texto,
            },
            "shouldEndSession": True,
        },
    }


def _respuesta_abierta(texto: str) -> dict:
    """
    Respuesta que mantiene la sesión abierta para esperar
    el siguiente input del usuario.
    """
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": texto,
            },
            "shouldEndSession": False,
        },
    }