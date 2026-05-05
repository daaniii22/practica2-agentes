# Usamos la imagen base oficial de AWS Lambda para Python 3.12, ya que tiene varias ventajas 
# frente a python:3.12-slim:
#   - El Runtime Interface Client (RIC) viene incluido
#   - El entorno replica exactamente el de Lambda en AWS
#   - No hay que configurar el ENTRYPOINT manualmente
FROM public.ecr.aws/lambda/python:3.12

# Dependencias para Chromium
# Playwright necesita bastantes librerías gráficas del sistema operativo para poder usar Chromium. 
# Sin estas, playwright install chromium instala el binario pero el navegador falla al ejecutarse.
RUN dnf install -y \
    atk \
    cups-libs \
    gtk3 \
    libXcomposite \
    libXcursor \
    libXdamage \
    libXext \
    libXi \
    libXrandr \
    libXScrnSaver \
    libXtst \
    pango \
    alsa-lib \
    at-spi2-atk \
    libdrm \
    libgbm \
    nss \
    && dnf clean all

# Dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalación de Chromium
# PLAYWRIGHT_BROWSERS_PATH indica dónde guardar el binario dentro del
# contenedor — usamos /ms-playwright para seguir la convención de Playwright.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

# Código de la aplicación
# LAMBDA_TASK_ROOT es la ruta estándar donde Lambda busca el código.
# La imagen base de AWS la define automáticamente como /var/task.
COPY scrapper.py ${LAMBDA_TASK_ROOT}/
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Punto de entrada
# La imagen base de AWS ya tiene el ENTRYPOINT configurado para el RIC,
# así que solo necesitamos el CMD con el handler.
CMD ["lambda_function.lambda_handler"]