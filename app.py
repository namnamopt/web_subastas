from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.utils import secure_filename
from functools import wraps
import os
import hashlib
from datetime import datetime
import logging

from config import Config
from conexion_db import DatabaseConnection

# Configuración de logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Crear carpeta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============ FUNCIONES AUXILIARES ============
def rows_to_dict(rows, columns):
    """Convierte múltiples filas de pyodbc a lista de diccionarios"""
    result = []
    for row in rows:
        try:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col] = row[i]
            result.append(row_dict)
        except Exception as e:
            print(f"Error convirtiendo fila: {e}")
            print(f"Row: {row}")
            print(f"Columns: {columns}")
    return result

def row_to_dict(row, columns):
    """Convierte una fila de pyodbc a diccionario"""
    if row:
        return {columns[i]: row[i] for i in range(len(columns))}
    return None

# ============ DECORADORES ============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicia sesión', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicia sesión', 'warning')
            return redirect(url_for('login'))
        if session.get('rol') != 'administrador':
            flash('Acceso denegado', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ============ MIDDLEWARE ============
@app.before_request
def before_request():
    try:
        DatabaseConnection.get_connection()
    except Exception as e:
        logger.error(f"Error de conexión: {e}")

@app.teardown_appcontext
def close_db(error):
    DatabaseConnection.close_connection(error)

# ============ RUTAS DE AUTENTICACIÓN ============
@app.route('/')
def index():
    """Página principal - Consulta sin fecha"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # ✅ Consulta SIN fecha - solo estado activo
        cursor.execute("""
            SELECT 
                id_producto,
                nombre,
                descripcion,
                precio_inicial,
                precio_actual,
                ruta_imagen,
                fecha_fin,
                estado
            FROM Productos
            WHERE estado = 'activo'
        """)
        
        rows = cursor.fetchall()
        cursor.close()
        
        productos = []
        for row in rows:
            producto = {
                'id_producto': row[0],
                'nombre': row[1],
                'descripcion': row[2],
                'precio_inicial': float(row[3]) if row[3] else 0,
                'precio_actual': float(row[4]) if row[4] else 0,
                'ruta_imagen': row[5],
                'fecha_fin': row[6],
                'estado': row[7],
                'total_pujas': 0
            }
            productos.append(producto)
        
        print(f"🔍 Productos encontrados: {len(productos)}")
        
        return render_template('index.html', productos=productos, user=session.get('user'))
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        flash('Error al cargar la página', 'danger')
        return render_template('index.html', productos=[], user=session.get('user'))
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            conn = DatabaseConnection.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM Usuarios WHERE email = ? AND activo = 1", (email,))
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                
                # Acceso por índice: 0=id_usuario, 1=nombre, 2=email, 3=password, 4=rol
                if password_hash == row[3]:
                    session['user_id'] = row[0]
                    session['user'] = row[1]
                    session['rol'] = row[4]
                    
                    flash(f'¡Bienvenido {row[1]}!', 'success')
                    
                    if row[4] == 'administrador':
                        return redirect(url_for('dashboard_admin'))
                    else:
                        return redirect(url_for('index'))
                else:
                    flash('Contraseña incorrecta', 'danger')
            else:
                flash('Usuario no encontrado', 'danger')
                
        except Exception as e:
            logger.error(f"Error en login: {e}")
            flash('Error al iniciar sesión', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'success')
    return redirect(url_for('login'))

# ============ RUTAS DE ADMINISTRACIÓN ============
@app.route('/dashboard_admin')
@admin_required
def dashboard_admin():
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Estadísticas básicas
        cursor.execute("SELECT COUNT(*) FROM Productos")
        total_productos = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM Productos WHERE estado = 'activo'")
        productos_activos = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM Usuarios WHERE rol = 'cliente'")
        total_clientes = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM Pujas")
        total_pujas = cursor.fetchone()[0]
        
        # Nuevas estadísticas
        cursor.execute("SELECT COUNT(*) FROM Productos WHERE estado = 'finalizado'")
        productos_finalizados = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM Pujas WHERE CAST(fecha_puja AS DATE) = CAST(GETDATE() AS DATE)")
        pujas_hoy = cursor.fetchone()[0]
        
        cursor.execute("SELECT ISNULL(SUM(monto), 0) FROM Pujas")
        total_recaudado = cursor.fetchone()[0]
        
        # ✅ PRODUCTOS MÁS PUJADOS (Top 5)
        cursor.execute("""
            SELECT TOP 5 
                p.nombre,
                COUNT(pu.id_puja) as total_pujas
            FROM Productos p
            LEFT JOIN Pujas pu ON p.id_producto = pu.id_producto
            WHERE p.estado = 'activo'
            GROUP BY p.id_producto, p.nombre
            ORDER BY total_pujas DESC
        """)
        top_productos = cursor.fetchall()
        
        # ✅ USUARIOS MÁS ACTIVOS (Top 5)
        cursor.execute("""
            SELECT TOP 5 
                u.nombre,
                COUNT(pu.id_puja) as total_pujas
            FROM Usuarios u
            LEFT JOIN Pujas pu ON u.id_usuario = pu.id_usuario
            WHERE u.rol = 'cliente'
            GROUP BY u.id_usuario, u.nombre
            ORDER BY total_pujas DESC
        """)
        top_usuarios = cursor.fetchall()
        
        cursor.close()
        
        now = datetime.now()
        
        return render_template('dashboard_admin.html',
                             total_productos=total_productos,
                             productos_activos=productos_activos,
                             total_clientes=total_clientes,
                             total_pujas=total_pujas,
                             productos_finalizados=productos_finalizados,
                             pujas_hoy=pujas_hoy,
                             total_recaudado=total_recaudado,
                             top_productos=top_productos,  # ✅ Agregado
                             top_usuarios=top_usuarios,    # ✅ Agregado
                             now=now,
                             user=session.get('user'))
    except Exception as e:
        logger.error(f"Error en dashboard: {e}")
        flash('Error al cargar el dashboard', 'danger')
        return render_template('dashboard_admin.html', 
                             total_productos=0,
                             productos_activos=0,
                             total_clientes=0,
                             total_pujas=0,
                             productos_finalizados=0,
                             pujas_hoy=0,
                             total_recaudado=0,
                             top_productos=[],  # ✅ Agregado
                             top_usuarios=[],    # ✅ Agregado
                             now=datetime.now(),
                             user=session.get('user'))

@app.route('/admin/reportes')
@admin_required
def admin_reportes():
    """Panel de reportes y estadísticas"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Ventas por mes (últimos 6 meses)
        cursor.execute("""
            SELECT 
                DATEPART(MONTH, fecha_puja) as mes,
                DATEPART(YEAR, fecha_puja) as anio,
                COUNT(*) as total_pujas,
                ISNULL(SUM(monto), 0) as total_recaudado
            FROM Pujas
            WHERE fecha_puja >= DATEADD(MONTH, -6, GETDATE())
            GROUP BY DATEPART(YEAR, fecha_puja), DATEPART(MONTH, fecha_puja)
            ORDER BY anio DESC, mes DESC
        """)
        
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        reportes_mensuales = rows_to_dict(rows, columns)
        
        # Top 5 productos con más pujas
        cursor.execute("""
            SELECT TOP 5 
                p.nombre,
                COUNT(pu.id_puja) as total_pujas,
                ISNULL(MAX(pu.monto), 0) as puja_maxima,
                p.precio_actual
            FROM Productos p
            LEFT JOIN Pujas pu ON p.id_producto = pu.id_producto
            GROUP BY p.id_producto, p.nombre, p.precio_actual
            ORDER BY total_pujas DESC
        """)
        
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        top_productos = rows_to_dict(rows, columns)
        
        # Usuarios más activos
        cursor.execute("""
            SELECT TOP 5 
                u.nombre,
                u.email,
                COUNT(pu.id_puja) as total_pujas,
                ISNULL(SUM(pu.monto), 0) as total_gastado
            FROM Usuarios u
            INNER JOIN Pujas pu ON u.id_usuario = pu.id_usuario
            WHERE u.rol = 'cliente'
            GROUP BY u.id_usuario, u.nombre, u.email
            ORDER BY total_pujas DESC
        """)
        
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        top_usuarios = rows_to_dict(rows, columns)
        
        cursor.close()
        
        return render_template('admin_reportes.html',
                             reportes_mensuales=reportes_mensuales,
                             top_productos=top_productos,
                             top_usuarios=top_usuarios,
                             user=session.get('user'))
        
    except Exception as e:
        logger.error(f"Error en admin_reportes: {e}")
        flash('Error al cargar reportes', 'danger')
        return render_template('admin_reportes.html', 
                             reportes_mensuales=[],
                             top_productos=[],
                             top_usuarios=[],
                             user=session.get('user'))

@app.route('/admin/configuracion', methods=['GET', 'POST'])
@admin_required
def admin_configuracion():
    """Configuración del sistema"""
    if request.method == 'POST':
        flash('Configuración actualizada exitosamente', 'success')
        return redirect(url_for('admin_configuracion'))
    
    return render_template('admin_configuracion.html', user=session.get('user'))

@app.route('/admin/clientes')
@admin_required
def admin_clientes():
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                u.id_usuario,
                u.nombre,
                u.email,
                u.fecha_registro,
                u.activo,
                (SELECT COUNT(*) FROM Pujas WHERE id_usuario = u.id_usuario) as total_pujas,
                (SELECT COUNT(*) FROM Productos WHERE id_usuario_creador = u.id_usuario) as total_productos
            FROM Usuarios u
            WHERE u.rol = 'cliente'
            ORDER BY u.fecha_registro DESC
        ''')
        
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        clientes = rows_to_dict(rows, columns)
        cursor.close()
        
        return render_template('admin_clientes.html', clientes=clientes, user=session.get('user'))
        
    except Exception as e:
        logger.error(f"Error en admin_clientes: {e}")
        flash('Error al cargar los clientes', 'danger')
        return render_template('admin_clientes.html', clientes=[], user=session.get('user'))

@app.route('/admin/cliente/eliminar/<int:id_usuario>', methods=['POST'])
@admin_required
def eliminar_cliente(id_usuario):
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar si el cliente existe
        cursor.execute("SELECT * FROM Usuarios WHERE id_usuario = ? AND rol = 'cliente'", (id_usuario,))
        if not cursor.fetchone():
            cursor.close()
            return jsonify({'success': False, 'error': 'Cliente no encontrado'}), 404
        
        # Eliminar pujas del cliente
        cursor.execute("DELETE FROM Pujas WHERE id_usuario = ?", (id_usuario,))
        
        # Eliminar productos del cliente
        cursor.execute("DELETE FROM Productos WHERE id_usuario_creador = ?", (id_usuario,))
        
        # Eliminar usuario
        cursor.execute("DELETE FROM Usuarios WHERE id_usuario = ?", (id_usuario,))
        
        conn.commit()
        cursor.close()
        
        flash('Cliente eliminado exitosamente.', 'success')
        return redirect(url_for('admin_clientes'))
        
    except Exception as e:
        logger.error(f"Error eliminando cliente: {e}")
        flash('Error al eliminar el cliente', 'danger')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/productos')
@admin_required
def admin_productos():
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                p.*,
                u.nombre as creador,
                (SELECT COUNT(*) FROM Pujas WHERE id_producto = p.id_producto) as total_pujas
            FROM Productos p
            LEFT JOIN Usuarios u ON p.id_usuario_creador = u.id_usuario
            ORDER BY p.fecha_fin DESC
        ''')
        
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        productos = rows_to_dict(rows, columns)
        cursor.close()
        
        return render_template('admin_productos.html', productos=productos, user=session.get('user'))
        
    except Exception as e:
        logger.error(f"Error en admin_productos: {e}")
        flash('Error al cargar los productos', 'danger')
        return render_template('admin_productos.html', productos=[], user=session.get('user'))

