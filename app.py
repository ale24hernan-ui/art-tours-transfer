import os
import io
import base64
import json
import urllib.parse
import urllib.request
import urllib.error
from functools import wraps
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify, flash
from fpdf import FPDF
from db import obtener_conexion_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

# ========================================================
# RUTA PÚBLICA (ESCAPARATE B2C)
# ========================================================
@app.route('/')
def index():
    conn = None
    cursor = None
    puntos = []
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Ejecutamos un SELECT a la tabla de localizaciones.
        # Ordenamos ASC para que el cliente tenga una lista alfabética fácil de leer.
        cursor.execute("SELECT nombre_destino FROM puntos_interes ORDER BY nombre_destino ASC")
        puntos = [fila[0] for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error cargando puntos de interés en el Home: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    # ¿Por qué y para qué?: Inyectamos la variable 'puntos' hacia el motor Jinja2 bajo el nombre 'puntos_interes'.
    return render_template('index.html', puntos_interes=puntos)

# ========================================================
# RUTAS DE RESERVA Y AUTENTICACIÓN
# ========================================================
@app.route('/reservar', methods=['POST'])
def reservar():
    nombre = request.form.get('nombre')
    pasajeros = request.form.get('pasajeros')
    origen = request.form.get('origen')
    destino = request.form.get('destino')
    fecha_hora = request.form.get('fecha_hora')
    numero_vuelo = request.form.get('numero_vuelo', 'N/A')
    cupon = request.form.get('cupon', 'Ninguno')
    vehiculo_asignado = request.form.get('vehiculo_asignado')
    
    conn = None
    cursor = None
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono) 
            VALUES (%s, %s) 
            RETURNING id_cliente
        """, (nombre, 'Obtenido vía WA'))
        id_cliente = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, fecha_hora_servicio, numero_pasajeros, numero_vuelo, cupon, estado_reserva) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pendiente')
            RETURNING id_reserva
        """, (id_cliente, origen, destino, fecha_hora, pasajeros, numero_vuelo, cupon))
        id_reserva = cursor.fetchone()[0]
        
        conn.commit()
        
        mensaje = f"Hola, soy {nombre}. Solicito un traslado de {origen} a {destino} para {pasajeros} pasajeros (Unidad: {vehiculo_asignado}) el día {fecha_hora}. Vuelo: {numero_vuelo}. Cupón: {cupon}. Folio interno: #{id_reserva}."
        mensaje_codificado = urllib.parse.quote(mensaje)
        numero_empresa = "5219982156446"
        url_whatsapp = f"https://wa.me/{numero_empresa}?text={mensaje_codificado}"
        
        return redirect(url_whatsapp)
        
    except Exception as e:
        if conn: conn.rollback()
        return f"Error interno al procesar la reserva: {str(e)}", 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password_ingresada = request.form.get('password')
        if password_ingresada == os.environ.get("ADMIN_PASSWORD"):
            session['admin_logeado'] = True
            session['id_chofer'] = 1 
            return redirect(url_for('panel_admin'))
        else:
            flash("Contraseña incorrecta. Intente de nuevo.")
            return render_template('login.html')
            
    return render_template('login.html')

