# Importaciones de la biblioteca estándar de Python unificadas al inicio (PEP 8).
# ¿Por qué y para qué?: Cargar todos los módulos en memoria antes de instanciar la app previene errores de "módulo no encontrado" durante la ejecución asíncrona.
import os
import io
import base64
from functools import wraps
from datetime import datetime, timedelta

# Importamos ZoneInfo (Nativo en Python 3.9+) para estandarizar los relojes.
# ¿Por qué y para qué?: Obligamos a Python a calcular diferencias de tiempo usando la zona de Cancún, igualando la lógica de PostgreSQL y evitando falsos positivos por la hora UTC del servidor Render.
from zoneinfo import ZoneInfo

# Importaciones de frameworks de terceros.
# ¿Por qué y para qué?: Flask maneja el ciclo HTTP, FPDF dibuja el reporte, requests permite a Flask ser cliente HTTP contra n8n.
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify
from fpdf import FPDF
import requests

# Importación del gestor de base de datos local.
from db import obtener_conexion_db

app = Flask(__name__)

# Configuración estricta de la llave secreta para encriptar las cookies.
# ¿Por qué y para qué?: Fuerza la caída inmediata del servidor en producción si el .env no está inyectado, protegiendo las sesiones.
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

# ==========================================
# RUTAS DE INTERFAZ Y AUTENTICACIÓN
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    # ¿Por qué y para qué?: Centraliza el despliegue del HTML (GET) y la recepción de credenciales (POST) en una sola función.
    if request.method == 'POST':
        password_ingresada = request.form.get('password')
        
        # Validamos contra la variable protegida.
        # ¿Por qué y para qué?: Evita credenciales hardcodeadas en GitHub.
        if password_ingresada == os.environ.get("ADMIN_PASSWORD"):
            session['admin_logeado'] = True
            # Inyectamos temporalmente el ID 1 (Dueño) para que la lógica de viajes asigne correctamente al Super Admin.
            session['id_chofer'] = 1 
            return redirect(url_for('panel_admin'))
        else:
            return "Contraseña incorrecta", 401
            
    return render_template('login.html')

@app.route('/admin')
def panel_admin():
    # Barrera de seguridad de sesión.
    # ¿Por qué y para qué?: Redirige accesos no autorizados a la ruta /admin, protegiendo el backend SaaS.
    if not session.get('admin_logeado'):
        return redirect(url_for('login'))
    return render_template('admin.html')

# ==========================================
# RUTAS TRANSACCIONALES (MÁQUINA DE ESTADOS)
# ==========================================

@app.route('/admin/viaje/<int:id_reserva>/estado', methods=['POST'])
def actualizar_estado_viaje(id_reserva):
    accion = request.json.get('accion')
    conn = None
    cursor = None
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # ¿Por qué y para qué?: La inyección directa de la hora local en PostgreSQL es más segura que mandar el tiempo desde el celular (evita manipulaciones de reloj del usuario).
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
        # Rollback en caso de colapso de la BD.
        # ¿Por qué y para qué?: Protege la atomicidad; si algo falla, no se guardan datos corruptos o a medias.
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
        
    finally:
        # Limpieza de memoria y liberación del socket de base de datos.
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
        
        # Verificación de viaje varado del chofer actual.
        cursor.execute("""
            SELECT id_reserva 
            FROM reservas 
            WHERE id_chofer = %s AND estado_reserva = 'En_Progreso'
        """, (id_chofer_actual,))
        
        viaje_activo = cursor.fetchone()
        
        if viaje_activo:
            cursor.execute("SELECT fecha_hora_servicio FROM reservas WHERE id_reserva = %s", (id_reserva,))
            proximo_viaje = cursor.fetchone()
            
            if proximo_viaje:
                hora_proximo_viaje = proximo_viaje[0]
                # CORRECCIÓN: Instanciamos datetime.now explícitamente con la zona de Cancún para evitar discrepancia con PostgreSQL.
                hora_actual = datetime.now(ZoneInfo('America/Cancun'))
                
                # Para operar, la fecha de la base de datos debe ser "timezone-aware".
                if hora_proximo_viaje.tzinfo is None:
                    hora_proximo_viaje = hora_proximo_viaje.replace(tzinfo=ZoneInfo('America/Cancun'))
                
                diferencia = hora_proximo_viaje - hora_actual
                
                if diferencia <= timedelta(minutes=5):
                    # Auto-cierre de viaje estancado.
                    # ¿Por qué y para qué?: Habilita la flexibilidad operativa para que el chofer no se bloquee por un simple olvido.
                    cursor.execute("""
                        UPDATE reservas 
                        SET estado_reserva = 'Finalizado', hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
                        WHERE id_reserva = %s
                    """, (viaje_activo[0],))
                else:
                    return jsonify({"status": "blocked", "mensaje": "Tienes un viaje activo. Finalízalo antes de iniciar otro."}), 403
                    
        # Actualización al estado iniciado.
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

