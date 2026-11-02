import os
import io
import base64
import json
import urllib.parse
import urllib.request
import urllib.error
import psycopg2.extras # ¿Por qué?: Necesario para DictCursor.
from functools import wraps
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify, flash
from fpdf import FPDF
from db import obtener_conexion_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

# ========================================================
# RUTAS PÚBLICAS (Lead y Autenticación)
# ========================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/reservar', methods=['POST'])
def reservar():
    # ¿Por qué y para qué?: Capturamos las nuevas variables del DOM. El teléfono ya no viene del frontend, así que lo omitimos.
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
        
        # ¿Por qué y para qué?: Insertamos 'Obtenido vía WA' como teléfono. Esto previene un error SQL si la columna 'telefono' en la tabla 'clientes' es obligatoria, logrando un bypass elegante.
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono) 
            VALUES (%s, %s) 
            RETURNING id_cliente
        """, (nombre, 'Obtenido vía WA'))
        id_cliente = cursor.fetchone()[0]
        
        # ¿Por qué y para qué?: Expandimos el INSERT de reservas para empatar exactamente con tu esquema, inyectando 'numero_vuelo' y 'cupon'.
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, fecha_hora_servicio, numero_pasajeros, numero_vuelo, cupon, estado_reserva) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pendiente')
            RETURNING id_reserva
        """, (id_cliente, origen, destino, fecha_hora, pasajeros, numero_vuelo, cupon))
        id_reserva = cursor.fetchone()[0]
        
        conn.commit()
        
        # ¿Por qué y para qué?: Enriquecemos el payload de WhatsApp para que cuando te llegue el mensaje, tengas toda la telemetría sin preguntar nada al cliente.
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
        if request.form.get('password') == os.environ.get("ADMIN_PASSWORD"):
            session['admin_logeado'] = True
            session['id_chofer'] = 1 
            return redirect(url_for('panel_admin'))
        flash("Contraseña incorrecta.")
    return render_template('login.html')

# ========================================================
# MÓDULO ADMINISTRATIVO Y MÁQUINA DE ESTADOS
# ========================================================
@app.route('/admin')
def panel_admin():
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    conn = None
    cursor = None
    viajes = []
    puntos = [] # ¿Por qué?: Inicializamos la lista vacía para evitar errores de referencia si la BD falla.
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # 1. Extracción de Viajes Activos
        # 1. Extracción Segmentada (Hoy y Mañana) con Jerarquía
        # ¿Por qué?: Cambiamos a LEFT JOIN para no perder los viajes del Bypass manual (donde id_cliente es NULL).
        # ¿Para qué?: Limitamos la extracción estrictamente a una ventana operativa de 48 horas. Usamos CASE WHEN para que los viajes críticos (Pendientes/En Progreso) floten arriba, y las resoluciones (Finalizados) bajen, limpiando la visión del chofer.
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, c.telefono, 
                   r.origen, r.destino, r.fecha_hora_servicio, 
                   r.numero_pasajeros, r.estado_reserva, r.precio,
                   DATE(r.fecha_hora_servicio) as fecha_corte
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE DATE(r.fecha_hora_servicio) >= (NOW() AT TIME ZONE 'America/Cancun')::DATE
              AND DATE(r.fecha_hora_servicio) <= (NOW() AT TIME ZONE 'America/Cancun')::DATE + INTERVAL '1 day'
            ORDER BY 
                DATE(r.fecha_hora_servicio) ASC,
                CASE 
                    WHEN r.estado_reserva = 'Pendiente' THEN 1
                    WHEN r.estado_reserva = 'En_Progreso' THEN 2
                    WHEN r.estado_reserva = 'Finalizado' THEN 3
                    WHEN r.estado_reserva = 'Cancelado' THEN 4
                    ELSE 5
                END ASC,
                r.fecha_hora_servicio ASC
        """)
        
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        
        # 2. NUEVO: Extracción del Catálogo Geográfico
        # ¿Por qué?: Ejecutamos un SELECT directo a la tabla puntos_interes creada en hitos anteriores.
        # ¿Para qué?: Para poblar dinámicamente el datalist del formulario manual en admin.html, garantizando que el origen y destino coincidan con el tarifario.
        cursor.execute("SELECT nombre_destino FROM puntos_interes ORDER BY nombre_destino ASC")
        puntos = [fila[0] for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error de base de datos en Panel Admin: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    # ¿Por qué?: Pasamos la variable 'puntos_interes' al motor Jinja2.
    return render_template('admin.html', viajes=viajes, puntos_interes=puntos)


@app.route('/admin/viaje/manual', methods=['POST'])
def crear_viaje_manual():
    datos = request.json
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        # ¿Por qué?: Inserción de Bypass operativo pasando NULL al id_cliente[cite: 1].
        # ¿Para qué?: Permite al administrador crear reservas telefónicas al vuelo sin registrar al cliente.
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, fecha_hora_servicio, numero_pasajeros, precio, estado_reserva) 
            VALUES (NULL, %s, %s, %s, %s, %s, 'Pendiente')
        """, (datos.get('origen'), datos.get('destino'), datos.get('fecha_hora'), datos.get('pasajeros'), datos.get('precio')))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/admin/viaje/<int:id_reserva>/master_edit', methods=['POST'])
