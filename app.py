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
        if password_ingresada == os.environ.get("ADMIN_PASSWORD"):
            session['admin_logeado'] = True
            session['id_chofer'] = 1 
            return redirect(url_for('panel_admin'))
        else:
            flash("Contraseña incorrecta. Intente de nuevo.")
            return render_template('login.html')
            
    return render_template('login.html')

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
        
        # ¿Por qué?: Se incluyó r.precio explícitamente en el SELECT.
        # ¿Para qué?: Permite al frontend HTML (Jinja2) pre-llenar el modal si el viaje ya tenía un costo pactado.
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

# ========================================================
# ENDPOINT: Cierre Operativo y Contable (Cobro en MXN)
# ========================================================
@app.route('/admin/viaje/<int:id_reserva>/finalizar_edicion', methods=['POST'])
def finalizar_viaje_con_edicion(id_reserva):
    datos = request.json
    origen_nuevo = datos.get('origen')
    destino_nuevo = datos.get('destino')
    precio_mxn = datos.get('precio')

    conn = None
    cursor = None
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE reservas 
            SET origen = %s, 
                destino = %s, 
                precio = %s,
                estado_reserva = 'Finalizado', 
                hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE id_reserva = %s
        """, (origen_nuevo, destino_nuevo, precio_mxn, id_reserva))
        
        conn.commit()
        return jsonify({"status": "success", "mensaje": "Viaje cobrado y cerrado con éxito."})
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
        
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# ========================================================
# ENDPOINT: Generación de Corte de Caja en PDF (SaaS Avanzado)
# ========================================================
@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # 1. Sello Transaccional por Frontera Horaria
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE estado_reserva = 'En_Progreso' 
              AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE
        """)
        
        # 2. Extracción Financiera y Operativa (Ampliación a 10 Columnas)
        # ¿Por qué?: Se extraen todos los campos visuales de tu plantilla Excel y se calcula el tiempo transcurrido en el motor SQL (EPOCH).
        # ¿Para qué?: Descargar a Python del procesamiento de fechas y centralizar la lógica de negocio en la consulta.
        cursor.execute("""
            SELECT TO_CHAR(hora_inicio_real, 'YYYY-MM-DD') as fecha,
                   TO_CHAR(hora_inicio_real, 'HH24:MI') as hr_inicio, 
                   TO_CHAR(hora_fin_real, 'HH24:MI') as hr_fin, 
                   EXTRACT(EPOCH FROM (hora_fin_real - hora_inicio_real)) as tiempo_segundos,
                   origen, 
                   destino, 
                   hotel_referencia,
                   id_reserva,
                   cupon,
                   precio
            FROM reservas
            WHERE estado_reserva = 'Finalizado' 
              AND hora_inicio_real::DATE = (NOW() AT TIME ZONE 'America/Cancun')::DATE
        """)
        
        viajes_hoy = cursor.fetchall()
        conn.commit()

        # 3. Inicialización del Motor FPDF (Landscape / Horizontal)
        # ¿Por qué y para qué?: 'L' invierte el eje para darnos ~260mm de ancho útil, esencial para desplegar 10 columnas corporativas sin que se rompa la tabla.
        pdf = FPDF('L', 'mm', 'Letter')
        pdf.add_page()
        
        # Inserción de Logotipo
        # ¿Por qué?: Os.path localiza el logo dinámicamente tanto en tu Windows como en el contenedor Linux de Render.
        ruta_logo = os.path.join(app.root_path, 'static', 'images', 'logo-transfers.png')
        if os.path.exists(ruta_logo):
            pdf.image(ruta_logo, x=10, y=8, w=35)
        
        # Título y Subtítulo Central
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 8, 'RELACION DE SERVICIOS DE ART TOURS TRANSFERS S.A. DE C.V', ln=1, align='C')
        
        fecha_actual_cancun = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, f'PERIODO: {fecha_actual_cancun}', ln=1, align='C')
        pdf.ln(8)
        
        # 4. Construcción de Encabezados (Estilo UI Corporativo)
        # ¿Por qué?: Se aplican los códigos RGB de tu plantilla (Fondo azul oscuro, texto blanco).
        pdf.set_fill_color(31, 73, 125) 
        pdf.set_text_color(255, 255, 255) 
        pdf.set_font('Arial', 'B', 8)
        
        headers = ['Fecha', 'Hora Inicio', 'Hora Fin', 'Tiempo Total', 'Lugar Inicio', 'Lugar Destino', 'Hotel', 'Folio', 'Cupón', 'Precio']
        # Ajuste milimétrico de anchos para sumar exactamente 254mm (encaja perfecto con los márgenes de FPDF)
        anchos = [22, 22, 18, 24, 33, 33, 40, 15, 22, 25]
        
        for i, h in enumerate(headers):
            # fill=True activa el renderizado del color de fondo azul
            pdf.cell(anchos[i], 8, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', fill=True)
        pdf.ln()

        # 5. Volcado de Datos y Agregación Matemática
        pdf.set_text_color(0, 0, 0) # Restaurar color de texto a negro para los datos
        pdf.set_font('Arial', '', 8)
        total_ingresos_mxn = 0.0

        for fila in viajes_hoy:
            fecha_str, hr_inicio, hr_fin, tiempo_seg, origen, destino, hotel, folio, cupon, precio = fila
            
            # Formateo de Tiempo Total
            # ¿Por qué?: Se realiza un divmod manual de los segundos extraídos del EPOCH SQL para obtener formato humano.
            if tiempo_seg is not None:
                horas = int(tiempo_seg // 3600)
                minutos = int((tiempo_seg % 3600) // 60)
                tiempo_str = f"{horas:02d}:{minutos:02d} h"
            else:
                tiempo_str = "N/A"

            # Truncado Responsivo (Defensa Unicode)
            # ¿Por qué?: Garantiza que textos como nombres de hoteles gigantescos no desborden su celda, e inmuniza contra emojis.
            def limpiar_celda(texto, max_len):
                if not texto: return 'N/A'
                return str(texto)[:max_len].encode('latin-1', 'replace').decode('latin-1')

            origen_c = limpiar_celda(origen, 20)
            destino_c = limpiar_celda(destino, 20)
            hotel_c = limpiar_celda(hotel, 25)
            cupon_c = limpiar_celda(cupon, 12)
            
            precio_val = float(precio) if precio is not None else 0.0
            total_ingresos_mxn += precio_val
            
            # Impresión de la fila
            pdf.cell(anchos[0], 8, str(fecha_str or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[1], 8, str(hr_inicio or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[2], 8, str(hr_fin or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[3], 8, tiempo_str, 1, 0, 'C')
            pdf.cell(anchos[4], 8, origen_c, 1, 0, 'L')
            pdf.cell(anchos[5], 8, destino_c, 1, 0, 'L')
            pdf.cell(anchos[6], 8, hotel_c, 1, 0, 'L')
            pdf.cell(anchos[7], 8, str(folio), 1, 0, 'C')
            pdf.cell(anchos[8], 8, cupon_c, 1, 0, 'C')
            pdf.cell(anchos[9], 8, f'${precio_val:,.2f}', 1, 0, 'R')
            pdf.ln()

        # 6. Resumen Financiero Ejecutivo
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 11)
        ancho_previo = sum(anchos[:-1])
        pdf.cell(ancho_previo, 10, 'INGRESO TOTAL DEL PERIODO:', 0, 0, 'R')
        pdf.set_text_color(31, 73, 125) # Azul corporativo para la métrica en MXN
        pdf.cell(anchos[-1], 10, f'${total_ingresos_mxn:,.2f} MXN', 0, 1, 'R')
        
        # 7. Serialización Binaria (Blobs en RAM)
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        pdf_b64 = base64.b64encode(salida_pdf.getvalue()).decode('utf-8')
        webhook_url = os.environ.get("N8N_WEBHOOK_URL_CIERRE")
        
        payload_n8n = {
            "fecha_cierre": fecha_actual_cancun,
            "total_viajes": len(viajes_hoy),
            "ingreso_total_mxn": total_ingresos_mxn,
            "archivo_pdf_b64": pdf_b64
        }
        
        try:
            if webhook_url:
                datos_json = json.dumps(payload_n8n).encode('utf-8')
                peticion_http = urllib.request.Request(webhook_url, data=datos_json, headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(peticion_http, timeout=3)
        except Exception:
            pass
        
        salida_pdf.seek(0)
        return send_file(
            salida_pdf, 
            as_attachment=True, 
            download_name=f'Corte_Caja_{fecha_actual_cancun}.pdf', 
            mimetype='application/pdf'
        )
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"ERROR CRÍTICO EN CIERRE DIARIO: {str(e)}")
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