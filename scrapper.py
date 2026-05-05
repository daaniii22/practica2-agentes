"""
Scraper de películas en IMDb usando Playwright.

Fases del flujo:
--------------------
  1. Búsqueda: navegamos a la URL de búsqueda de IMDb para esa película.
     De esta forma evitamos la homepage para ahorrar una carga de página completa, 
     además de aprovechar el SEO de la página de resultados.

  2. Selección: clicamos el primer resultado de la lista de títulos.
     El selector está acotado al contenedor de resultados para no
     confundirlo con links de navegación del header.

  3. Extracción: una vez en la ficha, cada campo tiene su propia función
     auxiliar con su estrategia de extracción.
     
Decisiones de diseño:
--------------------
- Se usa locale='es-ES' para obtener los textos en español (nota, votos,
  sinopsis) y el regex de votos cubre los sufijos españoles (mil) e
  ingleses (M, K) por si IMDb mezcla idiomas.

- playwright-stealth enmascara la variable navigator.webdriver y otras
  huellas digitales para que no se nos detecte como un bot.

- Los campos se extraen con funciones de regex sobre el texto del
  elemento, no sobre el HTML, lo que hace el código más legible.

Ejemplo de uso:
-------------------------
  python scrapper.py "Interstellar"
"""

import asyncio
import sys
import json
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import logging
import glob

# Configuración básica de logging para facilitar el debug y seguimiento de la ejecución.
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Funciones de limpieza y extracción de datos con regex

