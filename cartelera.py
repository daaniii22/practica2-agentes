"""
Scraper de cartelera de Madrid en eCartelera usando Playwright.

Fases del flujo:
--------------------
  1. Carga: navegamos a la URL de cartelera de Madrid en eCartelera.
     Usamos la página de ciudad (Madrid) en lugar de la de provincia para
     acotar los resultados a los cines dentro de la capital.

  2. Extracción: una vez cargada la sección de películas, extraemos los
     títulos y URLs de cada película en cartelera. Filtramos duplicados
     y enlaces de navegación exigiendo que la URL sea exactamente una
     ficha individual (/peliculas/slug/), descartando el índice general
     y las subpáginas (/peliculas/slug/cartelera/).

  3. Género: para cada película, visitamos su página en eCartelera y
     buscamos el patrón 'Género: X, Y' con regex sobre el texto completo
     de la página, igual que la duración en scrapper.py, para no depender
     de un selector concreto que varía entre películas. Se extraen todos
     los géneros para que el filtro de perfil pueda comprobar cualquiera
     de ellos, no solo el primero.

  4. Filtrado y enriquecimiento: las películas que pasan el filtro de perfil
     (alguno de sus géneros presente en el perfil y nota de IMDB por encima
     del umbral) se consultan en IMDB usando scrapper_pelicula() para obtener
     nota, votos, sinopsis, director y duración.

  5. Notificación: se envía el resultado formateado por Telegram, dividiendo
     en varios mensajes si se supera el límite de 4096 caracteres, siempre
     respetando el límite entre películas para no cortar una entrada a mitad.

Decisiones de diseño:
--------------------
- Se reutiliza scrapper_pelicula() de scrapper.py para no duplicar
  lógica de extracción de datos de IMDB.

- playwright-stealth enmascara la variable navigator.webdriver y otras
  huellas digitales para que no se nos detecte como un bot.

- El enriquecimiento con IMDB se hace fuera del bloque del navegador
  de eCartelera para cerrarlo cuanto antes y liberar recursos.

- El parámetro --limite permite acortar la lista durante el desarrollo
  sin modificar el código.

Ejemplo de uso:
-------------------------
  python cartelera.py
  python cartelera.py --perfil '{"Acción": 7, "Drama": 6}'
  python cartelera.py --sin-perfil
  python cartelera.py --sin-perfil --limite 3
"""

import asyncio
import json
import re
import requests
import argparse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from scrapper_david import scrapper_pelicula

# Configuración

BOT_TOKEN = "8771613781:AAFsfj0JRy6dXydtfj4yEJbtUcdCRdabc68"
CHAT_ID = "-5191815456"

URL_CARTELERA = "https://www.ecartelera.com/cines/0,30,1.html"

# Perfil por defecto: género → nota mínima de IMDB para pasar el filtro.
# Géneros disponibles en eCartelera (comentar/descomentar según preferencia):
PERFIL_DEFAULT = {
    "Acción": 6,
    "Animación": 5,
    # "Aventura":      6,
    # "Biografía":     7,
    "Ciencia ficción": 7,
    "Comedia": 6,
    # "Crimen":        6,
    # "Deporte":       6,
    # "Documental":    7,
    "Drama": 7,
    # "Erótica":       6,
    # "Familiar":      5,
    # "Fantasía":      6,
    # "Guerra":        7,
    # "Historia":      7,
    # "LGTB":          6,
    # "Misterio":      6,
    # "Música":        6,
    # "Romance":       6,
    # "Suspense":      6,
    "Terror": 6,
    "Thriller": 6,
    # "Western":       6,
}


# Funciones de limpieza y extracción de datos con regex