# --------------------------------------------------------
# 1. ACTUALIZA EL SELECT EN LA RUTA PRINCIPAL
# --------------------------------------------------------
@app.route('/admin')
def panel_admin():
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    conn = None
    cursor = None
    viajes = []
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        # ¿Por qué y para qué?: Expandimos el SELECT para traer TODAS las columnas 
        # necesarias y poblar el modal de edición maestro en el Frontend.
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, c.telefono, 
                   r.origen, r.destino, r.fecha_hora_servicio, 
                   r.numero_pasajeros, r.estado_reserva, r.precio,
                   r.hotel_referencia, r.numero_vuelo, r.estado_pago,
                   r.cupon, r.notas
            FROM reservas r
            JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.estado_reserva IN ('Pendiente', 'En_Progreso')
            ORDER BY r.fecha_hora_servicio ASC
        """)
        
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error de base de datos en Panel Admin: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    return render_template('admin.html', viajes=viajes)

# --------------------------------------------------------
# 2. ACTUALIZA EL CRUD MAESTRO
# --------------------------------------------------------
@app.route('/admin/viaje/<int:id_reserva>/master_edit', methods=['POST'])
def master_edit_viaje(id_reserva):
    datos = request.json
    accion = datos.get('accion')
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        if accion == 'editar':
            # ¿Por qué y para qué?: Ejecutamos un UPDATE masivo mapeando los 10 inputs del Frontend.
            cursor.execute("""
                UPDATE reservas 
                SET origen = %s, destino = %s, precio = %s, 
                    hotel_referencia = %s, numero_vuelo = %s, 
                    fecha_hora_servicio = %s, numero_pasajeros = %s, 
                    estado_pago = %s, cupon = %s, notas = %s
                WHERE id_reserva = %s
            """, (
                datos.get('origen'), datos.get('destino'), datos.get('precio'),
                datos.get('hotel_referencia'), datos.get('numero_vuelo'),
                datos.get('fecha_hora_servicio'), datos.get('numero_pasajeros'),
                datos.get('estado_pago'), datos.get('cupon'), datos.get('notas'),
                id_reserva
            ))
        elif accion == 'cancelar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'Cancelado' WHERE id_reserva = %s", (id_reserva,))
        elif accion == 'reactivar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'Pendiente' WHERE id_reserva = %s", (id_reserva,))
            
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# --------------------------------------------------------
# 3. ACTUALIZA EL REGISTRO MANUAL
# --------------------------------------------------------
@app.route('/admin/viaje/manual', methods=['POST'])
def registrar_viaje_manual():
    datos = request.json
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono)
            VALUES (%s, %s) RETURNING id_cliente
        """, ('Registro Manual (Bypass)', 'N/A'))
        id_cliente = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Insertamos la reserva con la tabla expandida.
        cursor.execute("""
            INSERT INTO reservas (
                id_cliente, origen, destino, numero_pasajeros, fecha_hora_servicio, 
                precio, hotel_referencia, numero_vuelo, estado_pago, cupon, notas, estado_reserva
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pendiente')
        """, (
            id_cliente, datos.get('origen'), datos.get('destino'), datos.get('pasajeros'), 
            datos.get('fecha_hora'), datos.get('precio'), datos.get('hotel_referencia'), 
            datos.get('numero_vuelo'), datos.get('estado_pago', 'Pago_Pendiente'), 
            datos.get('cupon'), datos.get('notas')
        ))
        
        conn.commit()
        return jsonify({"status": "success"})
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# --------------------------------------------------------
# 4. FIX DEL BUG: CIERRE DIARIO E HISTORIAL
# --------------------------------------------------------
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
            # ¿Por qué y para qué?: Si el Frontend envía una fecha, estamos en el HISTORIAL.
            # Omitimos el UPDATE de cierre y consultamos exclusivamente el día solicitado.
            cursor.execute("""
                SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD'), TO_CHAR(hora_inicio_real, 'HH24:MI'), 
                       TO_CHAR(hora_fin_real, 'HH24:MI'), EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)), 
                       origen, destino, hotel_referencia, id_reserva, cupon, precio 
                FROM reservas 
                WHERE estado_reserva = 'Finalizado' AND hora_inicio_real::DATE = %s::DATE
            """, (fecha_solicitada,))
            fecha_reporte = fecha_solicitada
        else:
            # ¿Por qué y para qué?: Si no hay fecha, es el CIERRE DIARIO DE HOY. Cerramos los viajes en progreso.
            cursor.execute("UPDATE reservas SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' WHERE estado_reserva = 'En_Progreso' AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE")
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

        # AQUÍ CONTINÚA TU CÓDIGO ORIGINAL DE FPDF (pdf = FPDF('L', 'mm', 'Letter')...) 
        # Asegúrate de cambiar la variable final de descarga a `fecha_reporte` en tu send_file:
        # return send_file(salida_pdf, as_attachment=True, download_name=f'Corte_{fecha_reporte}.pdf', mimetype='application/pdf')
# ========================================================
# GENERADOR DE MANIFIESTO (ALIANZA TURQUEZA) FPDF
# ========================================================