def limpiar(texto: str) -> str:
    """
    Normaliza el texto de un elemento web.

    Los textos obtenidos con Playwright pueden contener saltos de línea o espacios
    múltiples por el HTML. Esta función los deja un único espacio. En la práctica,
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


def extraer_nota(texto: str) -> str:
    """
    Extrae la puntuación del bloque de rating de IMDb.

    IMDb muestra la nota con coma decimal en español (ej. '8,7').
    Aceptamos uno o dos dígitos antes de la coma para cubrir
    el caso de '10,0'.

    Args:
        texto: Texto completo del bloque de rating.

    Returns:
        Devolvemos como string la puntuación (ej. '8,7') o 'N/A' si no se encuentra.
    """
    match = re.search(r"(\d{1,2}[.,]\d)", texto)
    return match.group(1) if match else "N/A"


def extraer_votos(texto: str) -> str:
    """
    Extrae el número de votos del bloque de rating de IMDb.

    IMDb tiene varios formatos para los votos según el volumen
    y el idioma (intentamos forzar español con locale, pero a veces mezcla):
      - '2,2 mil'  -> miles en español
      - '850 K'    -> miles en inglés
      - '2,5 M'    -> millones en ambos idiomas

    El sufijo es obligatorio (sin ?) para evitar coger el primer dígito
    encontrado y confundirlo con un voto.

    Args:
        texto: Texto completo del bloque de rating.

    Returns:
        Votos como string (ej. '2,2 mil') o 'N/A' si no se encuentra.
    """
    match = re.search(r"(\d[\d.,]*\s?(?:mil|[MK]))", texto)
    return match.group(1).strip() if match else "N/A"


def extraer_duracion(texto: str) -> str:
    """
    Busca el patrón de duración en el texto completo de la página.
    IMDb en español usa 'min' y debemos cubrir horas y minutos, solo horas o solo minutos.

    Args:
        texto: Texto completo del body de la página.

    Returns:
        Duración como string (ej. '2h 49min') o 'N/A' si no se encuentra.
    """
    match = re.search(r"\b(\d+h(?:\s\d+min)?|\d+min)\b", texto)
    return match.group(1) if match else "N/A"


def get_chromium_path() -> str:
    rutas = glob.glob("/ms-playwright/chromium-*/chrome-linux/chrome")
    if not rutas:
        raise FileNotFoundError("No se encontró el binario de Chromium en /ms-playwright")
    return rutas[0]


# Scraper principal
async def scrapper_pelicula(nombre_busqueda: str, headless: bool = True) -> dict:
    """
    Dado el nombre de una película, devuelve sus datos de IMDb.

    Args:
        nombre_busqueda: Nombre de la película a buscar.
        headless:        Si es False, abre una ventana visible del navegador.
                         Útil para el desarrollo y depuración visual.

    Returns:
        Diccionario con las claves: titulo, nota, votos, sinopsis,
        director, duracion. Si algo falla, devuelve {'error': '...'}.
    """

    # Validación de entrada antes de lanzar el navegador
    nombre_busqueda = nombre_busqueda.strip()
    if not nombre_busqueda:
        return {"error": "El nombre de la película no puede estar vacío."}

    async with async_playwright() as p:
        # Usamos como navegador Chromium por su buena compatibilidad con Playwright y su rendimiento.
        browser = await p.chromium.launch(
            headless=True,
            executable_path=get_chromium_path(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",  # /dev/shm es muy pequeño en Lambda
                "--disable-gpu",             # Lambda no tiene GPU
                "--single-process",          # reduce el uso de memoria
                ]
            )
        context = await browser.new_context(
            # Forzamos español para obtener sinopsis y metadatos en castellano.
            # El regex de votos cubre sufijos en ambos idiomas por si IMDb
            # mezcla según la IP del usuario. El contexto es como una sesión independiente con su propia 
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

        try:
            # 1. Búsqueda directa
            # Construimos la URL de búsqueda directamente en vez de pasar
            # por la homepage y usar la barra de búsqueda. Esto ahorra
            # una carga de página completa.
            # ttype=ft filtra solo largometrajes (feature films).
            # Usamos wait_until="domcontentloaded" para continuar cuando el HTML básico esté listo, 
            # sin esperar a que carguen otros recursos secundarios.
            logger.info("1. Buscando en IMDb.")
            query = nombre_busqueda.replace(" ", "+")
            await page.goto(
                f"https://www.imdb.com/find?q={query}&s=tt&ttype=ft",
                wait_until="domcontentloaded",
            ) 

            # El banner de cookies no siempre aparece; si no lo hay en
            # 3 segundos, continuamos.
            try:
                await page.get_by_test_id("accept-button").click(timeout=3000)
                logger.info("Cookies aceptadas.")
            except Exception:
                pass

            # 2. Selección del primer resultado
            # Acotamos el selector a .ipc-metadata-list-summary-item para
            # no confundir los resultados con links de /title/tt que también
            # aparecen en el header de navegación y en publicidad.
            logger.info("2. Seleccionando primer resultado.")
            # Esperamos a que aparezca el primer resultado de título. Si no aparece en 15 segundos, error.
            await page.wait_for_selector(
                ".ipc-metadata-list-summary-item a[href*='/title/tt']",
                timeout=15000,
            )
            # Clicamos el primer resultado que contenga un enlace con '/title/tt' en su href.
            await page.locator(
                ".ipc-metadata-list-summary-item a[href*='/title/tt']"
            ).first.click()

            # 3. Esperamos a que cargue la ficha
            # Esperamos el h1 como señal mínima de que la ficha ha cargado.
            # No usamos networkidle porque IMDb tiene peticiones publicitarias
            # continuas que hacen que nunca se cumpla ese estado.
            logger.info("3. Cargando ficha de la película.")
            await page.wait_for_selector("h1", timeout=15000)

            # 4. Extracción de los campos deseados
            # Cada campo va en su propio try/except para que un fallo
            # puntual no aborte la extracción del resto.
            logger.info("4. Extrayendo datos.")
            res = {}

            # Título
            try:
                res["titulo"] = limpiar(
                    await page.locator("h1").first.inner_text()
                )
            except Exception:
                res["titulo"] = "N/A"

            # Nota y votos
            # Buscamos el bloque que contiene la puntuación. IMDb puede
            # mostrar la etiqueta en español ('PUNTUACIÓN') o en inglés
            # ('RATING', 'IMDb RATING') según la IP, así que cubrimos ambos.
            try:
                logger.info("Rating.")
                rating_loc = (
                    page.locator("div")
                    .filter(has_text=re.compile(r"PUNTUACI[ÓO]N|RATING|IMDb RATING", re.I))
                    .first
                )
                raw_rating = await rating_loc.inner_text()
                res["nota"] = extraer_nota(raw_rating)
                res["votos"] = extraer_votos(raw_rating)
            except Exception:
                res["nota"] = "N/A"
                res["votos"] = "N/A"

            # Sinopsis
            # IMDb usa data-testid 'plot-xl' en la ficha principal. Esto lo sabemos por 
            # inspeccionar el HTML, pero para hacerlo más robusto, usamos un selector que 
            # busque cualquier atributo que empiece por 'plot'.
            # El selector ^= (empieza por) cubre variantes como 'plot-l'.
            try:
                logger.info("Sinopsis.")
                sinopsis_loc = page.locator('[data-testid^="plot"]').first
                res["sinopsis"] = limpiar(await sinopsis_loc.inner_text())
            except Exception:
                res["sinopsis"] = "N/A"

            # Director
            # Filtramos el <li> que contiene la palabra 'Director' o 'Dirección'
            # y extraemos el primer link dentro de él. Se omiten los anclajes ^ y $ 
            # para no depender de que el texto del <li> sea exactamente esa palabra y nada más.
            try:
                logger.info("Director.")
                director_loc = (
                    page.locator("li")
                    .filter(has_text=re.compile(r"Direcci[oó]n|Director", re.I))
                    .first
                )
                res["director"] = limpiar(
                    await director_loc.get_by_role("link").first.inner_text()
                )
            except Exception:
                res["director"] = "N/A"

            # Duración
            # Buscamos el patrón temporal en el texto completo de la página
            # para no depender de un selector concreto que varía según el
            # tipo de contenido (serie, película, corto).
            try:
                logger.info("Duración.")
                page_text = await page.inner_text("body")
                res["duracion"] = extraer_duracion(page_text)
            except Exception:
                res["duracion"] = "N/A"

            logger.info("Extracción finalizada.")
            return res

        except Exception as e:
            # Error en la navegación o selección.
            logger.error(f"Error: {e}")
            return {"error": str(e)}

        finally:
            # Cerramos el navegador siempre, tanto si hubo error como si no. 
            await browser.close()


# Ejecución 
async def main():
    if len(sys.argv) < 2:
        logger.error("Uso: python scrapper.py <nombre de la película>")
        logger.error('Ejemplo: python3 scrapper.py "Torrente"')
        return
    nombre = " ".join(sys.argv[1:])
    resultado = await scrapper_pelicula(nombre)
    logger.info("\nResultado:")
    logger.info(json.dumps(resultado, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())