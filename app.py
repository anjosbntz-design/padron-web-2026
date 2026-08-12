from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)  # Permite peticiones desde GitHub Pages / Cloudflare Pages

DB_NAME = "padron.db"

def init_db_indexes():
    """Crea indices para acelerar las busquedas con TRIM/CAST a menos de 0.1s"""
    if os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            
            # Indice directo
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_padron_cedula ON padron (cedula);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inhabilitados_cedula ON inhabilitados_historico (cedula);")
            
            # Indice de expresion para acelerar TRIM(cedula)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_padron_cedula_trim ON padron (CAST(TRIM(cedula) AS TEXT));")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inh_cedula_trim ON inhabilitados_historico (CAST(TRIM(cedula) AS TEXT));")
            
            conn.commit()
            conn.close()
            print("--- Indices de SQLite verificados con exito ---")
        except Exception as e:
            print(f"Error al verificar indices: {e}")

# Ejecuta la optimización al iniciar la aplicación en Render
init_db_indexes()

def formatear_fecha(fecha_str):
    if not fecha_str or str(fecha_str).strip() in ['None', '']:
        return ""
    fecha_clean = str(fecha_str).strip().split()[0]
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            dt = datetime.strptime(fecha_clean, fmt)
            return f"{dt.day}/{dt.month}/{dt.year}"
        except ValueError:
            continue
    return fecha_clean

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    # Retorna la vista limpia sin pasar ninguna cedula por defecto
    return render_template('index.html')

@app.route('/api/consultar', methods=['GET'])
def consultar_cedula():
    cedula = request.args.get('cedula', '').strip()
    if not cedula:
        return jsonify({'error': 'Debe ingresar un número de cédula.'}), 400

    if not os.path.exists(DB_NAME):
        return jsonify({'error': 'Base de datos no encontrada.'}), 500

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. INSCRIPCIÓN HABILITADA RCP (Optimizada con índice)
    cursor.execute('''
        SELECT 
            p.cedula, p.nombres, p.apellidos,
            p.departamento, d.nombre AS dep_nombre,
            p.distrito, dis.nombre AS dis_nombre,
            p.zona, z.nombre AS zon_nombre,
            p.local, l.nombre AS loc_nombre,
            p.mesa, p.orden, p.sexo, p.fec_nac, n.nombre AS nac_nombre,
            p.tipo_voto, p.pueblo_indigena, p.comunidad_indigena
        FROM padron p
        LEFT JOIN departamentos d ON p.departamento = d.id
        LEFT JOIN distritos dis ON (p.departamento = dis.id_depto AND p.distrito = dis.id_distrito)
        LEFT JOIN zonas z ON (p.departamento = z.id_depto AND p.distrito = z.id_distrito AND p.zona = z.id_zona)
        LEFT JOIN locales l ON (p.departamento = l.id_depto AND p.distrito = l.id_distrito AND p.zona = l.id_zona AND p.local = l.id_local)
        LEFT JOIN nacionalidades n ON p.nacionalidad = n.id
        WHERE CAST(TRIM(p.cedula) AS TEXT) = ?
    ''', (cedula,))
    h = cursor.fetchone()

    habilitado = None
    if h:
        tipo_v = "MESA NORMAL" if str(h['tipo_voto']).strip() in ['0', '', 'None'] else h['tipo_voto']
        habilitado = {
            'cedula': h['cedula'],
            'nombre_completo': f"{h['nombres']}, {h['apellidos']}",
            'nacionalidad': h['nac_nombre'] or 'PARAGUAYA',
            'departamento': f"{h['departamento']} - {h['dep_nombre'] or ''}",
            'fec_nac': formatear_fecha(h['fec_nac']),
            'distrito': f"{h['distrito']} - {h['dis_nombre'] or ''}",
            'sexo': h['sexo'],
            'zona': f"{h['zona']} - {h['zon_nombre'] or ''}",
            'local': f"{h['local']} - {h['loc_nombre'] or ''}",
            'mesa': h['mesa'],
            'orden': h['orden'],
            'tipo_voto': tipo_v,
            'pueblo_indigena': h['pueblo_indigena'] or 'SIN DATOS',
            'comunidad_indigena': h['comunidad_indigena'] or 'SIN DATOS'
        }

    # 2. INSCRIPCIONES NO HABILITADAS - HISTÓRICO
    cursor.execute('''
        SELECT 
            i.cedula, i.nombres, i.apellidos,
            i.departamento, d.nombre AS dep_nombre,
            i.distrito, dis.nombre AS dis_nombre,
            i.zona, z.nombre AS zon_nombre,
            i.local, l.nombre AS loc_nombre,
            i.motivo, i.detalle, i.fecha_inscr, i.tipo_inscr, i.talonario, i.boleta
        FROM inhabilitados_historico i
        LEFT JOIN departamentos d ON i.departamento = d.id
        LEFT JOIN distritos dis ON (i.departamento = dis.id_depto AND i.distrito = dis.id_distrito)
        LEFT JOIN zonas z ON (i.departamento = z.id_depto AND i.distrito = z.id_distrito AND i.zona = z.id_zona)
        LEFT JOIN locales l ON (i.departamento = l.id_depto AND i.distrito = l.id_distrito AND i.zona = l.id_zona AND i.local = l.id_local)
        WHERE CAST(TRIM(i.cedula) AS TEXT) = ?
    ''', (cedula,))
    inh_rows = cursor.fetchall()

    historico = []
    for row in inh_rows:
        historico.append({
            'cedula': row['cedula'],
            'nombre_completo': f"{row['nombres']}, {row['apellidos']}",
            'motivo': row['motivo'],
            'detalle': row['detalle'],
            'departamento': f"{row['departamento']} - {row['dep_nombre'] or ''}",
            'distrito': f"{row['distrito']} - {row['dis_nombre'] or ''}",
            'zona': f"{row['zona']} - {row['zon_nombre'] or ''}",
            'local': f"{row['local']} - {row['loc_nombre'] or ''}",
            'fecha_inscr': formatear_fecha(row['fecha_inscr']),
            'tipo_inscr': row['tipo_inscr'],
            'talonario': row['talonario'],
            'boleta': row['boleta']
        })

    conn.close()

    return jsonify({
        'habilitado': habilitado,
        'historico': historico
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)