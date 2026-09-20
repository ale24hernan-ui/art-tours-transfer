# Importamos Flask para el servidor y render_template para enviar la interfaz HTML al usuario.
from flask import Flask, render_template

# Importamos psycopg2, el adaptador oficial que permite a Python comunicarse con PostgreSQL y ejecutar comandos SQL.
import psycopg2

# Importamos os, una librería nativa de Python para leer variables de entorno del sistema operativo.
import os

# Importamos load_dotenv para cargar credenciales secretas desde un archivo oculto, protegiendo las contraseñas.
from dotenv import load_dotenv

# Ejecutamos la función para cargar las variables de entorno en la memoria de la aplicación.
load_dotenv()

# Inicializamos la aplicación de Flask, indicando el directorio raíz del proyecto.
app = Flask(__name__)

# Definimos una función especializada para establecer la conexión con la base de datos.
# ¿Por qué?: Modularizar la conexión nos permite abrirla y cerrarla de forma segura cada vez que un cliente hace una reserva.
def obtener_conexion_db():
    # Establecemos la conexión utilizando una URL de conexión segura proporcionada por las variables de entorno.
    # El formato típico será: postgresql://usuario:contraseña@servidor:puerto/nombre_bd
    conexion = psycopg2.connect(os.getenv("DATABASE_URL"))
    # Devolvemos el objeto de conexión listo para ser utilizado por otras funciones.
    return conexion

# Definimos la ruta principal ('/') de nuestra página web.
@app.route('/')
def home():
    # Renderizamos y devolvemos el archivo index.html ubicado en la carpeta 'templates'.
    return render_template('index.html')

# Punto de entrada principal: verifica que el script se ejecute directamente.
if __name__ == '__main__':
    # Arrancamos el servidor local en modo debug por el puerto 5000 para facilitar el desarrollo.
    app.run(debug=True, port=5000)