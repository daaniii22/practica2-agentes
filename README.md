# Agente Inteligente de Cartelera y Conciertos con n8n y Groq

Este repositorio contiene una práctica avanzada de **Sistemas Inteligentes** para automatizar la extracción, análisis y distribución inteligente de la cartelera de cine de Madrid y eventos musicales/conciertos.

El sistema orquesta múltiples microservicios locales en Docker mediante **n8n**, delegando la lógica a **Llama 3.1** y almacenando el histórico de ejecuciones en un bucket **S3 local (MinIO)** como única fuente de verdad. Además, incluye la infraestructura de **ComfyUI** para futuras generaciones multimedia.

---

## Arquitectura del Sistema

El stack tecnológico está completamente contenedorizado y estructurado de forma modular y desacoplada:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                DOCKER COMPOSESTACK                                     │
│                                                                                        │
│  ┌──────────────┐     HTTP (REST API)     ┌────────────────┐                           │
│  │   scrapper   │◄────────────────────────│      n8n       │ (Orquestador Principal)   │
│  │  (FastAPI +  │                         │                │                           │
│  │  Playwright) │                         │  - Workflows   │                           │
│  └──────────────┘                         │  - Triggers    │                           │
│                                           │  - Lógica      │                           │
│  ┌──────────────┐     S3 API (Upload)     │                │                           │
│  │    MinIO     │◄────────────────────────│                │                           │
│  │ (S3 Storage) │                         │                │                           │
│  └──────────────┘                         │                │                           │
│                                           │                │                           │
│  ┌──────────────┐   HTTP (Chat Query)     │                │                           │
│  │   comfyui    │◄────────────────────────│                │                           │
│  │              │                         │                │                           │
│  └──────────────┘                         └────────────────┘                           │
│                                            ▲    ▲    │                                 │
│                                            │    │    │ HTTP (Enviar Telegram)          │
│                      Telegram Webhook      │    │    ▼                                 │
│                      (Redirección Local)   │  ┌──────────────────┐                     │
│                                            │  │   Telegram Bot   │                     │
│  ┌──────────────┐                          │  │     (Chat /      │                     │
│  │    poller    │──────────────────────────┘  │  Notificaciones) │                     │
│  │   (python)   │◄────────────────────────────┴──────────────────┘                     │
│  └──────────────┘                Long Polling (getUpdates)                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Componentes y Servicios

| Componente | Imagen / Tecnología | Puerto | Descripción |
| :--- | :--- | :--- | :--- |
| **n8n** | `n8nio/n8n:latest` | `5678` | Orquestador visual de flujos de trabajo e integraciones. |
| **Scrapper** | `FastAPI + Playwright` | `8000` | Microservicio que raspa IMDb y eCartelera bajo demanda. |
| **MinIO** | `minio/minio:latest` | `9000` / `9001` | Almacenamiento S3 local. Actúa como base de datos persistente para la cartelera. |
| **ComfyUI** | `yanwk/comfyui-boot:cpu` | `8188` | Interfaz estable de generación por IA. |
| **Telegram Poller** | `python:3.10-alpine` | *Interno* | Escucha mensajes mediante Long Polling y los inyecta al webhook local de n8n. |

---

## ⚡ Workflows n8n Implementados

Los workflows se encuentran en la carpeta `n8n_workflows/` listos para ser importados:

### 1. 📅 [Cartelera Semanal]
*   **Trigger:** Cada lunes a las 9:00 AM (o manual).
*   **Funcionamiento:** 
    1. Llama al microservicio `scrapper` para extraer las películas en cartelera de Madrid filtradas por el perfil del usuario.
    2. Si hay películas, formatea un mensaje legible y lo envía a **Groq (Llama 3.1 8b)** para verificar que no haya spoilers y corregir la gramática/estructura.
    3. Envía el mensaje segmentado automáticamente (para cumplir el límite de 4000 caracteres de Telegram) al canal principal.
    4. **Persistencia S3:** Guarda simultáneamente el JSON en MinIO en dos rutas:
        *   `cartelera_latest.json`: Sobreescribe siempre el último estado para consumo inmediato del chat.
        *   `cartelera_YYYY_MM_DD.json`: Histórico fechado semanal para auditoría y evolución temporal.

### 2. 💬 [Chat Interactivo para la Cartelera]
*   **Trigger:** Al recibir cualquier pregunta o comando por el bot de Telegram.
*   **Funcionamiento:**
    1. Descarga el JSON `cartelera_latest.json` del bucket de MinIO en tiempo real.
    2. Procesa los datos binarios a un formato estructurado en JavaScript.
    3. Groq procesa la pregunta del usuario utilizando el JSON de la cartelera, actuando como un simpático acomodador de cine.
    4. Devuelve la respuesta al chat de Telegram correspondiente de forma instantánea y sin consumir peticiones API de raspado repetitivas.

