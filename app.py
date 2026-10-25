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
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify
from fpdf import FPDF
from db import obtener_conexion_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/reservar', methods=['POST'])
def reservar():
    nombre = request.form.get('nombre')
    telefono = request.form.get('telefono')
    pasajeros = request.form.get('pasajeros')
    origen = request.form.get('origen')
    destino = request.form.get('destino')
    fecha_hora = request.form.get('fecha_hora')
    
    conn = None
    cursor = None
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO clientes (nombre_completo, telefono) 
            VALUES (%s, %s) 
            RETURNING id_cliente
        """, (nombre, telefono))
        id_cliente = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO reservas (id_cliente, origen, destino, fecha_hora_servicio, numero_pasajeros) 
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id_reserva
        """, (id_cliente, origen, destino, fecha_hora, pasajeros))
        id_reserva = cursor.fetchone()[0]
        
        conn.commit()
        
        mensaje = f"Hola, soy {nombre}. Quiero confirmar mi traslado de {origen} a {destino} para {pasajeros} pasajeros el día {fecha_hora}. Folio interno: #{id_reserva}."
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
        # Validamos contra tu archivo .env
        if password_ingresada == os.environ.get("ADMIN_PASSWORD"):
            session['admin_logeado'] = True
            session['id_chofer'] = 1 
            return redirect(url_for('panel_admin'))
        else:
            # En lugar de devolver un string crudo con error 401, enviamos un mensaje a la UI
            flash("Contraseña incorrecta. Intente de nuevo.")
            return render_template('login.html')
            
    return render_template('login.html')

@app.route('/admin')
def panel_admin():
    # Barrera de seguridad: Expulsa a quien no tenga la cookie firmada.
    # ¿Por qué y para qué?: Protege los datos sensibles de tus clientes y las finanzas del negocio.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
        
    conn = None
    cursor = None
    viajes = []
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # Consulta SQL Relacional (JOIN).
        # ¿Por qué y para qué?: Unimos 'reservas' (datos operativos) con 'clientes' (nombre y teléfono) para mostrar una tarjeta (Card) completa al chofer, filtrando solo lo que debe atender hoy.
        cursor.execute("""
            SELECT r.id_reserva, c.nombre_completo, c.telefono, 
                   r.origen, r.destino, r.fecha_hora_servicio, 
                   r.numero_pasajeros, r.estado_reserva
            FROM reservas r
            JOIN clientes c ON r.id_cliente = c.id_cliente
            WHERE r.estado_reserva IN ('Pendiente', 'En_Progreso')
            ORDER BY r.fecha_hora_servicio ASC
        """)
        
        # Mapeo dinámico de columnas a diccionario.
        # ¿Por qué y para qué?: Convierte la tupla cruda de PostgreSQL en un diccionario de Python, permitiendo a Jinja2 acceder a los datos usando nombres legibles como viaje['origen'].
        columnas = [desc[0] for desc in cursor.description]
        viajes = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        
    except Exception as e:
        print(f"Error de base de datos en Panel Admin: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        
    # Inyección del arreglo 'viajes' hacia el motor de plantillas.
    # ¿Por qué y para qué?: Entrega los datos procesados al HTML para que Jinja2 construya las tarjetas de forma dinámica mediante un bucle 'for'.
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
            cursor.execute("""
                UPDATE reservas 
                SET estado_reserva = 'En_Progreso', hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun'
                WHERE id_reserva = %s
            """, (id_reserva,))
        elif accion == 'finalizar':
            cursor.execute("""
                UPDATE reservas 
                SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
                WHERE id_reserva = %s
            """, (id_reserva,))
            
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
                    cursor.execute("""
                        UPDATE reservas 
                        SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
                        WHERE id_reserva = %s
                    """, (viaje_activo[0],))
                else:
                    return jsonify({"status": "blocked", "mensaje": "Tienes un viaje activo. Finalízalo."}), 403
                    
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'En_Progreso', hora_inicio_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE id_reserva = %s
        """, (id_reserva,))
        conn.commit()
        return jsonify({"status": "success", "mensaje": "Viaje iniciado correctamente."})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
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
        
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE estado_reserva = 'En_Progreso' AND DATE(fecha_hora_servicio) = CURRENT_DATE
        """)
        
        cursor.execute("""
            SELECT TO_CHAR(fecha_hora_servicio, 'YYYY-MM-DD'), 
                   TO_CHAR(hora_inicio_real, 'HH24:MI'), TO_CHAR(hora_fin_real, 'HH24:MI'), 
                   origen, destino, hotel_referencia, numero_vuelo, precio
            FROM reservas
            WHERE estado_reserva = 'Finalizado' AND DATE(fecha_hora_servicio) = CURRENT_DATE
        """)
        viajes_hoy = cursor.fetchall()
        conn.commit()

        pdf = FPDF('L', 'mm', 'Letter')
        pdf.add_page()
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(250, 10, 'Reporte Operativo Diario - ART-TOURS TRANSFER', 0, 1, 'C')
        pdf.ln(5)
        
        pdf.set_font('Arial', 'B', 9)
        headers = ['Fecha', 'Inicio', 'Fin', 'Origen', 'Destino', 'Hotel', 'Vuelo', 'Precio']
        anchos = [25, 15, 15, 45, 45, 60, 25, 20]
        
        for i, h in enumerate(headers):
            pdf.cell(anchos[i], 10, h, 1, 0, 'C')
        pdf.ln()

        pdf.set_font('Arial', '', 8)
        for fila in viajes_hoy:
            for i, dato in enumerate(fila):
                valor = str(dato) if dato is not None else 'N/A'
                pdf.cell(anchos[i], 10, valor[:25], 1, 0, 'C')
            pdf.ln()
        
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        pdf_b64 = base64.b64encode(salida_pdf.getvalue()).decode('utf-8')
        webhook_url = os.environ.get("N8N_WEBHOOK_URL_CIERRE")
        fecha_actual_cancun = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
        payload_n8n = {
            "fecha_cierre": fecha_actual_cancun,
            "total_viajes": len(viajes_hoy),
            "archivo_pdf_b64": pdf_b64
        }
        
        try:
            if webhook_url:
                datos_json = json.dumps(payload_n8n).encode('utf-8')
                peticion_http = urllib.request.Request(
                    webhook_url, 
                    data=datos_json, 
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(peticion_http, timeout=3)
        except Exception:
            pass
        
        salida_pdf.seek(0)
        return send_file(salida_pdf, as_attachment=True, download_name=f'Reporte_Diario_{fecha_actual_cancun}.pdf', mimetype='application/pdf')
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def requerir_api_key(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if api_key and api_key == os.environ.get('N8N_SECRET_KEY'):
            return f(*args, **kwargs)
        return jsonify({"status": "error", "mensaje": "Acceso denegado. Token inválido."}), 401
    return decorador

@app.route('/api/v1/automatizacion/reporte-semanal', methods=['POST'])
@requerir_api_key
def trigger_reporte_semanal():
    return jsonify({"status": "success", "mensaje": "Endpoint reservado."}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)