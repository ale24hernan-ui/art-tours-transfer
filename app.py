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