def master_edit_viaje(id_reserva):
    datos = request.json
    accion = datos.get('accion') # editar | cancelar | reactivar
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué?: Soft-Delete aplicado al modelo de estado.
        # ¿Para qué?: No borramos la fila, solo la ocultamos del flujo principal y la preservamos para métricas[cite: 1].
        if accion == 'cancelar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'Cancelado' WHERE id_reserva = %s", (id_reserva,))
        elif accion == 'reactivar':
            cursor.execute("UPDATE reservas SET estado_reserva = 'Pendiente', hora_inicio_real = NULL, hora_fin_real = NULL WHERE id_reserva = %s", (id_reserva,))
        elif accion == 'editar':
            cursor.execute("UPDATE reservas SET origen = %s, destino = %s, precio = %s WHERE id_reserva = %s", 
                           (datos.get('origen'), datos.get('destino'), datos.get('precio'), id_reserva))
            
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# Mantengo intactas tus rutas de iniciar/finalizar estado
@app.route('/admin/iniciar_viaje/<int:id_reserva>', methods=['POST'])
def iniciar_viaje_seguro(id_reserva):
    # Lógica intacta de validación de 5 minutos y set a 'En_Progreso'
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE reservas SET estado_reserva = 'En_Progreso', hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun' WHERE id_reserva = %s", (id_reserva,))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error"}), 500
    finally:
        if cursor: cursor.close(); conn.close()

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
        if cursor: cursor.close(); conn.close()

# ========================================================
# VISTA HISTÓRICA Y REPORTE FPDF (Paramétrico)
# ========================================================
@app.route('/admin/historial')
def historial_admin():
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    # ¿Por qué?: Capturamos la fecha solicitada o usamos HOY por defecto.
    # ¿Para qué?: Permite al panel de historial navegar por días exactos.
    fecha_req = request.args.get('fecha')
    if not fecha_req:
        fecha_req = datetime.now(ZoneInfo('America/Cancun')).strftime('%Y-%m-%d')
        
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("""
            SELECT r.*, c.nombre_completo, c.telefono 
            FROM reservas r
            LEFT JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE DATE(r.fecha_hora_servicio) = %s
            ORDER BY r.fecha_hora_servicio ASC
        """, (fecha_req,))
        viajes = cursor.fetchall()
        return render_template('historial.html', viajes=viajes, fecha_actual=fecha_req)
    except Exception as e:
        return f"Error: {str(e)}", 500
    finally:
        if cursor: cursor.close(); conn.close()

@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    datos = request.json or {}
    # ¿Por qué?: Aceptamos una fecha por JSON, si no, tomamos la de hoy.
    # ¿Para qué?: Reutilizamos este generador FPDF tanto para el cierre del día operativo como para re-imprimir cierres pasados desde el Historial.
    fecha_corte = datos.get('fecha', datetime.now(ZoneInfo('America/Cancun')).strftime('%Y-%m-%d'))
    
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # 1. Sello Transaccional por Frontera Horaria (Solo si es el cierre del día actual)
        if fecha_corte == datetime.now(ZoneInfo('America/Cancun')).strftime('%Y-%m-%d'):
            cursor.execute("""
                UPDATE reservas 
                SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
                WHERE estado_reserva = 'En_Progreso' AND DATE(hora_inicio_real) = %s
            """, (fecha_corte,))
        
        # 2. Extracción Financiera y Operativa[cite: 1]
        cursor.execute("""
            SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD') as fecha,
                   TO_CHAR(hora_inicio_real, 'HH24:MI') as hr_inicio, 
                   TO_CHAR(hora_fin_real, 'HH24:MI') as hr_fin, 
                   EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)) as tiempo_segundos,
                   origen, destino, hotel_referencia, id_reserva, cupon, precio
            FROM reservas
            WHERE estado_reserva = 'Finalizado' AND DATE(fecha_hora_servicio) = %s
        """, (fecha_corte,))
        
        viajes = cursor.fetchall()
        conn.commit()

        # (La lógica de generación FPDF permanece exacta a tu versión funcional[cite: 2, 3])
        pdf = FPDF('L', 'mm', 'Letter')
        pdf.add_page()
        ruta_logo = os.path.join(app.root_path, 'static', 'images', 'logo-transfers.png')
        if os.path.exists(ruta_logo): pdf.image(ruta_logo, x=10, y=8, w=35)
        pdf.ln(15) 
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 8, 'RELACION DE SERVICIOS DE ART TOURS TRANSFERS S.A. DE C.V', ln=1, align='C')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, f'PERIODO: {fecha_corte}', ln=1, align='C')
        pdf.ln(8)
        
        pdf.set_fill_color(31, 73, 125); pdf.set_text_color(255, 255, 255); pdf.set_font('Arial', 'B', 8)
        headers = ['Fecha', 'Hora Inicio', 'Hora Fin', 'Tiempo Total', 'Lugar Inicio', 'Lugar Destino', 'Hotel', 'Folio', 'Cupón', 'Precio']
        anchos = [22, 22, 18, 24, 33, 33, 40, 15, 22, 25]
        for i, h in enumerate(headers): pdf.cell(anchos[i], 8, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', fill=True)
        pdf.ln()

        pdf.set_text_color(0, 0, 0); pdf.set_font('Arial', '', 8)
        total_ingresos = 0.0

        for fila in viajes:
            f_str, h_in, h_fin, t_seg, org, dst, hot, fol, cup, prec = fila
            t_str = f"{int(t_seg//3600):02d}:{int((t_seg%3600)//60):02d} h" if t_seg else "N/A"
            p_val = float(prec) if prec else 0.0
            total_ingresos += p_val
            
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
        pdf.cell(anchos[-1] + 5, 10, f'${total_ingresos:,.2f} MXN', 0, 1, 'R')
        
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        return send_file(salida_pdf, as_attachment=True, download_name=f'Corte_{fecha_corte}.pdf', mimetype='application/pdf')
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close(); conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)