def limpiar(texto: str) -> str:
    """
    Normaliza el texto de un elemento web.

    Los textos obtenidos con Playwright pueden contener saltos de línea o espacios
    múltiples por el HTML. Esta función los deja en un único espacio. En la práctica,
    esta función no suele ser necesaria pero la usamos por si nos encontramos cosas
    del tipo 'Christopher\n Nolan' o '2h  49min' con doble espacio.

    Args:
        texto: Texto raw de un elemento web.

    Returns:
        Texto limpio o 'N/A' si la entrada está vacía.
    """
    if not texto:
        return "N/A"

    return " ".join(texto.split())


def extraer_genero(texto: str) -> list[str]:
    """
    Extrae todos los géneros de la página de una película en eCartelera.

    eCartelera muestra los géneros en un bloque con el patrón 'Género: X, Y, Z'.
    Devolvemos todos para que el filtro de perfil pueda comprobar cualquiera de ellos,
    no solo el primero. Buscamos el patrón en el texto completo del body, igual que
    la duración en scrapper.py, para no depender de un selector concreto.

    Args:
        texto: Texto completo del body de la página de la película en eCartelera.

    Returns:
        Lista de géneros encontrados o ['Desconocido'] si no se encuentra.
    """
    match = re.search(r"G[eé]nero[s]?:?\s*([A-Za-záéíóúÁÉÍÓÚüÜñÑ ,\-]+)", texto)
    if match:
        # Dividimos por espacio simple entre palabras que empiezan por mayúscula,
        # ya que eCartelera separa géneros con espacios: "Comedia Drama Thriller"
        generos = re.findall(
            r"[A-ZÁÉÍÓÚ][a-záéíóúüñ]+(?: [a-záéíóúüñ]+)*", match.group(1)
        )
        return generos if generos else ["Desconocido"]
    return ["Desconocido"]


def formatear_mensaje(peliculas: list[dict]) -> str:
    """
    Construye el mensaje de Telegram con la cartelera filtrada.

    Args:
        peliculas: Lista de diccionarios con los datos de cada película.

    Returns:
        Texto en formato Markdown listo para enviar por Telegram.
    """
    if not peliculas:
        return "🎬 *Cartelera de Madrid*\n\nNo hay películas que cumplan tu perfil esta semana."

    lineas = ["🎬 *Cartelera de Madrid — Esta semana*\n"]
    for p in peliculas:
        lineas.append(
            f"*{p['titulo']}*\n"
            f"  🎭 Género: {p['genero']}\n"
            f"  ⭐ Nota: {p['nota']}/10 ({p['votos']} votos)\n"
            f"  🎬 Director: {p['director']}\n"
            f"  ⏱ Duración: {p['duracion']}\n"
            f"  📝 {p['sinopsis']}\n"
        )
    return "\n\n".join(lineas)


# Telegram


