# ¿Por qué y para qué?: Importamos 'os' para leer variables de entorno del sistema operativo (credenciales y llaves secretas).
import os
# ¿Por qué y para qué?: Importamos 'io' para gestionar flujos de bytes en memoria RAM (BytesIO) al generar archivos PDF sin escribir en disco.
import io
# ¿Por qué y para qué?: Importamos 'base64' y 'json' para serialización de datos y manejo de payloads en peticiones asíncronas.
import base64
import json
# ¿Por qué y para qué?: Importamos submódulos de 'urllib' para codificar parámetros de URL (como los mensajes prellenados hacia la API de WhatsApp).
import urllib.parse
import urllib.request
import urllib.error
# ¿Por qué y para qué?: Importamos 'wraps' de functools para preservar metadatos en decoradores si escalamos middlewares de seguridad.
from functools import wraps
# ¿Por qué y para qué?: Importamos 'datetime' y 'timedelta' para aritmética de fechas, validación de ventanas operativas y marcas de tiempo.
from datetime import datetime, timedelta
# ¿Por qué y para qué?: Importamos 'ZoneInfo' para forzar la zona horaria oficial de Quintana Roo ('America/Cancun') independientemente de la ubicación del servidor en Render.
from zoneinfo import ZoneInfo
# ¿Por qué y para qué?: Importamos los objetos esenciales de Flask para enrutamiento web, renderizado Jinja2, sesiones, envíos de archivos y respuestas JSON.
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify, flash
# ¿Por qué y para qué?: Importamos 'FPDF' para la construcción programática de documentos PDF (Corte de Caja y Manifiesto Alianza).
from fpdf import FPDF
# ¿Por qué y para qué?: Importamos el conector modular a PostgreSQL para mantener separada la capa de persistencia.
from db import obtener_conexion_db

# ¿Por qué y para qué?: Instanciamos la aplicación principal de Flask indicando el módulo actual como raíz.
app = Flask(__name__)
# ¿Por qué y para qué?: Asignamos la llave criptográfica desde las variables de entorno para firmar de forma segura las cookies de sesión.
app.secret_key = os.environ.get("FLASK_SECRET_KEY")


# ========================================================
# RUTA PÚBLICA (ESCAPARATE B2C)
# ========================================================
# ¿Por qué y para qué?: Definimos el endpoint raíz '/' que sirve la landing page pública a los turistas/clientes.
@app.route('/')
def index():
    # ¿Por qué y para qué?: Inicializamos las referencias de conexión y cursor en None para garantizar un cierre seguro en el bloque 'finally'.
    conn = None
    cursor = None
    # ¿Por qué y para qué?: Inicializamos una lista vacía como respaldo (fallback) por si ocurre una intermitencia en la base de datos.
    puntos = []
    try:
        # ¿Por qué y para qué?: Abrimos la conexión hacia PostgreSQL y creamos el cursor de ejecución SQL.
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Consultamos el catálogo de destinos ordenado alfabéticamente para alimentar los selectores del formulario B2C.
        cursor.execute("SELECT nombre_destino FROM puntos_interes ORDER BY nombre_destino ASC")
        # ¿Por qué y para qué?: Transformamos las tuplas devueltas por PostgreSQL en una lista plana de strings mediante list comprehension.
        puntos = [fila[0] for fila in cursor.fetchall()]
        
    except Exception as e:
        # ¿Por qué y para qué?: Registramos cualquier fallo en consola sin derribar la carga de la página principal (código defensivo).
        print(f"Error cargando puntos de interés en el Home: {e}")
    finally:
        # ¿Por qué y para qué?: Liberamos el cursor y devolvemos la conexión al sistema para evitar fugas de memoria o bloqueos en PostgreSQL.
        if cursor: cursor.close()
        if conn: conn.close()
        
    # ¿Por qué y para qué?: Renderizamos la plantilla 'index.html' inyectando el catálogo de ubicaciones.
    return render_template('index.html', puntos_interes=puntos)


