# Inmo Helpdesk — Guía de configuración

Este documento explica cómo preparar el entorno de desarrollo, ejecutar la aplicación localmente y usar los servicios requeridos (Postgres, Redis y Celery). Está pensado para que un compañero pueda poner en marcha el proyecto rápidamente.

**Resumen rápido**
- **Framework:** Django 5.2
- **Base de datos:** PostgreSQL (docker-compose incluido)
- **Broker de tareas:** Redis + Celery
- **Frontend:** Tailwind (en `theme`)

Requisitos previos
- Python 3.11+ (recomendado). Instalar `pip` y `virtualenv` o usar `venv`.
- Docker & Docker Compose (opcional pero recomendado para Postgres/Redis).
- Node.js + npm (para compilar Tailwind CSS): solo necesario si vas a modificar/compilar estilos.

Nota importante para usuarios de Windows
- Recomendamos usar WSL2 + Docker Desktop (con integración WSL) para una experiencia más cercana a Linux.
- Alternativas:
  - Ejecutar Django y Python en Windows nativo y usar Docker Desktop para Postgres/Redis.
  - Ejecutar toda la stack dentro de WSL2.

Activación de entorno virtual en Windows
- PowerShell (recomendado):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

- CMD:

```cmd
python -m venv .venv
.venv\Scripts\activate
```

Notas sobre `docker-compose` y `DB_HOST` en Windows
- Si usas `docker-compose up -d` y ejecutas Django dentro de los contenedores, deja `DB_HOST=db` y `CELERY_BROKER_URL=redis://redis:6379/0` en `.env`.
- Si ejecutas Django en Windows/WSL y usas Docker Desktop con puertos mapeados (como en `docker-compose.yml`), puedes usar `DB_HOST=127.0.0.1` o `localhost` para conectar al Postgres mapeado.

Node / npm en Windows
- Instala Node.js desde https://nodejs.org/ o usa `nvm-windows` si prefieres administrar versiones.
- Si `django-tailwind` requiere la ruta de `npm`, puedes definirla en el entorno (`NPM_BIN_PATH`) o el `PATH` del sistema. El proyecto intenta detectar `npm` automáticamente; si falla, añade en `.env`:

```
NPM_BIN_PATH=C:\\Program Files\\nodejs\\npm.cmd
```

Celery y Windows
- Ejecutar workers de Celery en Windows puede producir limitaciones. Recomendamos:
  - Ejecutar Celery dentro de WSL2 o en un contenedor Docker (más fiable).
  - Para desarrollo rápido sin worker, dejar `CELERY_TASK_ALWAYS_EAGER=true` en `.env`.


Archivos relevantes
- Configuración Django: [config/settings.py](config/settings.py)
- Archivo de variables de entorno: [.env](.env)
- Dependencias Python: [requirements.txt](requirements.txt)
- Docker Compose (Postgres, Redis): [docker-compose.yml](docker-compose.yml)

1) Clonar y preparar entorno Python

```bash
git clone <repo>
cd inmo_helpdesk
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

2) Configurar variables de entorno
- El repositorio contiene un archivo `.env` unificado en la raíz. Ábrelo y edita los valores sensibles antes de ejecutar la aplicación:

```bash
# Edita .env con tu editor (ej. nano, code, notepad)
nano .env
# O crea una copia para pruebas locales:
cp .env .env.local
```

- Variables importantes (ya presentes en `.env`):
  - `SECRET_KEY` — cambiar por una clave segura
  - `DEBUG` — `True` para desarrollo
  - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
  - `CELERY_BROKER_URL` — por defecto `redis://127.0.0.1:6379/0`
  - `GEMINI_API_KEY` — clave para integración AI (opcional)
  - `EMAIL_*` — configurar si se usará envío real de correos

Nota sobre Docker: si usas `docker-compose up` (ver abajo), actualiza `DB_HOST` a `db` y `CELERY_BROKER_URL` a `redis://redis:6379/0` en `.env` (los nombres coinciden con los servicios del `docker-compose.yml`).

3) Iniciar dependencias con Docker Compose (opcional)

Si no quieres instalar Postgres/Redis localmente, usa Docker Compose:

```bash
docker-compose up -d
```

Esto levanta:
- Servicio `db` (Postgres) con usuario/clave según `docker-compose.yml`.
- Servicio `redis` (Redis).

4) Migraciones y usuario administrador

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py createsuperuser
```

5) Tailwind / assets estáticos (opcional pero recomendado para desarrollo frontend)

Instalar dependencias de Node y compilar CSS:

```bash
cd theme/static_src
npm install
# en desarrollo (watch):
npm run dev
# para generar CSS minificado (producción):
npm run build
cd -
```

Si no vas a tocar estilos, esto no es obligatorio para arrancar el backend.

6) Ejecutar la aplicación

En desarrollo (con el entorno Python activo y `.env` configurado):

```bash
python manage.py runserver
```

7) Ejecutar Celery (tareas asíncronas)

En un terminal aparte (con el `venv` activado):

```bash
celery -A config worker -l info
```

Notas:
- Si `CELERY_TASK_ALWAYS_EAGER=true` (en `.env`), las tareas se ejecutan en el proceso Django (útil para pruebas/desarrollo sin worker).
- El backend de resultados está configurado con `django-celery-results` (usa la base de datos).

8) Ejecutar pruebas

```bash
pytest
```

9) Producción / despliegue (puntos clave)
- Asegúrate de configurar `DEBUG=False`, `SECRET_KEY` seguro y `ALLOWED_HOSTS` apropiado en `.env`.
- Ejecutar `python manage.py collectstatic --noinput` antes de servir estáticos en producción.
- Revisar `EMAIL_*` para notificaciones reales.

10) Información adicional y referencias
-- Variables de entorno y comportamiento están en [config/settings.py](config/settings.py).
-- Archivo `.env` en la raíz: [.env](.env)

Si quieres, puedo:
- Añadir un Dockerfile para contenerizar la aplicación completa.
- Generar un `Makefile` o scripts de `dev` para automatizar los pasos.
- Ajustar el README con pasos de despliegue específicos (Heroku, DigitalOcean, etc.).

---
Archivo generado automáticamente por el asistente.
