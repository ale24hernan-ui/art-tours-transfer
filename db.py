# Importamos la librería del sistema operativo para leer variables.
# ¿Por qué y para qué?: Necesitamos extraer las credenciales de forma segura desde el entorno del servidor o el archivo .env, sin escribirlas directamente en el código.
import os

# Importamos el adaptador de PostgreSQL para Python.
# ¿Por qué y para qué?: Es el motor binario (driver) que traduce las instrucciones de Python a un lenguaje que la base de datos PostgreSQL pueda entender y ejecutar.
import psycopg2

# Importamos el cargador de variables de entorno.
# ¿Por qué y para qué?: En tu entorno local, fuerza a Python a leer el archivo oculto '.env' y cargar sus valores a la memoria RAM antes de intentar la conexión.
from dotenv import load_dotenv

# Ejecutamos la carga de variables.
# ¿Por qué y para qué?: Garantiza que las credenciales estén disponibles inmediatamente cuando la función de conexión sea invocada por app.py.
load_dotenv()

def obtener_conexion_db():
    # Extraemos la cadena de conexión (URI) del entorno.
    # ¿Por qué y para qué?: Al usar una URI (ej. postgresql://usuario:password@host/dbname), centralizamos host, puerto, usuario y contraseña en una sola variable dinámica, facilitando el cambio entre tu entorno local y el servidor de Render.
    database_url = os.environ.get("DATABASE_URL")
    
    # Validamos defensivamente la existencia de la credencial.
    # ¿Por qué y para qué?: Si olvidaste configurar el .env o Render pierde la variable, el servidor arrojará un error claro e intencional (ValueError) en lugar de colapsar con un fallo críptico de psycopg2.
    if not database_url:
        raise ValueError("Fallo Crítico: La variable de entorno DATABASE_URL no está configurada.")
        
    # Abrimos y retornamos la conexión física a PostgreSQL.
    # ¿Por qué y para qué?: Crea el "túnel" de red (socket) a través del cual app.py enviará las sentencias SQL (INSERT, UPDATE, SELECT). Esta conexión se mantendrá abierta solo durante la transacción y se cerrará en el bloque 'finally' de app.py.
    conexion = psycopg2.connect(database_url)
    return conexion