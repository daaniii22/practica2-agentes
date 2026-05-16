# practica2-agentes

Práctica de IA Agéntica — Agente Inteligente para Películas.

## Componentes principales

| Componente | Archivo | Descripción |
|---|---|---|
| Scrapper IMDb | `scrapper.py` | Dado el nombre de una película, extrae nota, votos, sinopsis, director y duración de IMDb usando Playwright |
| Skill de Alexa | `lambda_function.py` | Lambda de AWS que usa el scrapper para responder preguntas sobre películas vía Alexa |
| Cartelera de Madrid | `cartelera.py` | Scrapper de eCartelera que extrae la cartelera, filtra por perfil de usuario y envía por Telegram |
| Dockerfile Lambda | `Dockerfile` | Imagen Docker para desplegar la Lambda en AWS con Playwright + Chromium |

### Uso del scrapper

```bash
python scrapper.py "Interstellar"
python scrapper.py "2001" --campo nota
```

### Uso de la cartelera

```bash
# Con perfil por defecto
python cartelera.py

# Con perfil personalizado
python cartelera.py --perfil '{"Acción": 7, "Drama": 6}'

# Sin filtro (todas las películas)
python cartelera.py --sin-perfil --limite 5
```

---

## Parte opcional: Workflow n8n + Guardarraíl (Gemini)

Orquestación de la cartelera y de conciertos con **n8n** y validación/procesamiento con **Google Gemini (API)** antes de enviarlos por Telegram.

### Arquitectura

```text
┌────────────────────────────────────────────────────────────────┐
│                    Docker Compose                              │
│                                                                │
│  ┌──────────┐    HTTP     ┌───────────┐                        │
│  │   n8n    │───────────►│ scrapper  │  (FastAPI + Playwright) │
│  │          │            │           │                         │
│  │          │            └───────────┘                         │
│  │          │    HTTP                                          │
│  │          │───────────► API Google Gemini (LLM en la nube)   │
│  │          │                                                  │
│  │          │    HTTP                                          │
│  │          │───────────► Telegram Bot API                     │
│  │          │                                                  │
│  │          │◄──────────┐ HTTP (Webhook local)                 │
│  └──────────┘           │                                      │
│                         │                                      │
│  ┌──────────┐           │                                      │
│  │  poller  │───────────┘                                      │
│  │ (python) │───────► Telegram API (Long Polling getUpdates)   │
│  └──────────┘                                                  │
└────────────────────────────────────────────────────────────────┘
```

### Flujos de n8n Incluidos

1. **Notificador de Cartelera (`cartelera_semanal_gemini.json`)**:
   - Se ejecuta por Cron los lunes.
   - Llama a `scrapper` para filtrar la cartelera.
   - Pasa la cartelera por la IA (Gemini) para validar el tono y el formato.
   - Envía los mensajes estructurados por Telegram.

2. **Chat Interactivo de Cartelera (`cartelera_chat_gemini.json`)**:
   - Escucha mensajes en tiempo real vía el microservicio `poller`.
   - Lee la pregunta del usuario por Telegram.
   - Gemini responde basándose estrictamente en la cartelera actual raspada por el scrapper.

3. **Notificador de Conciertos (`conciertos_gemini.json`)**:
   - Extrae eventos culturales de la API de Datos Abiertos de Madrid.
   - Gemini estructura los datos en formato Markdown.
   - Envía el resumen por Telegram y Email.

### Decisiones de Diseño y Problemas Resueltos

* **Uso de FastAPI**: En vez de ejecutar scripts de Python a través de nodos SSH, se construyó un pequeño servidor FastAPI (`server.py`). Esto permite a n8n interactuar con el código Python a través de llamadas HTTP limpias.
* **Caché en Memoria (Optimización de Rendimiento)**: Para que el bot de chat responda de forma instantánea, se implementó una capa de caché en la memoria RAM del servidor `scrapper`. El workflow semanal guarda la cartelera procesada mediante un `POST /set_cache`, y el bot de chat la recupera mediante un `GET /get_cache`. Esto elimina la necesidad de raspar la web en cada interacción y evita problemas de permisos de escritura en disco.
* **Control de Quotas (Gemini Rate Limiting)**: Para cumplir con los límites de la API gratuita de Gemini (15 RPM / 5 burst), el workflow semanal procesa las películas en lotes de 7 y aplica un intervalo de espera de 20 segundos entre peticiones. Esto garantiza que el envío de la cartelera sea robusto y no se bloquee por "Too Many Requests".
* **Migración a la Nube (Gemini)**: Inicialmente se usó Ollama local. Sin embargo, se migró a la API de Gemini para delegar el procesamiento a la nube, ganando estabilidad (0 crasheos), inteligencia para formatear, y la posibilidad de crear bots conversacionales súper rápidos.
* **Telegram Poller Local**: En lugar de exponer n8n a internet mediante webhooks públicos inestables (como localtunnel o ngrok), se desarrolló un servicio en Python (`poller.py`) que usa Long Polling para escuchar a Telegram y reenviar los mensajes al webhook interno de n8n. Esto hace que el bot funcione 100% en local sin problemas de red o bloqueos.
* **Supergrupos de Telegram**: El sistema detecta y maneja el cambio de IDs cuando un grupo de Telegram se convierte en Supergrupo, asegurando que las notificaciones semanales lleguen al destino correcto.

### Requisitos

- Docker Desktop instalado y funcionando
- Token de bot de Telegram ([@BotFather](https://t.me/BotFather))
- Chat ID del grupo o usuario de Telegram

### Despliegue

1. **Configurar variables de entorno:**

```bash
cp .env.example .env
# Editar .env con tus credenciales (BOT_TOKEN, GEMINI_API_KEY, etc)
```

2. **Levantar el stack:**

```bash
docker compose up -d --build
```

4. **Importar los workflows en n8n:**
   - Abrir [http://localhost:5678](http://localhost:5678)
   - Ir a *Workflows* → *Import from File*
   - Importar `n8n_workflows/cartelera_semanal_gemini.json`
   - Importar `n8n_workflows/cartelera_chat_gemini.json`
   - Importar `n8n_workflows/conciertos_gemini.json`
   - Activar los workflows (toggle en la esquina superior derecha)

5. **Probar manualmente:**
   - En n8n, pulsar *Test Workflow* para ejecutar sin esperar al lunes

### Estructura de ficheros (opcional)

```text
├── docker-compose.yml          # Stack: n8n + scrapper + poller
├── Dockerfile.scrapper         # Imagen para el servidor FastAPI
├── server.py                   # API REST que envuelve cartelera.py
├── poller.py                   # Microservicio para interceptar Telegram Webhooks
├── .env.example                # Template de variables de entorno
├── .env                        # Variables de entorno (no commiteado)
└── n8n_workflows/
    ├── cartelera_semanal_gemini.json # Workflow cartelera con Gemini
    ├── cartelera_chat_gemini.json    # Workflow chat interactivo
    └── conciertos_gemini.json        # Workflow conciertos con Gemini
```

---

## Entregable

- `scrapper.py` — Scrapper de IMDb por línea de comandos
- `lambda_function.py` — Lambda de Alexa
- `cartelera.py` — Analizador de cartelera
- `server.py` — API REST para n8n
- `docker-compose.yml` — Stack de Docker
- `poller.py` — Script de Long Polling para el bot
- `n8n_workflows/` — Carpeta con los 3 workflows definitivos exportados
- Vídeo demostrando el funcionamiento