### 3. 🎸 [Agente Conciertos]
*   **Trigger:** Cada lunes a las 10:00 AM (o manual).
*   **Funcionamiento:**
    1. Obtiene los eventos musicales de la API oficial de datos abiertos del Ayuntamiento de Madrid.
    2. Filtra por eventos de tipo música/concierto que tengan lugar a partir de hoy y se queda con los 10 más próximos cronológicamente.
    3. Groq maqueta la lista con formato premium Markdown enriquecido con emojis y sin omitir detalles.
    4. Envía el resultado simultáneamente a un canal de Telegram de Conciertos y por correo electrónico (SMTP).

---

## Guía de Despliegue Rápido

### Requisitos Previos
*   Docker y Docker Compose instalados.
*   Un bot de Telegram creado mediante [@BotFather](https://t.me/BotFather) y su respectivo `Token`.
*   El `Chat ID` de tu usuario o canal (puedes usar bots como `@userinfobot` para obtenerlo).

### Paso 1: Configurar Variables de Entorno
Copia la plantilla y edita el fichero `.env` con tus tokens y llaves:
```bash
cp .env.example .env
```
Fichero `.env` configurado:
```ini
BOT_TOKEN=tu_token_de_telegram_cartelera
CHAT_ID=tu_chat_id_cartelera

BOT_CONCIERTOS_TOKEN=tu_token_de_telegram_conciertos
CHAT_CONCIERTOS_ID=tu_chat_id_conciertos

PERFIL={"Acción": 6, "Animación": 5, "Ciencia ficción": 7}
GROQ_API_KEY=gsk_tu_clave_de_groq_aqui
```

### Paso 2: Iniciar el Stack de Docker
Construye y arranca todos los contenedores en segundo plano:
```bash
docker compose up -d --build
```

### Paso 3: Configurar el Bucket en MinIO
1. Abre tu navegador e ingresa a la consola de MinIO: [http://localhost:9001](http://localhost:9001).
2. Credenciales por defecto: Usuario `admin` \| Contraseña `supersecret`.
3. Dirígete a **Buckets** ➔ **Create Bucket** y crea un bucket llamado `cartelera`.

### Paso 4: Importar y Configurar Workflows en n8n
1. Accede a n8n: [http://localhost:5678](http://localhost:5678).
2. Crea un nuevo flujo e importa cada uno de los archivos JSON de la carpeta `n8n_workflows/`.
3. **Configurar Credenciales S3:** En los nodos de S3 (`Upload a file`, `Download a file`), crea o asigna una nueva credencial de tipo **S3 Account**:
   * **Access Key:** `admin`
   * **Secret Key:** `supersecret`
   * **Endpoint:** `http://minio:9000` (¡importante usar `minio` en lugar de `localhost` ya que corre dentro de Docker!)
4. **Configurar Credenciales SMTP:** En el nodo `Send Email` del Agente Conciertos, configura tu SMTP de preferencia.
5. Activa los tres flujos (*Active* toggle arriba a la derecha).

---

## 📁 Estructura del Repositorio

```text
├── docker-compose.yml              # Stack completo (n8n, scrapper, minio, comfyui, poller)
├── Dockerfile.scrapper             # Configuración del contenedor FastAPI + Playwright
├── server.py                       # Servidor de API que envuelve scrapper.py para llamadas HTTP
├── poller.py                       # Reenvía mensajes recibidos por Telegram al webhook de n8n
├── cartelera.py                    # Script de raspado y filtrado por perfil
├── scrapper.py                    # Analizador del detalle de películas en IMDb
├── .env.example                    # Plantilla de variables de entorno para despliegue
├── n8n_workflows/                  # Ficheros JSON de los workflows para n8n
│   ├── Cartelera Semanal.json
│   ├── Chat interactivo para la cartelera.json
│   └── Agente Conciertos.json
└── README.md                       # Documentación técnica
```

---

## 📽️ Entregable Final

El proyecto cumple todos los requisitos teóricos y prácticos para ser desplegado y evaluado de forma autónoma:
*   [scrapper.py](file:///media/brian/ssd_extra/CDIA%203%C2%BA/2%C2%BA%20Cuatrimestre/Sistemas%20Inteligentes/practica2-agentes/scrapper.py) (IMDb extractor CLI).
*   [cartelera.py](file:///media/brian/ssd_extra/CDIA%203%C2%BA/2%C2%BA%20Cuatrimestre/Sistemas%20Inteligentes/practica2-agentes/cartelera.py) (Analizador de películas y perfilamiento).
*   [server.py](file:///media/brian/ssd_extra/CDIA%203%C2%BA/2%C2%BA%20Cuatrimestre/Sistemas%20Inteligentes/practica2-agentes/server.py) (Punto de entrada de API REST para Docker).
*   Ficheros de workflows definitivos en [n8n_workflows/](file:///media/brian/ssd_extra/CDIA%203%C2%BA/2%C2%BA%20Cuatrimestre/Sistemas%20Inteligentes/practica2-agentes/n8n_workflows).
*   Stack listo para desplegar con `docker compose up -d`.
