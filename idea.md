# Documento de Formulación de Proyecto de Titulación
**Carrera:** Ingeniería de Software
**Tema:** Mesa de Ayuda Inteligente para Mantenimiento Inmobiliario

---

## 1. Resumen del Proyecto
El presente proyecto de Ingeniería de Software consiste en el diseño y desarrollo de una plataforma web de Mesa de Ayuda (Help Desk) especializada en el sector inmobiliario. Su principal innovación (I+D) radica en la integración de Inteligencia Artificial, específicamente un Modelo de Lenguaje Grande (LLM) a través de la API de Gemini, para procesar los reportes multimodales (texto e imágenes) de los inquilinos. El sistema automatiza la clasificación de incidentes, asigna prioridad y sugiere el técnico más adecuado, utilizando un enfoque "Human-in-the-Loop" donde el administrador valida las acciones, optimizando los tiempos de respuesta y la gestión operativa.

## 2. Planteamiento del Problema
La gestión tradicional de mantenimiento en condominios y edificios presenta ineficiencias operativas significativas:
* **Falta de estandarización en reportes:** Los inquilinos reportan daños de forma ambigua, lo que retrasa el diagnóstico.
* **Tiempos muertos en asignación:** Los administradores invierten demasiado tiempo clasificando manualmente los tickets y buscando al técnico adecuado.
* **Ausencia de trazabilidad en tiempo real:** Desconexión entre el reporte del usuario y el estado real del trabajo del técnico en campo.
* **Falta de datos históricos:** Imposibilidad de medir Acuerdos de Nivel de Servicio (SLA) y eficiencia del personal.

## 3. Objetivos del Proyecto

### Objetivo General
Desarrollar un sistema web basado en el framework Django para la gestión de mantenimiento inmobiliario, integrando un Modelo de Lenguaje Grande (LLM) a través de una API para la clasificación, priorización automatizada y asignación asistida de incidentes mediante procesamiento de lenguaje natural y visión computacional.

### Objetivos Específicos
1. **Diseñar la arquitectura de software** utilizando el patrón Modelo-Vista-Plantilla (MVT) en Django, definiendo el modelo de datos relacional para gestionar propiedades, usuarios, tickets y costos.
2. **Integrar la API de Inteligencia Artificial (Gemini)** diseñando prompts dinámicos que permitan el análisis multimodal de tickets para generar salidas estructuradas (JSON) con sugerencias de categorización y asignación.
3. **Desarrollar interfaces adaptativas y basadas en roles (RBAC)**, priorizando un enfoque *Mobile-First* para el flujo operativo de los técnicos en campo y dashboards analíticos para la administración.
4. **Implementar una máquina de estados discretos** para el ciclo de vida del ticket, permitiendo trazabilidad asíncrona sin dependencia de geolocalización en tiempo real.
5. **Evaluar la precisión de la IA y el impacto del sistema** mediante métricas de rendimiento y reducción de tiempos en el proceso de asignación (Asignación Asistida vs. Manual).

## 4. Arquitectura y Stack Tecnológico
* **Backend y Lógica de Negocio:** Python con el Framework Django.
* **Frontend:** Django Templates integrando HTMX (y opcionalmente Alpine.js) para lograr reactividad y asincronismo sin la complejidad de una Single Page Application (SPA).
* **Base de Datos:** PostgreSQL.
* **Inteligencia Artificial:** API de Gemini (Procesamiento Multimodal y Generación de JSON estructurado).
* **Procesamiento Asíncrono:** Celery o Django-Q (para manejar la latencia de las peticiones a la API de IA sin bloquear la interfaz del usuario).

## 5. Roles y Reglas de Negocio
El sistema implementa Control de Acceso Basado en Roles (RBAC) estructurado en tres perfiles principales:

### A. Inquilino (Usuario Final)
* **Funciones:** Generar reportes multimodales (texto + fotos), revisar el análisis preliminar de la IA, hacer seguimiento de estados y calificar el servicio.
* **Regla de Negocio:** El inquilino no clasifica su problema (infraestructura, plomería, etc.), delega esta fricción a la IA.

### B. Administrador (Gestor Operativo)
* **Funciones:** Validar el diagnóstico de la IA, confirmar o modificar la asignación sugerida de técnicos (Human-in-the-Loop), auditar los costos y visualizar métricas de eficiencia.
* **Métricas Clave:** Tiempo Medio de Respuesta (MTTR), Tasa de Acierto de la IA, Carga de trabajo y calificaciones de técnicos.

### C. Técnico (Operario de Campo)
* **Funciones:** Recibir órdenes de trabajo asignadas, actualizar estados discretos de la reparación y subir evidencias (fotos/notas).
* **Regla de Negocio:** Su interfaz debe ser estrictamente *Mobile-First*. Al cerrar el ticket, imputa los gastos lógicamente a `[Administración]` o `[Inquilino]` para auditoría posterior.

## 6. Flujo del Sistema (Máquina de Estados del Ticket)
El ciclo de vida de un incidente sigue un flujo de estados discretos diseñados para el seguimiento en tiempo real asíncrono:

1. `CREADO_PENDIENTE_IA`: El usuario envía el formulario. Tarea asíncrona enviada a Gemini.
2. `ANALIZADO_POR_IA`: Gemini devuelve clasificación y sugerencia de técnico.
3. `PENDIENTE_VALIDACION`: El Administrador revisa la sugerencia y aprueba/modifica (Asignación Asistida).
4. `ASIGNADO`: El técnico recibe la notificación en su bandeja de entrada móvil.
5. `EN_CAMINO`: El técnico acepta e inicia el desplazamiento.
6. `EN_PROGRESO`: El técnico se encuentra ejecutando la reparación en el sitio.
7. `RESUELTO`: Técnico sube foto final, notas y asigna a quién corresponde el costo del material/servicio. Ticket se cierra y se habilita la calificación del inquilino.