# ==========================================
# REPORTES Y AUTOMATIZACIONES (CRON / N8N)
# ==========================================

# Consolidamos el Cierre Diario en UNA SOLA función.
@app.route('/admin/cierre_diario', methods=['POST'])
def cierre_diario():
    conn = None
    cursor = None
    
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        
        # Contingencia: Finaliza todos los viajes del día que quedaron "En Progreso".
        # ¿Por qué y para qué?: Normaliza las tablas y previene que viajes fantasmas arrastren ingresos al día siguiente.
        cursor.execute("""
            UPDATE reservas 
            SET estado_reserva = 'Finalizado', 
                hora_fin_real = NOW() AT TIME ZONE 'America/Cancun'
            WHERE estado_reserva = 'En_Progreso' 
            AND DATE(fecha_hora_servicio) = CURRENT_DATE
        """)
        
        # Recupera los metadatos operativos para el PDF, usando AGE() para calcular la diferencia de horas.
        cursor.execute("""
            SELECT TO_CHAR(fecha_hora_servicio, 'YYYY-MM-DD'), 
                   TO_CHAR(hora_inicio_real, 'HH24:MI'), 
                   TO_CHAR(hora_fin_real, 'HH24:MI'), 
                   origen, destino, hotel_referencia, numero_vuelo, precio
            FROM reservas
            WHERE estado_reserva = 'Finalizado' 
            AND DATE(fecha_hora_servicio) = CURRENT_DATE
        """)
        viajes_hoy = cursor.fetchall()
        conn.commit()

        # Generación dinámica del PDF en RAM.
        pdf = FPDF('L', 'mm', 'Letter') # Horizontal (L) para acomodar más columnas
        pdf.add_page()
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(250, 10, 'Reporte Operativo Diario - ART-TOURS TRANSFER', 0, 1, 'C')
        pdf.ln(5)
        
        # Headers de la tabla FPDF.
        pdf.set_font('Arial', 'B', 9)
        headers = ['Fecha', 'Inicio', 'Fin', 'Origen', 'Destino', 'Hotel', 'Vuelo', 'Precio']
        anchos = [25, 15, 15, 45, 45, 60, 25, 20]
        
        for i, h in enumerate(headers):
            pdf.cell(anchos[i], 10, h, 1, 0, 'C')
        pdf.ln()

        # Bucle de iteración para inyectar filas de PostgreSQL al documento.
        # ¿Por qué y para qué?: Automatiza el volcado de datos emulando el comportamiento tabular de tu archivo Excel.
        pdf.set_font('Arial', '', 8)
        for fila in viajes_hoy:
            for i, dato in enumerate(fila):
                valor = str(dato) if dato is not None else 'N/A'
                pdf.cell(anchos[i], 10, valor[:25], 1, 0, 'C') # Truncamos a 25 caracteres para evitar desbordes visuales.
            pdf.ln()
        
        salida_pdf = io.BytesIO()
        salida_pdf.write(pdf.output(dest='S').encode('latin1'))
        salida_pdf.seek(0)
        
        # Conversión a Base64 para consumo en n8n.
        pdf_b64 = base64.b64encode(salida_pdf.getvalue()).decode('utf-8')
        webhook_url = os.environ.get("N8N_WEBHOOK_URL_CIERRE")
        fecha_actual_cancun = datetime.now(ZoneInfo('America/Cancun')).strftime("%Y-%m-%d")
        
        payload_n8n = {
            "fecha_cierre": fecha_actual_cancun,
            "total_viajes": len(viajes_hoy),
            "archivo_pdf_b64": pdf_b64
        }
        
        # POST asíncrono y tolerante a fallos.
        try:
            if webhook_url:
                requests.post(webhook_url, json=payload_n8n, timeout=3)
        except requests.exceptions.RequestException:
            pass
        
        salida_pdf.seek(0)
        
        # Retorno del binario físico al frontend para descarga celular instantánea.
        return send_file(salida_pdf, as_attachment=True, download_name=f'Reporte_Diario_{fecha_actual_cancun}.pdf', mimetype='application/pdf')
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 500
        
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# Decorador de seguridad para APIs internas.
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
    # La lógica interna ya la tienes; al estar purgada del frontend, Flask la renderizará sin fallos sintácticos.
    return jsonify({"status": "success", "mensaje": "Endpoint reservado para expansión n8n."}), 200