def enviar_telegram(mensaje: str) -> None:
    """
    Envía un mensaje de texto al chat configurado vía Telegram Bot API.
    Si el mensaje supera los 4096 caracteres (límite de Telegram),
    lo divide en chunks respetando siempre el límite entre películas,
    nunca en medio de una entrada.

    Args:
        mensaje: Texto en formato Markdown a enviar.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    limite = 4096

    # Dividimos por película (doble salto de línea entre ellas).
    # Así nunca cortamos en medio de una entrada.
    bloques = mensaje.split("\n\n")
    chunk_actual = ""

    for bloque in bloques:
        # Si añadir este bloque supera el límite, enviamos lo acumulado
        # y empezamos un chunk nuevo con este bloque.
        if len(chunk_actual) + len(bloque) + 2 > limite:
            payload = {
                "chat_id": CHAT_ID,
                "text": chunk_actual.strip(),
                "parse_mode": "Markdown",
            }
            requests.post(url, json=payload)
            chunk_actual = bloque + "\n\n"
        else:
            chunk_actual += bloque + "\n\n"

    # Enviamos el último chunk si quedó algo.
    if chunk_actual.strip():
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk_actual.strip(),
            "parse_mode": "Markdown",
        }
        requests.post(url, json=payload)


# Scraper principal


async def scrapper_cartelera(
    perfil: dict, headless: bool = True, limite: int = None
) -> list[dict]:
    """
    Extrae las películas en cartelera en Madrid y las enriquece con datos de IMDB.

    Args:
        perfil:   Diccionario género → nota mínima para filtrar películas.
                  Si está vacío, se devuelven todas las películas sin filtrar.
        headless: Si es False, abre una ventana visible del navegador.
                  Útil para el desarrollo y depuración visual.
        limite:   Número máximo de películas a procesar. Útil para pruebas
                  sin tener que esperar la lista completa.

    Returns:
        Lista de diccionarios con las claves: titulo, genero, nota, votos,
        sinopsis, director, duracion. Si algo falla, devuelve lista vacía.
    """
    async with async_playwright() as p:
        # Usamos como navegador Chromium por su buena compatibilidad con Playwright y su rendimiento.
        browser = await p.chromium.launch(headless=headless)

        context = await browser.new_context(
            # Forzamos español para obtener los textos de género en castellano.
            # El contexto es como una sesión independiente con su propia
            # configuración de idioma, cookies, etc.
            locale="es-ES",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # Creamos una nueva pestaña o ventana dentro del contexto.
        page = await context.new_page()

        # Stealth enmascara navigator.webdriver y otras variables JS que
        # los sitios usan para detectar navegadores automatizados.
        await Stealth().apply_stealth_async(page)

        peliculas_cartelera = []

        try:
            # 1. Carga de la cartelera
            # Usamos wait_until="domcontentloaded" para continuar cuando el HTML básico esté listo,
            # sin esperar a que carguen otros recursos secundarios.
            print("1. Cargando cartelera de Madrid.")
            await page.goto(URL_CARTELERA, wait_until="domcontentloaded")

            # El banner de cookies no siempre aparece; si no lo hay en
            # 3 segundos, continuamos.
            try:
                await page.get_by_test_id("accept-button").click(timeout=3000)
                print("Cookies aceptadas.")
            except Exception:
                pass

            # 2. Extracción de títulos y URLs
            # Esperamos a que aparezca el primer enlace de película. Si no aparece en 15 segundos, error.
            # Los enlaces de película en eCartelera contienen '/peliculas/' en su href.
            print("2. Extrayendo lista de películas.")
            await page.wait_for_selector("a[href*='/peliculas/']", timeout=15000)

            enlaces = await page.locator("a[href*='/peliculas/']").all()

            peliculas_vistas = set()
            for enlace in enlaces:
                try:
                    titulo = limpiar(await enlace.inner_text())
                    href = await enlace.get_attribute("href")

                    # Filtramos enlaces vacíos, duplicados o demasiado cortos
                    # para ser títulos reales.
                    if not titulo or not href or titulo in peliculas_vistas:
                        continue
                    if len(titulo) < 2 or len(titulo) > 60:
                        continue
                    # Requerimos que la URL sea exactamente una ficha individual: /peliculas/slug/
                    # Esto descarta el índice general (/peliculas/) y las subpáginas
                    # (/peliculas/slug/cartelera/).
                    if not re.search(r"/peliculas/[^/]+/$", href):
                        continue

                    peliculas_vistas.add(titulo)
                    url_pelicula = (
                        href
                        if href.startswith("http")
                        else f"https://www.ecartelera.com{href}"
                    )
                    peliculas_cartelera.append(
                        {
                            "titulo": titulo,
                            "url_ecartelera": url_pelicula,
                        }
                    )
                except Exception:
                    continue

            # Aplicamos el límite antes de visitar cada página individual,
            # para no hacer más peticiones de las necesarias durante el desarrollo.
            if limite:
                peliculas_cartelera = peliculas_cartelera[:limite]

            print(f"   → {len(peliculas_cartelera)} películas encontradas.")

            # 3. Extracción de géneros desde la página de cada película
            # Extraemos todos los géneros para que el filtro pueda comprobar
            # cualquiera de ellos, no solo el primero.
            print("3. Obteniendo géneros.")
            for peli in peliculas_cartelera:
                try:
                    await page.goto(
                        peli["url_ecartelera"], wait_until="domcontentloaded"
                    )
                    await page.wait_for_selector("body", timeout=10000)
                    page_text = await page.inner_text("body")
                    peli["generos"] = extraer_genero(page_text)
                except Exception:
                    peli["generos"] = ["Desconocido"]

        except Exception as e:
            # Error en la navegación o extracción.
            # Guardamos una captura para facilitar el debug.
            print(f"Error: {e}")
            await page.screenshot(path="debug_cartelera.png")

        finally:
            # Cerramos el navegador siempre, tanto si hubo error como si no.
            await browser.close()

    # 4. Filtrado por perfil y enriquecimiento con IMDB
    # Esto se hace fuera del bloque del navegador para cerrarlo cuanto antes
    # y liberar recursos antes de lanzar las consultas a IMDB.
    print("4. Filtrando por perfil y consultando IMDB.")
    resultado = []

    for peli in peliculas_cartelera:
        generos = peli.get("generos", ["Desconocido"])

        # Si hay perfil activo, comprobamos si alguno de los géneros está en él.
        # Así una película de 'Acción Ciencia ficción' pasa el filtro si
        # cualquiera de los dos géneros está en el perfil.
        if perfil and not any(g in perfil for g in generos):
            continue

        # Consultamos IMDB usando el scrapper ya implementado.
        datos_imdb = await scrapper_pelicula(peli["titulo"])

        if "error" in datos_imdb:
            continue

        # Convertimos la nota a float para comparar (ej. '7,4' → 7.4).
        try:
            nota = float(datos_imdb["nota"].replace(",", "."))
        except (ValueError, AttributeError):
            nota = 0.0

        # Aplicamos el umbral de nota mínima más exigente de los géneros que matchearon.
        if perfil:
            nota_minima = max(perfil[g] for g in generos if g in perfil)
            if nota < nota_minima:
                continue

        resultado.append(
            {
                "titulo": datos_imdb.get("titulo", peli["titulo"]),
                "genero": ", ".join(generos),
                "nota": datos_imdb.get("nota", "N/A"),
                "votos": datos_imdb.get("votos", "N/A"),
                "director": datos_imdb.get("director", "N/A"),
                "duracion": datos_imdb.get("duracion", "N/A"),
                "sinopsis": datos_imdb.get("sinopsis", "N/A"),
            }
        )

    return resultado


# Ejecución


async def main():
    parser = argparse.ArgumentParser(
        description="Scraper de cartelera de Madrid con filtro por perfil de usuario"
    )
    parser.add_argument(
        "--perfil",
        type=str,
        default=None,
        help='Perfil JSON con género y nota mínima. Ej: \'{"Acción": 7, "Drama": 6}\'',
    )
    parser.add_argument(
        "--sin-perfil",
        action="store_true",
        help="Devuelve todas las películas sin filtrar.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Número máximo de películas a procesar (útil para pruebas).",
    )
    parser.add_argument(
        "--headless",
        action="store_false",
        dest="headless",
        help="Abre el navegador en modo visible (útil para depuración).",
    )
    args = parser.parse_args()

    if args.sin_perfil:
        perfil = {}
    elif args.perfil:
        try:
            perfil = json.loads(args.perfil)
        except json.JSONDecodeError:
            print("Error: el perfil no es un JSON válido.")
            return
    else:
        perfil = PERFIL_DEFAULT

    peliculas = await scrapper_cartelera(
        perfil=perfil,
        headless=args.headless,
        limite=args.limite,
    )

    print("\nResultado:")
    print(json.dumps(peliculas, indent=4, ensure_ascii=False))

    print("\nEnviando por Telegram...")
    enviar_telegram(formatear_mensaje(peliculas))
    print("¡Listo!")


if __name__ == "__main__":
    asyncio.run(main())
