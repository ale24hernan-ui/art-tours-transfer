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

# ========================================================
# MÓDULO ADMINISTRATIVO (SaaS)
# ========================================================
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
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, c.telefono, 
                   r.origen, r.destino, r.fecha_hora_servicio, 
                   r.numero_pasajeros, r.estado_reserva, r.precio
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

@app.route('/admin/viaje/<int:id_reserva>/estado', methods=['POST'])
def actualizar_estado_viaje(id_reserva):
    accion = request.json.get('accion')
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        if accion == 'iniciar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'En_Progreso', hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (id_reserva,))
        elif accion == 'finalizar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (id_reserva,))
            
        conn.commit()
        return jsonify({"status": "success", "mensaje": f"Estado actualizado a {accion}"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/admin/iniciar_viaje/<int:id_reserva>', methods=['POST'])
def iniciar_viaje_seguro(id_reserva):
    id_chofer_actual = session.get('id_chofer')
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id_reserva FROM reservas WHERE id_chofer = %s AND estado_reserva = 'En_Progreso'", (id_chofer_actual,))
        viaje_activo = cursor.fetchone()
        
        if viaje_activo:
            cursor.execute("SELECT fecha_hora_servicio FROM reservas WHERE id_reserva = %s", (id_reserva,))
            proximo_viaje = cursor.fetchone()
            if proximo_viaje:
                hora_proximo_viaje = proximo_viaje[0]
                hora_actual = datetime.now(ZoneInfo('America/Cancun'))
                if hora_proximo_viaje.tzinfo is None:
                    hora_proximo_viaje = hora_proximo_viaje.replace(tzinfo=ZoneInfo('America/Cancun'))
                
                diferencia = hora_proximo_viaje - hora_actual
                if diferencia <= timedelta(minutes=5):
                    cursor.execute("UPDATE reservas SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (viaje_activo[0],))
                else:
                    return jsonify({"status": "blocked", "mensaje": "Tienes un viaje activo. Finalízalo."}), 403
                    
        cursor.execute("UPDATE reservas SET estado_reserva = 'En_Progreso', hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (id_reserva,))
        conn.commit()
        return jsonify({"status": "success", "mensaje": "Viaje iniciado."})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/admin/viaje/<int:id_reserva>/finalizar_edicion', methods=['POST'])
def finalizar_viaje_con_edicion(id_reserva):
    datos = request.json
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE reservas SET origen = %s, destino = %s, precio = %s, estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE id_reserva = %s
        """, (datos.get('origen'), datos.get('destino'), datos.get('precio'), id_reserva))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE reservas SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun' WHERE estado_reserva = 'En_Progreso' AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE")
        cursor.execute("SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD'), TO_CHAR(hora_inicio_real, 'HH24:MI'), TO_CHAR(hora_fin_real, 'HH24:MI'), EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)), origen, destino, hotel_referencia, id_reserva, cupon, precio FROM reservas WHERE estado_reserva = 'Finalizado' AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE")
        viajes_hoy = cursor.fetchall()
        conn.commit()

        pdf = FPDF('L', 'mm', 'Letter')
        pdf.add_page()
        ruta_logo = os.path.join(app.root_path, 'static', 'images', 'logo-transfers.png')
        if os.path.exists(ruta_logo): pdf.image(ruta_logo, x=10, y=8, w=35)
        pdf.ln(15) 
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 8, 'RELACION DE SERVICIOS DE ART TOURS TRANSFERS S.A. DE C.V', ln=1, align='C')
        fecha_actual = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, f'PERIODO: {fecha_actual}', ln=1, align='C')
        pdf.ln(8)
        
        pdf.set_fill_color(31, 73, 125); pdf.set_text_color(255, 255, 255); pdf.set_font('Arial', 'B', 8)
        headers = ['Fecha', 'Hora Inicio', 'Hora Fin', 'Tiempo Total', 'Lugar Inicio', 'Lugar Destino', 'Hotel', 'Folio', 'Cupón', 'Precio']
        anchos = [22, 22, 18, 24, 33, 33, 40, 15, 22, 25]
        for i, h in enumerate(headers): pdf.cell(anchos[i], 8, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', fill=True)
        pdf.ln()

        pdf.set_text_color(0, 0, 0); pdf.set_font('Arial', '', 8)
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

        pdf.ln(10); pdf.set_font('Arial', 'B', 11)
        pdf.cell(sum(anchos[:-1]) - 5, 10, 'INGRESO TOTAL DEL PERIODO:', 0, 0, 'R')
        pdf.set_text_color(31, 73, 125) 
        pdf.cell(anchos[-1] + 5, 10, f'${total_ingresos_mxn:,.2f} MXN', 0, 1, 'R')
        
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        return send_file(salida_pdf, as_attachment=True, download_name=f'Corte_Caja_{fecha_actual}.pdf', mimetype='application/pdf')
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
# ========================================================
# CRUD MAESTRO Y REGISTRO MANUAL (Bypass Operativo)
# ========================================================

@app.route('/admin/viaje/<int:id_reserva>/master_edit', methods=['POST'])
def master_edit_viaje(id_reserva):
    # ¿Por qué y para qué?: Obtenemos el payload JSON enviado por JS (Fetch API) con los datos del modal.
    datos = request.json
    accion = datos.get('accion')
    
    conn = None
    cursor = None
    try:
        # ¿Por qué y para qué?: Abrimos conexión a PostgreSQL para ejecutar sentencias de modificación.
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        if accion == 'editar':
            # ¿Por qué y para qué?: Actualizamos los datos básicos en vivo para corregir errores de captura.
            cursor.execute("""
                UPDATE reservas SET origen = %s, destino = %s, precio = %s
                WHERE id_reserva = %s
            """, (datos.get('origen'), datos.get('destino'), datos.get('precio'), id_reserva))
            
        elif accion == 'cancelar':
            # ¿Por qué y para qué?: Realizamos una eliminación lógica (Soft-Delete) cambiando el estado.
            # Así ocultamos el viaje de la vista principal sin destruir la trazabilidad en la base de datos.
            cursor.execute("""
                UPDATE reservas SET estado_reserva = 'Cancelado'
                WHERE id_reserva = %s
            """, (id_reserva,))
            
        elif accion == 'reactivar':
            # ¿Por qué y para qué?: Permitimos al administrador recuperar un folio cerrado o cancelado por error.
            cursor.execute("""
                UPDATE reservas SET estado_reserva = 'Pendiente'
                WHERE id_reserva = %s
            """, (id_reserva,))
            
        # ¿Por qué y para qué?: Confirmamos y blindamos la transacción (Atomicidad).
        conn.commit()
        return jsonify({"status": "success"})
        
    except Exception as e:
        # ¿Por qué y para qué?: Si PostgreSQL arroja un error, revertimos la transacción para evitar datos corruptos.
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        # ¿Por qué y para qué?: Liberamos el pool de conexiones en el servidor Render.
        if cursor: cursor.close()
        if conn: conn.close()


@app.route('/admin/viaje/manual', methods=['POST'])
def registrar_viaje_manual():
    # ¿Por qué y para qué?: Desempaquetamos el objeto JSON que envía el modal "Registro Manual".
    datos = request.json
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Primero creamos un perfil temporal en la tabla 'clientes' para 
        # mantener la integridad referencial obligatoria de tu arquitectura SQL.
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono)
            VALUES (%s, %s) RETURNING id_cliente
        """, ('Registro Manual (Bypass)', 'N/A'))
        id_cliente = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Insertamos la reserva enlazada al ID de cliente generado en el paso anterior.
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, numero_pasajeros, fecha_hora_servicio, precio, estado_reserva)
            VALUES (%s, %s, %s, %s, %s, %s, 'Pendiente')
        """, (id_cliente, datos.get('origen'), datos.get('destino'), datos.get('pasajeros'), datos.get('fecha_hora'), datos.get('precio')))
        
        conn.commit()
        return jsonify({"status": "success"})
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# ========================================================
# RUTA DE HISTORIAL OPERATIVO
# ========================================================

@app.route('/admin/historial', methods=['GET'])
def historial_operativo():
    # ¿Por qué y para qué?: Protegemos la ruta validando la variable global de sesión de Flask.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    # ¿Por qué y para qué?: Leemos el parámetro GET ?fecha=. Si está vacío, inyectamos la fecha actual en Cancún.
    fecha_solicitada = request.args.get('fecha')
    if not fecha_solicitada:
        fecha_solicitada = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
    conn = None
    cursor = None
    viajes = []
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: Realizamos un LEFT JOIN buscando exclusivamente los registros 
        # que coincidan textualmente con la fecha filtrada (LIKE) para alimentar el histórico.
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, r.origen, r.destino, r.precio, r.estado_reserva
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.fecha_hora_servicio::text LIKE %s
            ORDER BY r.id_reserva DESC
        """, (f"{fecha_solicitada}%",))
        
        # ¿Por qué y para qué?: Convertimos la tupla cruda a un diccionario para que Jinja2 pueda iterar con llaves en historial.html.
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error cargando el historial: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    # ¿Por qué y para qué?: Servimos el frontend enlazado a los datos procesados.
    return render_template('historial.html', viajes=viajes, fecha_actual=fecha_solicitada)
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