# ========================================================
# RUTAS DE RESERVA PÚBLICA Y AUTENTICACIÓN
# ========================================================
# ¿Por qué y para qué?: Definimos la ruta POST que procesa el formulario de cotización/reserva desde la web pública.
@app.route('/reservar', methods=['POST'])
def reservar():
    # ¿Por qué y para qué?: Extraemos los campos enviados en el form-data del cliente desde el navegador.
    nombre = request.form.get('nombre')
    pasajeros = request.form.get('pasajeros')
    origen = request.form.get('origen')
    destino = request.form.get('destino')
    fecha_hora = request.form.get('fecha_hora')
    # ¿Por qué y para qué?: Asignamos valores por defecto ('N/A' y 'Ninguno') si el pasajero deja opcionales vacíos.
    numero_vuelo = request.form.get('numero_vuelo', 'N/A')
    cupon = request.form.get('cupon', 'Ninguno')
    vehiculo_asignado = request.form.get('vehiculo_asignado')
    
    # ¿Por qué y para qué?: Declaramos variables de control de base de datos antes del bloque transaccional.
    conn = None
    cursor = None
    
    try:
        # ¿Por qué y para qué?: Conectamos a PostgreSQL para registrar tanto al cliente como su reserva en una sola transacción atómica.
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Insertamos primero en la tabla 'clientes' (3NF) y recuperamos la llave primaria generada con RETURNING.
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono, correo_electronico) 
            VALUES (%s, %s, %s) 
            RETURNING id_cliente
        """, (nombre, 'Obtenido vía WA', 'N/A'))
        # ¿Por qué y para qué?: Extraemos el 'id_cliente' recién creado para vincularlo como llave foránea en 'reservas'.
        id_cliente = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Insertamos el registro operativo en la tabla 'reservas' con estado inicial 'Pendiente'.
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, fecha_hora_servicio, numero_pasajeros, numero_vuelo, cupon, estado_reserva) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pendiente')
            RETURNING id_reserva
        """, (id_cliente, origen, destino, fecha_hora, pasajeros, numero_vuelo, cupon))
        # ¿Por qué y para qué?: Obtenemos el número de folio único ('id_reserva') para incluirlo en el mensaje de WhatsApp.
        id_reserva = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Confirmamos permanentemente ambos INSERT en la base de datos.
        conn.commit()
        
        # ¿Por qué y para qué?: Construimos la plantilla del mensaje comercial con todos los metadatos de la reserva y su folio.
        mensaje = f"Hola, soy {nombre}. Solicito un traslado de {origen} a {destino} para {pasajeros} pasajeros (Unidad: {vehiculo_asignado}) el día {fecha_hora}. Vuelo: {numero_vuelo}. Cupón: {cupon}. Folio interno: #{id_reserva}."
        # ¿Por qué y para qué?: Codificamos espacios y caracteres especiales en formato URL-safe (%20, etc.).
        mensaje_codificado = urllib.parse.quote(mensaje)
        # ¿Por qué y para qué?: Definimos el número receptor oficial de Art-Tours Transfer para cierre de venta.
        numero_empresa = "5219982156446"
        # ¿Por qué y para qué?: Ensamblamos el enlace hacia la API de WhatsApp Web / App móvil.
        url_whatsapp = f"https://wa.me/{numero_empresa}?text={mensaje_codificado}"
        
        # ¿Por qué y para qué?: Redirigimos al usuario directamente hacia el chat de WhatsApp con su solicitud lista para enviar.
        return redirect(url_whatsapp)
        
    except Exception as e:
        # ¿Por qué y para qué?: Si ocurre cualquier error SQL, revertimos la transacción (rollback) para no dejar clientes huérfanos sin reserva.
        if conn: conn.rollback()
        return f"Error interno al procesar la reserva: {str(e)}", 500
    finally:
        # ¿Por qué y para qué?: Cerramos recursos de base de datos de forma garantizada.
        if cursor: cursor.close()
        if conn: conn.close()


# ¿Por qué y para qué?: Definimos la ruta de acceso administrativo soportando GET (mostrar formulario) y POST (validar credenciales).
@app.route('/login', methods=['GET', 'POST'])
def login():
    # ¿Por qué y para qué?: Verificamos si el administrador está enviando el formulario de acceso.
    if request.method == 'POST':
        # ¿Por qué y para qué?: Obtenemos la contraseña capturada en el input HTML.
        password_ingresada = request.form.get('password')
        # ¿Por qué y para qué?: Comparamos contra la variable de entorno segura configurada en el servidor.
        if password_ingresada == os.environ.get("ADMIN_PASSWORD"):
            # ¿Por qué y para qué?: Activamos la bandera de sesión autenticada y fijamos el ID del chofer titular (1 = Arturo Monroy).
            session['admin_logeado'] = True
            session['id_chofer'] = 1 
            # ¿Por qué y para qué?: Redirigimos al centro de control operativo.
            return redirect(url_for('panel_admin'))
        else:
            # ¿Por qué y para qué?: Enviamos retroalimentación visual si la contraseña no coincide.
            flash("Contraseña incorrecta. Intente de nuevo.")
            return render_template('login.html')
            
    # ¿Por qué y para qué?: Si la petición es GET, servimos la vista de login.
    return render_template('login.html')


# ========================================================
# 1. PANEL ADMINISTRATIVO PRINCIPAL (SELECT EXPANDIDO)
# ========================================================
# ¿Por qué y para qué?: Ruta principal de operación diaria para visualizar y gestionar viajes activos.
@app.route('/admin')
def panel_admin():
    # ¿Por qué y para qué?: Guardián de seguridad que bloquea el acceso sin sesión activa redirigiendo a '/login'.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    # ¿Por qué y para qué?: Inicializamos estructuras de datos para viajes y catálogo de puntos de interés.
    conn = None
    cursor = None
    viajes = []
    puntos = []
    
    try:
        # ¿Por qué y para qué?: Establecemos conexión con PostgreSQL.
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Consultamos todos los campos de 'reservas' y de 'clientes' (incluyendo 'correo_electronico' e 'id_cliente')
        # además de calcular 'fecha_corte' con TO_CHAR para agrupar visualmente la agenda por día en 'admin.html'.
        cursor.execute("""
            SELECT r.id_reserva, r.id_cliente, c.nombre_completo, c.telefono, c.correo_electronico,
                   r.origen, r.destino, r.fecha_hora_servicio,
                   TO_CHAR(r.fecha_hora_servicio, 'YYYY-MM-DD') AS fecha_corte,
                   r.numero_pasajeros, r.estado_reserva, r.precio,
                   r.hotel_referencia, r.numero_vuelo, r.estado_pago,
                   r.cupon, r.notas
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.estado_reserva IN ('Pendiente', 'En_Progreso')
            ORDER BY r.fecha_hora_servicio ASC
        """)
        
        # ¿Por qué y para qué?: Extraemos los nombres de las columnas del cursor para construir una lista de diccionarios clave-valor para Jinja2.
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]

        # ¿Por qué y para qué?: Cargamos también los puntos de interés para que el modal de Registro Manual tenga autocompletado en Origen/Destino.
        cursor.execute("SELECT nombre_destino FROM puntos_interes ORDER BY nombre_destino ASC")
        puntos = [fila[0] for fila in cursor.fetchall()]
        
    except Exception as e:
        # ¿Por qué y para qué?: Imprimimos cualquier anomalía SQL en los logs del servidor para diagnóstico inmediato.
        print(f"Error de base de datos en Panel Admin: {e}")
    finally:
        # ¿Por qué y para qué?: Cerramos recursos de conexión.
        if cursor: cursor.close()
        if conn: conn.close()
        
    # ¿Por qué y para qué?: Renderizamos 'admin.html' entregando tanto los viajes activos como la lista de destinos.
    return render_template('admin.html', viajes=viajes, puntos_interes=puntos)


