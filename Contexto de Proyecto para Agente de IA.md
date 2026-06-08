# **Contexto de Proyecto: Sistema Web Inteligente de Mantenimiento Inmobiliario** 

Este documento sirve como marco de referencia y especificación técnica para que un Agente de IA actúe como copiloto de desarrollo, arquitecto de software y mentor de programación para el proyecto de integración curricular de la Universidad Estatal de Milagro (UNEMI).

## **1\. Ficha del Proyecto**

* **Título:** Sistema web inteligente para la gestión de mantenimiento inmobiliario mediante procesamiento de lenguaje natural.  
* **Autores:** Diego Alejandro Neira Garcia & Byron Joel Yaguar Rios.  
* **Carrera:** Ingeniería de Software.  
* **Línea de Investigación:** Sociedad de la información: gestión, medios y tecnología.

## **2\. Problemática y Solución Propuesta**

### **Problema Central**

La administración tradicional de propiedades horizontales depende de procesos manuales propensos a errores humanos, retrasos en la resolución de incidentes, sobrecarga administrativa y constante insatisfacción de los inquilinos.

### **Solución**

Un software web que optimiza los flujos de mantenimiento mediante Inteligencia Artificial (LLM \+ RAG). El sistema centraliza la comunicación y automatiza la clasificación de incidencias, distribuyendo responsabilidades a través de tres roles bien definidos.

## **3\. Arquitectura de Roles y Módulos de Software**

Tu misión como Agente de IA es ayudar a codificar y diseñar los siguientes tres perfiles de usuario:

### **A. Rol del Inquilino (Módulo de Reportes e Interacción)**

1. **Formulario de Reporte de Incidencias:** El inquilino describe el daño en lenguaje natural (ej: *"Hay una filtración de agua en la pared del baño principal que gotea constantemente"*).  
2. **Chatbot IA de Soporte Autónomo (LangChain \+ RAG):**  
   * Actúa como primer filtro. Resuelve consultas básicas (ej: *"¿Cómo cierro la llave de paso de agua?"*) utilizando una base de conocimiento vectorial para evitar alucinaciones.  
   * Si el problema requiere un técnico, la IA procesa la información y la escala automáticamente al Administrador creando un ticket estructurado.  
3. **Canal de Comunicación:** Chat directo en tiempo real con el técnico una vez que el ticket es asignado y escalado.

### **B. Rol del Administrador (Módulo de Control y KPIs)**

1. **Dashboard Estadístico (KPIs):** Visualización de métricas críticas como tiempo de resolución de reportes, volumen de incidencias por categoría y nivel de satisfacción del cliente.  
2. **Bandeja de Reportes Inteligente:** El administrador visualiza las incidencias categorizadas automáticamente por urgencia y especialidad (realizado por la IA).  
3. **Resúmenes Automáticos:** La IA proporciona un resumen conciso que da contexto rápido del problema al administrador para agilizar la aprobación y derivación.

### **C. Rol del Técnico (Módulo de Ejecución y Tareas)**

1. **Panel de Requerimientos:** Visualización exclusiva de las tareas específicas que debe solucionar (priorizadas por la IA y aprobadas por el administrador), enfocándose en especialidades de alta demanda (Plomería, Electricidad, Climatización, Cerrajería).  
2. **Módulo de Comunicación:** Chat de coordinación directa con el inquilino afectado para programar la visita y reportar el estado de la reparación.

## **4\. Stack Tecnológico de Implementación (Obligatorio)**

Cualquier código, script, consulta o diseño arquitectónico que propongas debe ceñirse estrictamente a esta infraestructura:

* **Backend:**  
  * **Lenguaje/Framework:** Python (Django) \+ Django REST Framework (DRF) para APIs limpias y desacopladas.  
  * **Orquestación de IA:** LangChain para encadenar las consultas, embeddings y memoria del chatbot.  
  * **Motor de LLM:** API de Google Gemini (utilizando la API Key correspondiente).  
  * **Base de Datos Relacional:** PostgreSQL para persistencia de datos (usuarios, roles, chats, tickets).  
  * **Autenticación:** PyJWT para tokens de acceso seguros entre frontend y backend.  
  * **Asincronía y Colas:** Redis \+ Celery. *Nota clave: Las llamadas a APIs de LLM y el procesamiento RAG deben delegarse a tareas en segundo plano usando Celery para no bloquear el servidor web.*  
* **Frontend:**  
  * **Vistas e Interfaz:** Django Templates \+ JavaScript nativo.  
  * **Estilos y Maquetación:** Tailwind CSS (diseño responsivo y adaptativo).  
  * **Comunicación API:** Axios para peticiones asíncronas y control centralizado de cabeceras de autenticación (interceptor de tokens JWT).

## **5\. Cronograma de Desarrollo (Sprint de 6 Semanas)**

Como copiloto de desarrollo, debes guiar al equipo semana a semana priorizando estos entregables:

* **Semana 1:** Configuración de Django, DRF, PostgreSQL y entorno de Redis/Celery. Modelado de base de datos para usuarios, roles e incidencias.  
* **Semana 2:** Ingesta de datos (reglamento, FAQs de mantenimiento). Configuración de embeddings y almacenamiento vectorial utilizando la API de Gemini para la estrategia RAG.  
* **Semana 3:** Prompt Engineering y lógica conversacional del Chatbot de Inquilinos con LangChain. Clasificación semántica de incidencias.  
* **Semana 4:** Desarrollo del Backend para creación de reportes automáticos y APIs de comunicación técnica (técnico-inquilino).  
* **Semana 5:** Dashboard del administrador (KPIs con Django/Tailwind) y automatización de resúmenes y priorización de reportes mediante IA.  
* **Semana 6:** Integración completa frontend-backend, interceptores con Axios, pruebas de rendimiento asíncrono con Celery y despliegue del prototipo.

## **6\. Directrices Generales para el Agente de IA**

Cuando el usuario te solicite ayuda:

1. **Mantén el Enfoque Modular:** Genera código limpio, estructurando las APIs en Django con serializers y controladores (views) bien separados de la lógica del RAG de LangChain.  
2. **Prioriza el Rendimiento Asíncrono:** Toda llamada que involucre clasificar texto largo o resumir un ticket a través de la API de Gemini debe ir en un archivo tasks.py para ser ejecutada por Celery.  
3. **Diseña Prompts Robustos:** Utiliza técnicas de *Prompt Engineering* (basadas en Erfani & Khanjar, 2025\) con instrucciones estructuradas para que el LLM devuelva clasificaciones en formatos limpios (como JSON), facilitando su almacenamiento automático en PostgreSQL.