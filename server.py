"""
Servidor HTTP que expone el scrapper de cartelera como API REST.

n8n invoca este endpoint para obtener la cartelera filtrada.
Se usa FastAPI por su soporte nativo de async (necesario para Playwright)
y su generación automática de documentación OpenAPI.

Endpoints:
    GET  /health     → healthcheck para n8n y Docker
    POST /cartelera  → ejecuta el scrapper y devuelve JSON

Ejemplo:
    curl http://localhost:8000/health
    curl -X POST http://localhost:8000/cartelera
    curl -X POST http://localhost:8000/cartelera -H "Content-Type: application/json" -d '{"limite": 3}'
"""

import json
import os
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from cartelera import scrapper_cartelera, PERFIL_DEFAULT

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = FastAPI(title="Scrapper Cartelera API", version="1.0.0")


class CarteleraRequest(BaseModel):
    """
    Modelo de la petición al endpoint /cartelera.

    Attributes:
        perfil: Diccionario género → nota mínima. Si es None, usa el perfil por defecto.
        limite: Número máximo de películas a procesar. Útil para pruebas.
    """

    perfil: dict | None = None
    limite: int | None = None


# Caché en memoria para evitar re-escrapear constantemente
CACHE = {"peliculas": [], "total": 0}


@app.get("/health")
def health():
    """Healthcheck para Docker y n8n."""
    return {"status": "ok"}


@app.post("/set_cache")
def set_cache(data: dict):
    """Guarda datos en la caché del servidor."""
    global CACHE
    CACHE = data
    logger.info("Caché actualizada con %s películas", CACHE.get("total", 0))
    return {"status": "success"}


@app.get("/get_cache")
def get_cache():
    """Devuelve los datos guardados en la caché."""
    return CACHE


@app.post("/cartelera")
async def cartelera(req: CarteleraRequest = CarteleraRequest()):
    """
    Ejecuta el scrapper de cartelera y devuelve las películas filtradas.

    El perfil de usuario se puede pasar en el body o se usa el perfil
    por defecto definido en cartelera.py.
    """
    perfil = req.perfil if req.perfil is not None else PERFIL_DEFAULT
    logger.info("Ejecutando scrapper con perfil: %s, limite: %s", perfil, req.limite)

    peliculas = await scrapper_cartelera(perfil=perfil, limite=req.limite)

    return {"peliculas": peliculas, "total": len(peliculas)}