# ========================================================
# RUTA DE HISTORIAL OPERATIVO
# ========================================================
# ¿Por qué y para qué?: Endpoint para auditar viajes pasados filtrados por fecha específica.
@app.route('/admin/historial', methods=['GET'])
def historial_operativo():
    # ¿Por qué y para qué?: Verificamos sesión activa del administrador.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    # ¿Por qué y para qué?: Leemos el parámetro '?fecha=YYYY-MM-DD' de la URL; si no existe, usamos la fecha actual de Cancún.
    fecha_solicitada = request.args.get('fecha')
    if not fecha_solicitada:
        fecha_solicitada = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
    conn = None
    cursor = None
    viajes = []
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Consultamos todos los viajes cuya fecha de servicio coincida con el día seleccionado.
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, c.telefono, c.correo_electronico,
                   r.origen, r.destino, r.precio, r.estado_reserva
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.fecha_hora_servicio::text LIKE %s
            ORDER BY r.id_reserva DESC
        """, (f"{fecha_solicitada}%",))
        
        # ¿Por qué y para qué?: Convertimos cada fila en un diccionario accesible desde la plantilla 'historial.html'.
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error cargando el historial: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    return render_template('historial.html', viajes=viajes, fecha_actual=fecha_solicitada)


# ========================================================
# 2. CRUD MAESTRO 360° (RESERVAS + CLIENTES)
# ========================================================
# ¿Por qué y para qué?: Permite editar todos los datos del viaje y del cliente, o cancelar/reactivar un folio desde el botón de engrane.
@app.route('/admin/viaje/<int:id_reserva>/master_edit', methods=['POST'])
def master_edit_viaje(id_reserva):
    # ¿Por qué y para qué?: Validamos que quien ejecuta la petición JSON tenga sesión activa.
    if not session.get('admin_logeado'):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401

    # ¿Por qué y para qué?: Extraemos el cuerpo JSON enviado por Fetch API desde 'admin.html'.
    datos = request.json or {}
    accion = datos.get('accion')
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        if accion == 'editar':
            # ¿Por qué y para qué?: Sanitizamos el valor numérico del precio para evitar errores si el campo se envía vacío.
            precio_raw = datos.get('precio')
            precio_val = float(precio_raw) if (precio_raw not in [None, '', 'None']) else 0.0
            # ¿Por qué y para qué?: Sanitizamos el número de pasajeros asegurando un entero válido (mínimo 1).
            pax_raw = datos.get('numero_pasajeros')
            pax_val = int(pax_raw) if (pax_raw not in [None, '', 'None']) else 1

            # ¿Por qué y para qué?: Actualizamos los campos logísticos y financieros en la tabla 'reservas'.
            cursor.execute("""
                UPDATE reservas 
                SET origen = %s, destino = %s, precio = %s, 
                    hotel_referencia = %s, numero_vuelo = %s, 
                    fecha_hora_servicio = %s, numero_pasajeros = %s, 
                    estado_pago = %s, cupon = %s, notas = %s
                WHERE id_reserva = %s
                RETURNING id_cliente
            """, (
                datos.get('origen'), datos.get('destino'), precio_val,
                datos.get('hotel_referencia'), datos.get('numero_vuelo'),
                datos.get('fecha_hora_servicio'), pax_val,
                datos.get('estado_pago'), datos.get('cupon'), datos.get('notas'),
                id_reserva
            ))
            fila_reserva = cursor.fetchone()

            # ¿Por qué y para qué?: Si la reserva tiene un 'id_cliente' asociado, actualizamos también sus datos en la tabla 'clientes'.
            if fila_reserva and fila_reserva[0]:
                id_cliente_asociado = fila_reserva[0]
                nombre_cli = (datos.get('nombre_completo') or '').strip() or 'Cliente Exprés'
                telefono_cli = (datos.get('telefono') or '').strip() or 'N/A'
                correo_cli = (datos.get('correo_electronico') or '').strip() or 'N/A'

                cursor.execute("""
                    UPDATE clientes
                    SET nombre_completo = %s, telefono = %s, correo_electronico = %s
                    WHERE id_cliente = %s
                """, (nombre_cli, telefono_cli, correo_cli, id_cliente_asociado))

        elif accion == 'cancelar':
            # ¿Por qué y para qué?: Cambiamos el estado a 'Cancelado' para sacarlo de la cola operativa sin borrar el registro histórico.
            cursor.execute("UPDATE reservas SET estado_reserva = 'Cancelado' WHERE id_reserva = %s", (id_reserva,))
        elif accion == 'reactivar':
            # ¿Por qué y para qué?: Permite reincorporar un viaje cancelado o finalizado de vuelta al estado 'Pendiente'.
            cursor.execute("UPDATE reservas SET estado_reserva = 'Pendiente' WHERE id_reserva = %s", (id_reserva,))
            
        # ¿Por qué y para qué?: Confirmamos los cambios en la base de datos.
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ========================================================
# 3. REGISTRO MANUAL COMPLETO (TABLA CLIENTES + RESERVAS)
# ========================================================
# ¿Por qué y para qué?: Endpoint que resuelve el Problema 1 insertando los datos reales del cliente en 'clientes' y vinculándolos a 'reservas'.
@app.route('/admin/viaje/manual', methods=['POST'])
def registrar_viaje_manual():
    # ¿Por qué y para qué?: Verificamos que la sesión de administrador esté activa antes de permitir inserciones.
    if not session.get('admin_logeado'):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401

    # ¿Por qué y para qué?: Leemos el payload JSON enviado desde el modal 'Registro Manual' en 'admin.html'.
    datos = request.json or {}
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Extraemos y limpiamos los 3 atributos correspondientes a la tabla 'clientes' (nombre_completo, telefono, correo_electronico).
        nombre_cliente = (datos.get('nombre_completo') or '').strip() or 'Cliente Exprés (Manual)'
        telefono_cliente = (datos.get('telefono') or '').strip() or 'N/A'
        correo_cliente = (datos.get('correo_electronico') or '').strip() or 'N/A'

        # ¿Por qué y para qué?: Insertamos el registro real en la tabla 'clientes' respetando el modelo relacional y obtenemos su 'id_cliente'.
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono, correo_electronico)
            VALUES (%s, %s, %s)
            RETURNING id_cliente
        """, (nombre_cliente, telefono_cliente, correo_cliente))
        id_cliente = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Convertimos de forma segura 'precio' y 'pasajeros' a tipos numéricos válidos para PostgreSQL.
        precio_raw = datos.get('precio')
        precio_val = float(precio_raw) if (precio_raw not in [None, '', 'None']) else 0.0
        pax_raw = datos.get('pasajeros')
        pax_val = int(pax_raw) if (pax_raw not in [None, '', 'None']) else 1

        # ¿Por qué y para qué?: Insertamos la reserva vinculada al 'id_cliente' recién creado y asignamos 'id_chofer = 1' por defecto.
        cursor.execute("""
            INSERT INTO reservas (
                id_cliente, id_chofer, origen, destino, numero_pasajeros, fecha_hora_servicio, 
                precio, hotel_referencia, numero_vuelo, estado_pago, cupon, notas, estado_reserva
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pendiente')
        """, (
            id_cliente, session.get('id_chofer', 1), datos.get('origen'), datos.get('destino'),
            pax_val, datos.get('fecha_hora'), precio_val, datos.get('hotel_referencia'), 
            datos.get('numero_vuelo'), datos.get('estado_pago', 'Pago_Pendiente'), 
            datos.get('cupon'), datos.get('notas')
        ))
        
        # ¿Por qué y para qué?: Confirmamos la transacción dual (cliente + reserva) en PostgreSQL.
        conn.commit()
        return jsonify({"status": "success"})
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ========================================================
# CONTROL DE FLUJO DE VIAJES (INICIAR Y FINALIZAR)
# ========================================================
# ¿Por qué y para qué?: Cambia el estado del viaje a 'En_Progreso' y registra la marca de tiempo exacta de inicio en horario de Cancún.
@app.route('/admin/iniciar_viaje/<int:id_reserva>', methods=['POST'])
def iniciar_viaje_seguro(id_reserva):
    id_chofer_actual = session.get('id_chofer', 1)
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        # ¿Por qué y para qué?: Verificamos si el chofer ya tiene otro viaje 'En_Progreso' para evitar colisiones operativas.
        cursor.execute("SELECT id_reserva FROM reservas WHERE id_chofer = %s AND estado_reserva = 'En_Progreso'", (id_chofer_actual,))
        viaje_activo = cursor.fetchone()
        
        if viaje_activo:
            cursor.execute("SELECT fecha_hora_servicio FROM reservas WHERE id_reserva = %s", (id_reserva,))
            proximo_viaje = cursor.fetchone()
            if proximo_viaje and proximo_viaje[0]:
                hora_proximo_viaje = proximo_viaje[0]
                hora_actual = datetime.now(ZoneInfo('America/Cancun'))
                if hora_proximo_viaje.tzinfo is None:
                    hora_proximo_viaje = hora_proximo_viaje.replace(tzinfo=ZoneInfo('America/Cancun'))
                
                diferencia = hora_proximo_viaje - hora_actual
                # ¿Por qué y para qué?: Si faltan 5 minutos o menos para el nuevo viaje, cerramos automáticamente el anterior.
                if diferencia <= timedelta(minutes=5):
                    cursor.execute("UPDATE reservas SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (viaje_activo[0],))
                else:
                    return jsonify({"status": "blocked", "mensaje": "Tienes un viaje activo. Finalízalo antes de iniciar otro."}), 403
        
        # ¿Por qué y para qué?: Actualizamos el viaje actual a 'En_Progreso', asignamos el chofer y guardamos 'hora_inicio_real'.
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'En_Progreso', 
                id_chofer = %s,
                hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun' 
            WHERE id_reserva = %s
        """, (id_chofer_actual, id_reserva))
        conn.commit()
        return jsonify({"status": "success", "mensaje": "Viaje iniciado."})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ¿Por qué y para qué?: Cierra el viaje, actualiza el precio/ruta real cobrada y marca el estado de pago como 'Pagado'.
@app.route('/admin/viaje/<int:id_reserva>/finalizar_edicion', methods=['POST'])
def finalizar_viaje_con_edicion(id_reserva):
    datos = request.json or {}
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        precio_raw = datos.get('precio')
        precio_val = float(precio_raw) if (precio_raw not in [None, '', 'None']) else 0.0

        # ¿Por qué y para qué?: Guardamos origen, destino, precio final, estado 'Finalizado', estado_pago 'Pagado' y hora exacta de término.
        cursor.execute("""
            UPDATE reservas 
            SET origen = %s, destino = %s, precio = %s, 
                estado_reserva = 'Finalizado', 
                estado_pago = 'Pagado',
                hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE id_reserva = %s
        """, (datos.get('origen'), datos.get('destino'), precio_val, id_reserva))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ========================================================
# 4. CORTE DE CAJA DIARIO E HISTORIAL (FPDF)
# ========================================================
@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    datos = request.json or {}
    fecha_solicitada = datos.get('fecha')
    
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        if fecha_solicitada:
            # ¿Por qué y para qué?: Si viene parámetro 'fecha', consultamos únicamente los servicios de esa fecha histórica.
            cursor.execute("""
                SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD'), TO_CHAR(hora_inicio_real, 'HH24:MI'), 
                       TO_CHAR(hora_fin_real, 'HH24:MI'), EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)), 
                       origen, destino, hotel_referencia, id_reserva, cupon, precio 
                FROM reservas 
                WHERE estado_reserva = 'Finalizado' AND hora_inicio_real::DATE = %s::DATE
            """, (fecha_solicitada,))
            fecha_reporte = fecha_solicitada
        else:
            # ¿Por qué y para qué?: Si es el cierre del día actual, finalizamos los viajes en curso y extraemos el corte de hoy.
            cursor.execute("""
                UPDATE reservas 
                SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' 
                WHERE estado_reserva = 'En_Progreso' AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE
            """)
            cursor.execute("""
                SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD'), TO_CHAR(hora_inicio_real, 'HH24:MI'), 
                       TO_CHAR(hora_fin_real, 'HH24:MI'), EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)), 
                       origen, destino, hotel_referencia, id_reserva, cupon, precio 
                FROM reservas 
                WHERE estado_reserva = 'Finalizado' AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE
            """)
            fecha_reporte = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
            
        viajes_hoy = cursor.fetchall()
        conn.commit()

        pdf = FPDF('L', 'mm', 'Letter')
        pdf.add_page()
        ruta_logo = os.path.join(app.root_path, 'static', 'images', 'logo-transfers.png')
        if os.path.exists(ruta_logo): pdf.image(ruta_logo, x=10, y=8, w=35)
        pdf.ln(15) 
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 8, 'RELACION DE SERVICIOS DE ART TOURS TRANSFERS S.A. DE C.V', ln=1, align='C')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, f'PERIODO: {fecha_reporte}', ln=1, align='C')
        pdf.ln(8)
        
        pdf.set_fill_color(31, 73, 125)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 8)
        headers = ['Fecha', 'Hora Inicio', 'Hora Fin', 'Tiempo Total', 'Lugar Inicio', 'Lugar Destino', 'Hotel', 'Folio', 'Cupón', 'Precio']
        anchos = [22, 22, 18, 24, 33, 33, 40, 15, 22, 25]
        for i, h in enumerate(headers):
            pdf.cell(anchos[i], 8, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', fill=True)
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Arial', '', 8)
        total_ingresos_mxn = 0.0

        for fila in viajes_hoy:
            f_str, h_in, h_fin, t_seg, org, dst, hot, fol, cup, prec = fila
            t_str = f"{int(t_seg//3600):02d}:{int((t_seg%3600)//60):02d} h" if t_seg else "N/A"
            p_val = float(prec) if prec else 0.0
            total_ingresos_mxn += p_val
            def lmp(t, m): return str(t or 'N/A')[:m].encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(anchos[0], 8, str(f_str or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[1], 8, str(h_in or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[2], 8, str(h_fin or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[3], 8, t_str, 1, 0, 'C')
            pdf.cell(anchos[4], 8, lmp(org, 20), 1, 0, 'L')
            pdf.cell(anchos[5], 8, lmp(dst, 20), 1, 0, 'L')
            pdf.cell(anchos[6], 8, lmp(hot, 25), 1, 0, 'L')
            pdf.cell(anchos[7], 8, str(fol), 1, 0, 'C')
            pdf.cell(anchos[8], 8, lmp(cup, 12), 1, 0, 'C')
            pdf.cell(anchos[9], 8, f'${p_val:,.2f}', 1, 0, 'R')
            pdf.ln()

        pdf.ln(10)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(sum(anchos[:-1]) - 5, 10, 'INGRESO TOTAL DEL PERIODO:', 0, 0, 'R')
        pdf.set_text_color(31, 73, 125) 
        pdf.cell(anchos[-1] + 5, 10, f'${total_ingresos_mxn:,.2f} MXN', 0, 1, 'R')
        
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        return send_file(salida_pdf, as_attachment=True, download_name=f'Corte_Caja_{fecha_reporte}.pdf', mimetype='application/pdf')
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ========================================================
# 5. GENERADOR DE MANIFIESTO EJECUTIVO (SOLUCIÓN PROBLEMA 2)
# ========================================================
# ¿Por qué y para qué?: Genera el PDF Manifiesto_Alianza_Folio con diseño ejecutivo, datos completos de la reserva, del cliente y del conductor asignado.
@app.route('/admin/viaje/<int:id_reserva>/manifiesto_pdf', methods=['GET'])
def generar_manifiesto_individual(id_reserva):
    # ¿Por qué y para qué?: Validamos sesión administrativa para proteger los datos personales de los pasajeros.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))

    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Consultamos la totalidad de columnas de 'reservas' y 'clientes' para mostrar un documento completo y sin omisiones.
        cursor.execute("""
            SELECT r.id_reserva, r.origen, r.destino, r.hotel_referencia, r.numero_vuelo,
                   r.fecha_hora_servicio, r.numero_pasajeros, r.estado_reserva,
                   r.estado_pago, r.precio, r.cupon, r.notas,
                   c.nombre_completo, c.telefono, c.correo_electronico
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.id_reserva = %s
        """, (id_reserva,))
        viaje = cursor.fetchone()
        
        # ¿Por qué y para qué?: Si el folio no existe en la base de datos, devolvemos un código HTTP 404 controlado.
        if not viaje:
            return "Viaje no encontrado", 404

        # ¿Por qué y para qué?: Desempaquetamos los 15 campos de la tupla SQL en variables semánticas claras.
        (fol_id, origen, destino, hotel_ref, num_vuelo,
         fecha_hr, num_pax, est_reserva, est_pago, precio,
         cupon, notas, cli_nombre, cli_tel, cli_correo) = viaje

        # ¿Por qué y para qué?: Definimos una función sanitizadora a codificación 'latin-1' para que acentos y eñes no rompan FPDF.
        def txt_pdf(valor, max_len=None, default='N/A'):
            cadena = str(valor if (valor not in [None, '', 'None']) else default).strip()
            if max_len:
                cadena = cadena[:max_len]
            return cadena.encode('latin-1', 'replace').decode('latin-1')

        # ¿Por qué y para qué?: Inicializamos el lienzo PDF en orientación Horizontal ('L'), milímetros ('mm') y formato Carta ('Letter': 279.4 x 215.9 mm).
        pdf = FPDF('L', 'mm', 'Letter')
        # ¿Por qué y para qué?: Fijamos márgenes simétricos de 10mm (ancho útil exacto de 260mm).
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()

        # --------------------------------------------------------
        # SECCIÓN A: ENCABEZADO CORPORATIVO, LOGOS Y FOLIO
        # --------------------------------------------------------
        # ¿Por qué y para qué?: Dibujamos un cintillo superior azul marino corporativo para dar jerarquía visual inmediata al documento.
        pdf.set_fill_color(18, 48, 89)
        pdf.rect(10, 10, 260, 28, 'F')

        # ¿Por qué y para qué?: Insertamos los logotipos institucionales si están presentes en la carpeta 'static/images/'.
        ruta_logo_turq = os.path.join(app.root_path, 'static', 'images', 'turqueza.png')
        ruta_logo_safe = os.path.join(app.root_path, 'static', 'images', 'safe-travels.png')
        ruta_logo_att = os.path.join(app.root_path, 'static', 'images', 'logo-transfers.png')

        if os.path.exists(ruta_logo_turq):
            pdf.image(ruta_logo_turq, x=14, y=13, w=38)
        elif os.path.exists(ruta_logo_att):
            pdf.image(ruta_logo_att, x=14, y=13, w=32)

        if os.path.exists(ruta_logo_safe):
            pdf.image(ruta_logo_safe, x=55, y=13, w=24)

        # ¿Por qué y para qué?: Posicionamos el cursor en el bloque central-derecho del encabezado para los datos fiscales de la alianza.
        pdf.set_xy(82, 12)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 13)
        pdf.cell(125, 6, txt_pdf('CANCUN TURQUEZA TRANSFERS S.A. DE C.V.'), 0, 1, 'L')

        pdf.set_x(82)
        pdf.set_font('Arial', '', 8)
        pdf.cell(125, 5, txt_pdf('DIRECCIÓN FISCAL: SM 76 M 23 L 12 CALLE 62 C.P. 77527 | CANCÚN, QUINTANA ROO'), 0, 1, 'L')

        pdf.set_x(82)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(125, 5, txt_pdf('RFC: CTT171213QS1   |   ALIANZA OPERATIVA: ART-TOURS TRANSFERS'), 0, 1, 'L')

        pdf.set_x(82)
        pdf.set_font('Arial', 'I', 8)
        pdf.set_text_color(0, 191, 255)
        pdf.cell(125, 5, txt_pdf('MANIFIESTO OFICIAL DE SERVICIO Y AUTORIZACIÓN DE ACCESO HOTELERO'), 0, 1, 'L')

        # ¿Por qué y para qué?: Creamos una caja destacada en la esquina superior derecha para el Número de Folio y Fecha de Emisión.
        pdf.set_fill_color(0, 191, 255)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(212, 13)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(54, 8, txt_pdf(f'FOLIO #{fol_id:04d}'), 0, 1, 'C', fill=True)

        fecha_emision = datetime.now(ZoneInfo('America/Cancun')).strftime("%d/%m/%Y %H:%M")
        pdf.set_xy(212, 22)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 7)
        pdf.cell(54, 6, txt_pdf(f'EMISIÓN: {fecha_emision}'), 0, 1, 'C', fill=True)

        pdf.set_xy(212, 29)
        pdf.set_fill_color(235, 243, 250)
        pdf.cell(54, 6, txt_pdf(f'ESTADO: {str(est_reserva).upper()}'), 0, 1, 'C', fill=True)

        # ¿Por qué y para qué?: Bajamos el cursor debajo del banner principal para iniciar los bloques de información.
        pdf.set_y(43)

        # --------------------------------------------------------
        # SECCIÓN B: BLOQUES LADO A LADO (CLIENTE VS CONDUCTOR/UNIDAD)
        # --------------------------------------------------------
        # ¿Por qué y para qué?: Guardamos la coordenada Y inicial para dibujar ambas tarjetas exactamente a la misma altura.
        y_bloques = pdf.get_y()

        # --- TARJETA IZQUIERDA: INFORMACIÓN DEL CLIENTE (127mm) ---
        pdf.set_xy(10, y_bloques)
        pdf.set_fill_color(31, 73, 125)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(127, 7, txt_pdf('  1. INFORMACIÓN DEL CLIENTE (PASAJERO TITULAR)'), 1, 1, 'L', fill=True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_fill_color(248, 250, 252)
        
        # Fila 1 Cliente: Nombre Completo
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Nombre Completo:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', '', 8)
        pdf.cell(89, 7, txt_pdf(cli_nombre, 52, 'CLIENTE EXPRÉS').upper(), 1, 1, 'L')

        # Fila 2 Cliente: Teléfono WhatsApp
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Teléfono / WhatsApp:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', '', 8)
        pdf.cell(89, 7, txt_pdf(cli_tel, 40, 'N/A'), 1, 1, 'L')

        # Fila 3 Cliente: Correo Electrónico
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Correo Electrónico:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', '', 8)
        pdf.cell(89, 7, txt_pdf(cli_correo, 52, 'N/A'), 1, 1, 'L')

        # Fila 4 Cliente: Número de Pasajeros
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Total de Pasajeros:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(89, 7, txt_pdf(f'{num_pax or 1} PAX (PASAJEROS CONFIRMADOS)'), 1, 1, 'L')

        # --- TARJETA DERECHA: INFORMACIÓN DEL CONDUCTOR Y UNIDAD (127mm) ---
        # ¿Por qué y para qué?: Posicionamos en X=143 (10 margen + 127 tarjeta izquierda + 6 separación = 143) y Y=y_bloques.
        pdf.set_xy(143, y_bloques)
        pdf.set_fill_color(31, 73, 125)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(127, 7, txt_pdf('  2. INFORMACIÓN DEL CONDUCTOR Y UNIDAD ASIGNADA'), 1, 1, 'L', fill=True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_fill_color(248, 250, 252)

        # Fila 1 Conductor: Driver Arturo Monroy
        pdf.set_xy(143, y_bloques + 7)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Driver (Conductor):'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(89, 7, txt_pdf('ARTURO MONROY'), 1, 1, 'L')

        # Fila 2 Conductor: Unidad Van Toyota Sienna
        pdf.set_xy(143, y_bloques + 14)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Unidad (Vehículo):'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', '', 8)
        pdf.cell(89, 7, txt_pdf('VAN TOYOTA SIENNA'), 1, 1, 'L')

        # Fila 3 Conductor: Placas 68RD8X
        pdf.set_xy(143, y_bloques + 21)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Placas de Unidad:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(89, 7, txt_pdf('68RD8X'), 1, 1, 'L')

        # Fila 4 Conductor: Operadora
        pdf.set_xy(143, y_bloques + 28)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(38, 7, txt_pdf(' Operador Turístico:'), 1, 0, 'L', fill=True)
        pdf.set_font('Arial', '', 8)
        pdf.cell(89, 7, txt_pdf('ART TOURS TRANSFERS S.A. DE C.V.'), 1, 1, 'L')

        # --------------------------------------------------------
        # SECCIÓN C: TABLA DE ITINERARIO Y RESERVA COMPLETA
        # --------------------------------------------------------
        pdf.set_y(y_bloques + 41)
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(31, 73, 125)
        pdf.cell(0, 5, txt_pdf('SE SOLICITAN LOS SIGUIENTES SERVICIOS A CANCUN TURQUEZA TRANSFERS S.A. DE C.V.:'), 0, 1, 'L')
        pdf.ln(1)

        # ¿Por qué y para qué?: Definimos las 8 columnas de la tabla principal sumando exactamente 260mm de ancho total.
        anchos_tabla1 = [16, 34, 48, 48, 44, 24, 16, 30]
        headers_tabla1 = ['FOLIO', 'FECHA Y HORA', 'PUNTO DE ORIGEN', 'PUNTO DE DESTINO', 'HOTEL / REFERENCIA', 'N° VUELO', 'PAX', 'CUPÓN']

        pdf.set_fill_color(31, 73, 125)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 8)
        for i, cab in enumerate(headers_tabla1):
            pdf.cell(anchos_tabla1[i], 8, txt_pdf(cab), 1, 0, 'C', fill=True)
        pdf.ln()

        # ¿Por qué y para qué?: Formateamos los valores de la fila principal asegurando legibilidad y alineación limpia.
        fecha_servicio_str = str(fecha_hr)[:16] if fecha_hr else 'N/A'
        pdf.set_fill_color(245, 248, 252)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Arial', '', 8)

        pdf.cell(anchos_tabla1[0], 10, txt_pdf(f'#{fol_id}'), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[1], 10, txt_pdf(fecha_servicio_str, 16), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[2], 10, txt_pdf(origen, 28).upper(), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[3], 10, txt_pdf(destino, 28).upper(), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[4], 10, txt_pdf(hotel_ref, 26, 'SIN ESPECIFICAR').upper(), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[5], 10, txt_pdf(num_vuelo, 14, 'S/V').upper(), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[6], 10, txt_pdf(f'{num_pax or 1}'), 1, 0, 'C', fill=True)
        pdf.cell(anchos_tabla1[7], 10, txt_pdf(cupon, 16, 'NINGUNO').upper(), 1, 1, 'C', fill=True)

        pdf.ln(4)

        # --------------------------------------------------------
        # SECCIÓN D: DESGLOSE OPERATIVO, NOTAS Y ESTADO DE PAGO
        # --------------------------------------------------------
        # ¿Por qué y para qué?: Segunda tabla de 260mm para mostrar el tipo de servicio completo, notas operativas, estado de pago e importe.
        anchos_tabla2 = [85, 95, 40, 40]
        headers_tabla2 = ['MODALIDAD / TIPO DE SERVICIO', 'NOTAS E INSTRUCCIONES DEL OPERADOR', 'ESTADO DE PAGO', 'TARIFA REGISTRADA']

        pdf.set_fill_color(45, 95, 145)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 8)
        for i, cab in enumerate(headers_tabla2):
            pdf.cell(anchos_tabla2[i], 7, txt_pdf(cab), 1, 0, 'C', fill=True)
        pdf.ln()

        tipo_servicio_full = f"TRASLADO PRIVADO A {str(destino or '').upper()}"
        est_pago_limpio = str(est_pago or 'Pago_Pendiente').replace('_', ' ').upper()
        precio_num = float(precio) if (precio not in [None, '', 'None']) else 0.0
        precio_formateado = f"${precio_num:,.2f} MXN"

        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Arial', '', 8)
        pdf.cell(anchos_tabla2[0], 9, txt_pdf(tipo_servicio_full, 48), 1, 0, 'C')
        pdf.cell(anchos_tabla2[1], 9, txt_pdf(notas, 55, 'SIN OBSERVACIONES ADICIONALES'), 1, 0, 'C')
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(anchos_tabla2[2], 9, txt_pdf(est_pago_limpio, 22), 1, 0, 'C')
        pdf.cell(anchos_tabla2[3], 9, txt_pdf(precio_formateado), 1, 1, 'C')

        # --------------------------------------------------------
        # SECCIÓN E: BLOQUE DE VALIDACIÓN Y FIRMAS DE CONFORMIDAD
        # --------------------------------------------------------
        pdf.ln(16)
        y_firmas = pdf.get_y()

        # ¿Por qué y para qué?: Trazamos las líneas de firma para el conductor asignado y para el pasajero/caseta de hotel.
        pdf.set_draw_color(100, 100, 100)
        pdf.line(35, y_firmas, 115, y_firmas)
        pdf.line(165, y_firmas, 245, y_firmas)

        pdf.set_y(y_firmas + 2)
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(40, 40, 40)
        pdf.set_x(35)
        pdf.cell(80, 5, txt_pdf('OPERADOR: ARTURO MONROY'), 0, 0, 'C')
        pdf.set_x(165)
        pdf.cell(80, 5, txt_pdf(f'PASAJERO TITULAR: {str(cli_nombre or "CLIENTE").upper()[:28]}'), 0, 1, 'C')

        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(100, 100, 100)
        pdf.set_x(35)
        pdf.cell(80, 4, txt_pdf('Van Toyota Sienna | Placas: 68RD8X'), 0, 0, 'C')
        pdf.set_x(165)
        pdf.cell(80, 4, txt_pdf('Firma de Conformidad / Sello Caseta Hotel'), 0, 1, 'C')

        # ¿Por qué y para qué?: Volcamos el archivo PDF en un buffer en memoria RAM y lo enviamos como descarga directa al navegador.
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        return send_file(
            salida_pdf,
            as_attachment=True,
            download_name=f'Manifiesto_Alianza_Folio_{id_reserva}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        if conn: conn.rollback()
        return f"Error generando manifiesto: {str(e)}", 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ¿Por qué y para qué?: Punto de entrada para ejecución local en entorno de desarrollo.
if __name__ == '__main__':
    app.run(debug=True, port=5000)