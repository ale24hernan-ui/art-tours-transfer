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
# ENDPOINT: Generación de Corte de Caja en PDF (Frontera Horaria)
# ========================================================
@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    # Inicializamos variables de conexión en nulo.
    # ¿Por qué y para qué?: Previene fugas de memoria y errores de referencia si el clúster de Render rechaza la conexión inicial.
    conn = None
    cursor = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # 1. Sello Transaccional por Frontera Horaria (UPDATE)
        # ¿Por qué?: Cambiamos el filtro 'DATE(fecha_hora_servicio)' por 'DATE(hora_inicio_real AT TIME ZONE 'America/Cancun')'.
        # ¿Para qué?: Garantiza que si el operador olvidó cerrar un viaje en la app, el sistema forzará su cierre adjudicando el dinero al día exacto en que físicamente arrancó la Van.
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE estado_reserva = 'En_Progreso' 
              AND DATE(hora_inicio_real AT TIME ZONE 'America/Cancun') = CURRENT_DATE
        """)
        
        # 2. Extracción Financiera (SELECT)
        # ¿Por qué?: Mantenemos la lógica de 'hora_inicio_real' y extraemos 'precio'.
        # ¿Para qué?: Traemos a la RAM de Python únicamente los viajes rentabilizados hoy, aislando el capital de la medianoche.
        cursor.execute("""
            SELECT id_reserva, 
                   TO_CHAR(hora_inicio_real, 'HH24:MI'), 
                   TO_CHAR(hora_fin_real, 'HH24:MI'), 
                   origen, destino, precio
            FROM reservas
            WHERE estado_reserva = 'Finalizado' 
              AND DATE(hora_inicio_real AT TIME ZONE 'America/Cancun') = CURRENT_DATE
        """)
        
        # Volcado de datos a la memoria de Flask.
        viajes_hoy = cursor.fetchall()
        conn.commit()

        # 3. Inicialización del Motor FPDF
        # ¿Por qué?: Orientación 'P' (Portrait) en tamaño Carta (Letter).
        # ¿Para qué?: Optimizar la lectura del PDF en pantallas verticales de smartphones, evitando que el dueño deba hacer zoom lateral.
        pdf = FPDF('P', 'mm', 'Letter')
        pdf.add_page()
        
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(190, 10, 'CORTE DE CAJA DIARIO - ART-TOURS', ln=1, align='C')
        
        # Sincronización estricta del reloj local.
        # ¿Por qué?: ZoneInfo fuerza a Python a ignorar el reloj UTC del servidor en la nube.
        # ¿Para qué?: El PDF se titulará siempre con la fecha real de Quintana Roo.
        fecha_actual_cancun = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
        pdf.set_font('Arial', 'I', 10)
        pdf.cell(190, 10, f'Fecha de Operacion: {fecha_actual_cancun}', ln=1, align='C')
        pdf.ln(5)
        
        # 4. Renderizado Estructural de la Tabla
        # ¿Por qué?: Arreglos de strings y enteros para columnas.
        # ¿Para qué?: Controlar matemáticamente los 190mm de ancho disponible en la hoja Carta.
        pdf.set_font('Arial', 'B', 9)
        headers = ['Folio', 'Inicio', 'Fin', 'Ruta (Origen - Destino)', 'Ingreso']
        anchos = [15, 15, 15, 115, 30]
        
        for i, h in enumerate(headers):
            pdf.cell(anchos[i], 8, h, 1, 0, 'C')
        pdf.ln()

        # 5. Agregación Matemática y Volcado de Filas
        pdf.set_font('Arial', '', 8)
        
        # Acumulador financiero en RAM.
        # ¿Por qué?: Variable float inicializada en 0.0.
        # ¿Para qué?: Calcular el total de MXN recaudado iterando una sola vez los registros, sin requerir una consulta SQL COUNT/SUM adicional.
        total_ingresos_mxn = 0.0

        for fila in viajes_hoy:
            folio, hr_inicio, hr_fin, origen, destino, precio = fila
            
            # ¿Por qué?: String slicing '[:60]'.
            # ¿Para qué?: Prevenir que un nombre de hotel excesivamente largo rompa la celda de FPDF e invada la columna de 'Ingreso'.
            ruta = f"{origen} a {destino}"[:60]
            
            # ¿Por qué?: Casteo defensivo a float.
            # ¿Para qué?: Previene excepciones matemáticas si PostgreSQL devolvió un valor nulo.
            precio_val = float(precio) if precio is not None else 0.0
            total_ingresos_mxn += precio_val
            
            pdf.cell(anchos[0], 8, str(folio), 1, 0, 'C')
            pdf.cell(anchos[1], 8, str(hr_inicio or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[2], 8, str(hr_fin or 'N/A'), 1, 0, 'C')
            pdf.cell(anchos[3], 8, ruta, 1, 0, 'L')
            
            # ¿Por qué?: Interpolación de strings con formato ':,.2f'.
            # ¿Para qué?: Mostrar el ingreso unitario estrictamente en moneda (ej. $1,500.00 MXN).
            pdf.cell(anchos[4], 8, f'${precio_val:,.2f} MXN', 1, 0, 'R')
            pdf.ln()

        # 6. Resumen Financiero del Día
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(160, 10, 'TOTAL INGRESOS DEL DIA:', 0, 0, 'R')
        pdf.cell(30, 10, f'${total_ingresos_mxn:,.2f} MXN', 0, 1, 'R')
        
        # 7. Serialización Binaria (Blobs)
        # ¿Por qué?: Manejo de archivos virtuales con io.BytesIO().
        # ¿Para qué?: Mantener la arquitectura "Stateless"; evitamos escribir el PDF en el disco duro de Render, operando todo fluidamente en la memoria RAM del servidor.
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        # Preparación para Webhooks (n8n Fase 3)
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
                peticion_http = urllib.request.Request(
                    webhook_url, 
                    data=datos_json, 
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(peticion_http, timeout=3)
        except Exception:
            pass
        
        salida_pdf.seek(0)
        
        # ¿Por qué?: Directiva HTTP 'as_attachment=True'.
        # ¿Para qué?: Forzar al navegador del usuario (Safari/Chrome móvil) a abrir el cuadro de diálogo de descarga nativo del OS.
        return send_file(
            salida_pdf, 
            as_attachment=True, 
            download_name=f'Corte_Caja_{fecha_actual_cancun}.pdf', 
            mimetype='application/pdf'
        )
        
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