@app.route('/admin/viaje/<int:id_reserva>/manifiesto_pdf', methods=['GET'])
def generar_manifiesto_individual(id_reserva):
    # ¿Por qué y para qué?: Protegemos la ruta para que solo el admin/chofer logeado pueda descargar comprobantes.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))

    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Hacemos un JOIN para extraer la información logística (origen/destino) y del cliente (nombre).
        cursor.execute("""
            SELECT r.id_reserva, r.origen, r.destino, r.fecha_hora_servicio, r.numero_pasajeros, r.numero_vuelo, r.estado_reserva, c.nombre_completo
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.id_reserva = %s
        """, (id_reserva,))
        viaje = cursor.fetchone()
        
        if not viaje:
            return "Viaje no encontrado", 404
            
        # ¿Por qué y para qué?: Inicializamos FPDF en orientación 'L' (Landscape/Apaisado), milímetros, tamaño 'Letter' (Hoja Carta).
        pdf = FPDF('L', 'mm', 'Letter') 
        pdf.add_page()
        
        # ¿Por qué y para qué?: Manejo de Logos. Busca imágenes en /static/images. Si no existen, FPDF simplemente ignora el bloque sin tirar error 500.
        # TIP: Sube los logos de Turqueza y Safe Travels a tu carpeta static/images/ para que se inyecten aquí.
        ruta_logo_turq = os.path.join(app.root_path, 'static', 'images', 'turqueza.png')
        ruta_logo_safe = os.path.join(app.root_path, 'static', 'images', 'safe-travels.png')
        if os.path.exists(ruta_logo_turq): pdf.image(ruta_logo_turq, x=60, y=10, w=60)
        if os.path.exists(ruta_logo_safe): pdf.image(ruta_logo_safe, x=130, y=10, w=40)
        
        pdf.ln(35) # Salto de línea para despejar la zona de los logotipos.
        
        # ¿Por qué y para qué?: Datos fiscales y cabecera izquierda en fuente negrita cursiva (BI).
        pdf.set_font('Arial', 'BI', 10)
        pdf.cell(150, 5, 'CANCUNTURQUEZATRANSFERSS.A DE C.V SM76M23L12CALLE62C.P.77527', 0, 0, 'L')
        # ¿Por qué y para qué?: Alineación a la derecha (R) para la ubicación.
        pdf.cell(0, 5, 'CANCUN QUINTANAROO.', 0, 1, 'R') 
        pdf.ln(4)
        
        pdf.cell(150, 5, 'RFC:CTT171213QS1', 0, 0, 'L')
        
        # ¿Por qué y para qué?: Generamos la marca de tiempo dinámica del momento de la descarga.
        fecha_str = datetime.now(ZoneInfo('America/Cancun')).strftime("%d %B %Y")
        pdf.cell(0, 5, f'MANIFIESTO DEL [ {fecha_str} ]', 0, 1, 'R')
        pdf.ln(4)
        
        pdf.cell(0, 5, 'SE SOLICITA LOS SIGUIENTES SERVICIOS A CANCUN TURQUEZA TRANSFERS SA DE CV', 0, 1, 'L')
        pdf.ln(8)
        
        # ¿Por qué y para qué?: Estructuración de la Tabla de Manifiesto.
        # Repartimos los 260mm útiles de la hoja Carta apaisada entre 8 columnas.
        pdf.set_font('Arial', 'B', 8)
        anchos = [8, 22, 15, 20, 60, 55, 30, 45]
        cabeceras = ['', 'HORA', 'PAX', 'VUELO', 'NOMBRE', 'HOTEL', 'OPERADOR', 'TIPO DE SERVICIO']
        
        for i, cab in enumerate(cabeceras):
            pdf.cell(anchos[i], 8, cab, border=1, align='C')
        pdf.ln()
        
        # ¿Por qué y para qué?: Preparación de variables con mapeo lógico y limpieza (truncate) para evitar que rompan las celdas.
        # viaje[3] es la fecha, extraemos solo un fragmento o lo dejamos como string.
        hora_str = str(viaje[3])[:16] 
        pax = f"{viaje[4]} PAX"
        vuelo = str(viaje[5] or '')
        nombre = str(viaje[7] or 'N/A').upper()
        hotel = str(viaje[1]).upper() 
        operador = "ART TOURS" 
        tipo_servicio = f"TRASLADO A {str(viaje[2]).upper()}"
        
        # Función auxiliar para truncar textos largos y recodificar a latin-1 (para acentos ñ, á, é).
        def lmp(t, m): return str(t)[:m].encode('latin-1', 'replace').decode('latin-1')
        
        # ¿Por qué y para qué?: Inserción de la fila con los datos reales de la reserva.
        pdf.set_font('Arial', '', 8)
        pdf.cell(anchos[0], 10, "1", border=1, align='C')
        pdf.cell(anchos[1], 10, lmp(hora_str, 15), border=1, align='C')
        pdf.cell(anchos[2], 10, lmp(pax, 10), border=1, align='C')
        pdf.cell(anchos[3], 10, lmp(vuelo, 10), border=1, align='C')
        pdf.cell(anchos[4], 10, lmp(nombre, 35), border=1, align='C')
        pdf.cell(anchos[5], 10, lmp(hotel, 30), border=1, align='C')
        pdf.cell(anchos[6], 10, lmp(operador, 15), border=1, align='C')
        pdf.cell(anchos[7], 10, lmp(tipo_servicio, 28), border=1, align='C')
        
        # ¿Por qué y para qué?: Volcamos el PDF en memoria RAM (sin tocar disco duro) y forzamos descarga HTTP.
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        return send_file(salida_pdf, as_attachment=True, download_name=f'Manifiesto_Alianza_Folio_{id_reserva}.pdf', mimetype='application/pdf')
        
    except Exception as e:
        if conn: conn.rollback()
        return f"Error generando manifiesto: {str(e)}", 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