@app.route('/admin/producto/editar/<int:id_producto>', methods=['GET', 'POST'])
@admin_required
def editar_producto(id_producto):
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        if request.method == 'POST':
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            estado = request.form.get('estado')
            precio = request.form.get('precio')
            fecha_fin_str = request.form.get('fecha_fin')
            
            # Validar campos requeridos
            if not all([nombre, descripcion, estado, precio]):
                flash('Todos los campos son requeridos.', 'warning')
                return redirect(url_for('editar_producto', id_producto=id_producto))
            
            try:
                precio = float(precio)
            except ValueError:
                flash('Precio inválido', 'danger')
                return redirect(url_for('editar_producto', id_producto=id_producto))
            
            # Manejar imagen
            imagen_filename = None
            if 'imagen' in request.files:
                imagen = request.files['imagen']
                if imagen and imagen.filename != '':
                    # Validar extensión
                    ext = imagen.filename.rsplit('.', 1)[1].lower() if '.' in imagen.filename else ''
                    if ext in app.config['ALLOWED_EXTENSIONS']:
                        # Eliminar imagen anterior si existe
                        cursor.execute("SELECT ruta_imagen FROM Productos WHERE id_producto = ?", (id_producto,))
                        old_row = cursor.fetchone()
                        if old_row and old_row[0]:
                            try:
                                old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_row[0])
                                if os.path.exists(old_path):
                                    os.remove(old_path)
                            except Exception as e:
                                logger.error(f"Error eliminando imagen anterior: {e}")
                        
                        # Guardar nueva imagen
                        filename = secure_filename(imagen.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        filename = f"{timestamp}_{filename}"
                        imagen.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        imagen_filename = filename
                    else:
                        flash('Tipo de archivo no permitido. Use: jpg, jpeg, png, gif', 'warning')
                        return redirect(url_for('editar_producto', id_producto=id_producto))
            
            # Construir consulta UPDATE
            if imagen_filename:
                cursor.execute('''
                    UPDATE Productos 
                    SET nombre = ?, 
                        descripcion = ?, 
                        precio_actual = ?,
                        precio_inicial = ?,
                        estado = ?, 
                        ruta_imagen = ?
                    WHERE id_producto = ?
                ''', (nombre, descripcion, precio, precio, estado, imagen_filename, id_producto))
            else:
                cursor.execute('''
                    UPDATE Productos 
                    SET nombre = ?, 
                        descripcion = ?, 
                        precio_actual = ?,
                        precio_inicial = ?,
                        estado = ?
                    WHERE id_producto = ?
                ''', (nombre, descripcion, precio, precio, estado, id_producto))
            
            conn.commit()
            flash('Producto actualizado exitosamente.', 'success')
            return redirect(url_for('admin_productos'))
        
        # GET - Obtener producto
        cursor.execute('''
            SELECT * FROM Productos WHERE id_producto = ?
        ''', (id_producto,))
        
        row = cursor.fetchone()
        if not row:
            flash('Producto no encontrado', 'danger')
            return redirect(url_for('admin_productos'))
        
        columns = [column[0] for column in cursor.description]
        producto = row_to_dict(row, columns)
        cursor.close()
        
        return render_template('editar_producto.html', producto=producto, user=session.get('user'))
        
    except Exception as e:
        logger.error(f"Error editando producto: {e}")
        flash('Error al editar el producto', 'danger')
        return redirect(url_for('admin_productos'))
    
@app.route('/admin/producto/eliminar/<int:id_producto>', methods=['POST'])
@admin_required
def eliminar_producto(id_producto):
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar si tiene pujas
        cursor.execute('''
            SELECT COUNT(*) FROM Pujas WHERE id_producto = ?
        ''', (id_producto,))
        
        tiene_pujas = cursor.fetchone()[0] > 0
        
        if tiene_pujas:
            # Solo marcar como finalizado
            cursor.execute('''
                UPDATE Productos SET estado = 'finalizado' WHERE id_producto = ?
            ''', (id_producto,))
            flash('Producto marcado como finalizado.', 'success')
        else:
            # Si no tiene pujas, eliminar completamente
            # Primero eliminar la imagen si existe
            cursor.execute("SELECT ruta_imagen FROM Productos WHERE id_producto = ?", (id_producto,))
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    imagen_path = os.path.join(app.config['UPLOAD_FOLDER'], row[0])
                    if os.path.exists(imagen_path):
                        os.remove(imagen_path)
                except Exception as e:
                    logger.error(f"Error eliminando imagen: {e}")
            
            # Eliminar producto
            cursor.execute("DELETE FROM Productos WHERE id_producto = ?", (id_producto,))
            flash('Producto eliminado exitosamente.', 'success')
        
        conn.commit()
        cursor.close()
        
        return redirect(url_for('admin_productos'))
        
    except Exception as e:
        logger.error(f"Error eliminando producto: {e}")
        flash('Error al eliminar el producto', 'danger')
        return redirect(url_for('admin_productos'))

@app.route('/admin/producto/nuevo', methods=['GET', 'POST'])
@admin_required
def nuevo_producto():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        precio_inicial = request.form.get('precio_inicial')
        fecha_fin_str = request.form.get('fecha_fin')
        
        if not all([nombre, descripcion, precio_inicial, fecha_fin_str]):
            flash('Todos los campos son estrictamente requeridos.', 'warning')
            return render_template('nuevo_producto.html', user=session.get('user'))
        
        try:
            precio = float(precio_inicial)
            imagen_filename = None
            
            # Convertir fecha al formato que SQL Server entiende
            try:
                fecha_fin_dt = datetime.fromisoformat(fecha_fin_str)
            except:
                try:
                    fecha_fin_dt = datetime.strptime(fecha_fin_str, '%d/%m/%Y %H:%M')
                except:
                    fecha_fin_dt = datetime.strptime(fecha_fin_str, '%Y-%m-%d %H:%M:%S')
            
            fecha_fin_sql = fecha_fin_dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Manejar imagen
            if 'imagen' in request.files:
                imagen = request.files['imagen']
                if imagen and imagen.filename != '':
                    # Validar extensión
                    ext = imagen.filename.rsplit('.', 1)[1].lower() if '.' in imagen.filename else ''
                    if ext in app.config['ALLOWED_EXTENSIONS']:
                        filename = secure_filename(imagen.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        filename = f"{timestamp}_{filename}"
                        imagen.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        imagen_filename = filename
                    else:
                        flash('Tipo de archivo no permitido. Use: jpg, jpeg, png, gif', 'warning')
                        return render_template('nuevo_producto.html', user=session.get('user'))
            
            conn = DatabaseConnection.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO Productos (nombre, descripcion, precio_inicial, precio_actual, 
                                     ruta_imagen, fecha_fin, id_usuario_creador, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (nombre, descripcion, precio, precio, imagen_filename, fecha_fin_sql, session['user_id'], 'activo'))
            
            conn.commit()
            cursor.close()
            
            flash('Producto creado exitosamente.', 'success')
            return redirect(url_for('admin_productos'))
                
        except Exception as e:
            logger.error(f"Error creando producto: {e}")
            flash(f'Error al guardar el producto: {str(e)}', 'danger')
            return render_template('nuevo_producto.html', user=session.get('user'))
    
    return render_template('nuevo_producto.html', user=session.get('user'))

# ============ RUTAS DE SUBASTAS ============
@app.route('/producto/<int:id_producto>')
def detalle_producto(id_producto):
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Obtener producto
        cursor.execute('''
            SELECT p.*, u.nombre as creador
            FROM Productos p
            LEFT JOIN Usuarios u ON p.id_usuario_creador = u.id_usuario
            WHERE p.id_producto = ?
        ''', (id_producto,))
        
        row = cursor.fetchone()
        if not row:
            flash('Producto no encontrado', 'danger')
            return redirect(url_for('index'))
        
        columns = [column[0] for column in cursor.description]
        producto = row_to_dict(row, columns)
        
        # Obtener pujas
        cursor.execute('''
            SELECT pu.*, u.nombre, u.email
            FROM Pujas pu
            INNER JOIN Usuarios u ON pu.id_usuario = u.id_usuario
            WHERE pu.id_producto = ?
            ORDER BY pu.monto DESC
        ''', (id_producto,))
        
        rows = cursor.fetchall()
        columns_pujas = [column[0] for column in cursor.description]
        pujas = rows_to_dict(rows, columns_pujas)
        cursor.close()
        
        return render_template('detalle_producto.html', 
                             producto=producto, 
                             pujas=pujas,
                             user=session.get('user'))
                             
    except Exception as e:
        logger.error(f"Error en detalle_producto: {e}")
        flash('Error al cargar el producto', 'danger')
        return redirect(url_for('index'))

@app.route('/api/pujar', methods=['POST'])
@login_required
def realizar_puja():
    try:
        id_producto = request.form.get('id_producto')
        monto = request.form.get('monto')
        
        if not id_producto or not monto:
            return jsonify({'success': False, 'error': 'Datos incompletos'}), 400
        
        try:
            id_producto = int(id_producto)
            monto = float(monto)
        except ValueError:
            return jsonify({'success': False, 'error': 'Datos inválidos'}), 400
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar producto
        cursor.execute('''
            SELECT precio_actual, fecha_fin, estado 
            FROM Productos 
            WHERE id_producto = ? 
        ''', (id_producto,))
        
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify({'success': False, 'error': 'Producto no encontrado'}), 400
        
        precio_actual = float(row[0])
        fecha_fin = row[1]
        estado = row[2]
        
        # Validar que el producto esté activo
        if estado != 'activo':
            cursor.close()
            return jsonify({'success': False, 'error': 'Esta subasta no está activa'}), 400
        
        # Validar que no haya expirado
        if fecha_fin and fecha_fin <= datetime.now():
            cursor.close()
            return jsonify({'success': False, 'error': 'La subasta ha finalizado'}), 400
        
        # Validar monto
        if monto <= precio_actual:
            cursor.close()
            mensaje = f'Ingrese un monto mayor al ofrecido (Monto actual: ${precio_actual:.2f})'
            return jsonify({'success': False, 'error': mensaje}), 400
        
        try:
            # Registrar puja
            cursor.execute('''
                INSERT INTO Pujas (id_producto, id_usuario, monto, fecha_puja)
                VALUES (?, ?, ?, GETDATE())
            ''', (id_producto, session['user_id'], monto))
            
            # Actualizar precio actual del producto
            cursor.execute('''
                UPDATE Productos SET precio_actual = ? WHERE id_producto = ?
            ''', (monto, id_producto))
            
            conn.commit()
            logger.info(f"Puja registrada: Usuario {session['user_id']}, Producto {id_producto}, Monto {monto}")
            
            return jsonify({
                'success': True,
                'message': '¡Puja realizada con éxito!',
                'nuevo_precio': monto
            })
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error insertando puja: {e}")
            return jsonify({'success': False, 'error': 'Error al procesar la puja'}), 500
        finally:
            cursor.close()
        
    except Exception as e:
        logger.error(f"Error en realizar_puja: {e}")
        return jsonify({'success': False, 'error': 'Error al procesar la puja'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)