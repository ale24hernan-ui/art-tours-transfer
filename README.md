# Artours Transfer SaaS - B2B Logistics Automation 🚐

Módulo SaaS transaccional "Mobile-First" desarrollado para la gestión logística de una flotilla de transporte turístico, reemplazando las operaciones basadas en macros de Excel por una arquitectura en la nube segura y escalable.

## 🎯 Contexto y Problema de Negocio
La dependencia de archivos locales de Excel limitaba la movilidad de los choferes en campo y generaba cuellos de botella administrativos. Los cierres de jornada requerían transcripción manual, exponiendo la operación a errores de captura y desajustes de tiempo por la suspensión de navegadores móviles.

## 💡 Solución Arquitectónica
Se desarrolló un backend en Python (Flask) integrado con PostgreSQL para centralizar el control operativo. 

### Características Principales:

| Innovación Técnica | Implementación y Propósito (El "Por qué" y "Para qué") |
| :--- | :--- |
| **Máquina de Estados Sincronizada** | Uso de Timestamps en SQL con `AT TIME ZONE 'America/Cancun'` para evadir la latencia de navegadores móviles y la desviación UTC del servidor. |
| **Gestión de Memoria RAM (`io.BytesIO`)** | Compilación de reportes financieros en PDF al vuelo mediante `FPDF`, sirviendo archivos binarios sin consumir almacenamiento en disco físico. |
| **Orquestación Dual B2B** | Webhooks transaccionales hacia `n8n` para el despacho SMTP simultáneo a la descarga del Blob nativo. |
| **Seguridad Perimetral** | Abstracción absoluta de credenciales (BD, JWT, n8n) mediante variables de entorno y `flask.session`. |

## 🛠️ Stack Tecnológico

| Categoría | Tecnologías Utilizadas |
| :--- | :--- |
| **Backend** | Python 3, Flask, Gunicorn |
| **Base de Datos** | PostgreSQL (Render) |
| **Automatización** | n8n (Webhooks HTTP) |
| **Librerías Clave** | `psycopg2-binary`, `fpdf`, `zoneinfo`, `urllib` |

## 🚀 Despliegue
Este proyecto está optimizado para su ejecución en contenedores o entornos PaaS (Render / Hetzner). Para ejecutar localmente:

| Paso | Acción Requerida | Comando o Detalle |
| :--- | :--- | :--- |
| **1. Clonar** | Descargar el repositorio localmente | `git clone [TU_URL_DE_GITHUB]` |
| **2. Dependencias** | Instalar las librerías necesarias | `pip install -r requirements.txt` |
| **3. Configuración** | Definir variables en un archivo `.env` | `DATABASE_URL`, `FLASK_SECRET_KEY`, `ADMIN_PASSWORD` |
| **4. Ejecución** | Levantar el servidor web | `python app.py` (o mediante gunicorn en producción) |
