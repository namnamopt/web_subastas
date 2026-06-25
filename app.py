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
    """Página principal - Muestra TODOS los productos"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Consulta SIN filtro - muestra todos los productos
        cursor.execute("""
            SELECT 
                id_producto,
                nombre,
                descripcion,
                precio_inicial,
                precio_actual,
                ruta_imagen,
                fecha_fin,
                estado,
                (SELECT COUNT(*) FROM Pujas WHERE id_producto = p.id_producto) as total_pujas
            FROM Productos p
            ORDER BY fecha_fin DESC
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
                'total_pujas': row[8] if len(row) > 8 else 0
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
    # Si hay un usuario logueado, redirigir
    if 'user_id' in session:
        if session.get('rol') == 'administrador':
            return redirect(url_for('dashboard_admin'))
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember')
        
        try:
            conn = DatabaseConnection.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM Usuarios WHERE email = ? AND activo = 1", (email,))
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                
                if password_hash == row[3]:  # row[3] es password
                    session['user_id'] = row[0]
                    session['user'] = row[1]
                    session['rol'] = row[4]
                    
                    # Actualizar último acceso
                    conn = DatabaseConnection.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE Usuarios SET ultimo_acceso = GETDATE() 
                        WHERE id_usuario = ?
                    """, (row[0],))
                    conn.commit()
                    cursor.close()
                    
                    flash(f'¡Bienvenido {row[1]}!', 'success')
                    
                    if row[4] == 'administrador':
                        return redirect(url_for('dashboard_admin'))
                    else:
                        return redirect(url_for('index'))
                else:
                    flash('Contraseña incorrecta', 'danger')
            else:
                flash('Usuario no encontrado o inactivo', 'danger')
                
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
    """Eliminar producto con transacción"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar si tiene pujas
        cursor.execute('SELECT COUNT(*) FROM Pujas WHERE id_producto = ?', (id_producto,))
        tiene_pujas = cursor.fetchone()[0] > 0
        
        # Obtener información del producto
        cursor.execute('''
            SELECT nombre, ruta_imagen, id_usuario_creador 
            FROM Productos WHERE id_producto = ?
        ''', (id_producto,))
        producto_info = cursor.fetchone()
        
        if not producto_info:
            flash('Producto no encontrado', 'danger')
            return redirect(url_for('admin_productos'))
        
        nombre_producto = producto_info[0]
        ruta_imagen = producto_info[1]
        id_creador = producto_info[2]
        
        # ============ INICIO DE TRANSACCIÓN ============
        try:
            conn = DatabaseConnection.begin_transaction()
            cursor = conn.cursor()
            
            if tiene_pujas:
                # Si tiene pujas, marcar como finalizado
                cursor.execute('''
                    UPDATE Productos 
                    SET estado = 'finalizado', updated_at = GETDATE()
                    WHERE id_producto = ?
                ''', (id_producto,))
                
                # Notificar a los usuarios que participaron
                cursor.execute('''
                    SELECT DISTINCT id_usuario FROM Pujas WHERE id_producto = ?
                ''', (id_producto,))
                
                usuarios = cursor.fetchall()
                for usuario in usuarios:
                    if usuario[0] != id_creador:
                        cursor.execute('''
                            INSERT INTO Notificaciones (id_usuario, tipo, titulo, mensaje, enlace)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            usuario[0],
                            'subasta_finalizada',
                            'Subasta finalizada',
                            f'La subasta "{nombre_producto}" ha sido finalizada por el administrador',
                            f'/producto/{id_producto}'
                        ))
                
                flash('Producto marcado como finalizado.', 'success')
            else:
                # Si no tiene pujas, eliminar completamente
                # 1️⃣ Eliminar la imagen
                if ruta_imagen:
                    try:
                        imagen_path = os.path.join(app.config['UPLOAD_FOLDER'], ruta_imagen)
                        if os.path.exists(imagen_path):
                            os.remove(imagen_path)
                    except Exception as e:
                        logger.error(f"Error eliminando imagen: {e}")
                
                # 2️⃣ Eliminar favoritos
                cursor.execute('DELETE FROM Favoritos WHERE id_producto = ?', (id_producto,))
                
                # 3️⃣ Eliminar pujas
                cursor.execute('DELETE FROM Pujas WHERE id_producto = ?', (id_producto,))
                
                # 4️⃣ Eliminar historial de precios
                cursor.execute('DELETE FROM HistorialPrecios WHERE id_producto = ?', (id_producto,))
                
                # 5️⃣ Eliminar producto
                cursor.execute('DELETE FROM Productos WHERE id_producto = ?', (id_producto,))
                
                flash('Producto eliminado exitosamente.', 'success')
            
            # ✅ Confirmar transacción
            DatabaseConnection.commit_transaction(conn)
            
        except Exception as e:
            # ❌ Reversar transacción
            DatabaseConnection.rollback_transaction(conn)
            logger.error(f"❌ Error en transacción: {e}")
            flash('Error al eliminar el producto', 'danger')
        finally:
            if cursor:
                cursor.close()
        
        return redirect(url_for('admin_productos'))
        
    except Exception as e:
        logger.error(f"❌ Error eliminando producto: {e}")
        flash('Error al eliminar el producto', 'danger')
        return redirect(url_for('admin_productos'))
    
    # ============ RUTAS PARA GESTIÓN DE PUJAS ============

@app.route('/admin/producto/<int:id_producto>/info')
@admin_required
def producto_info(id_producto):
    """Obtener información del producto para el modal"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT nombre FROM Productos WHERE id_producto = ?", (id_producto,))
        row = cursor.fetchone()
        cursor.close()
        
        if row:
            return jsonify({'nombre': row[0]})
        return jsonify({'error': 'Producto no encontrado'}), 404
        
    except Exception as e:
        logger.error(f"Error en producto_info: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/producto/<int:id_producto>/pujas')
@admin_required
def pujas_producto(id_producto):
    """Obtener todas las pujas de un producto"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar que el producto existe
        cursor.execute("SELECT nombre FROM Productos WHERE id_producto = ?", (id_producto,))
        if not cursor.fetchone():
            cursor.close()
            return jsonify({'error': 'Producto no encontrado'}), 404
        
        # Obtener todas las pujas del producto
        cursor.execute("""
            SELECT 
                p.id_puja,
                p.id_usuario,
                u.nombre as usuario_nombre,
                u.email as usuario_email,
                p.monto,
                p.fecha_puja
            FROM Pujas p
            LEFT JOIN Usuarios u ON p.id_usuario = u.id_usuario
            WHERE p.id_producto = ?
            ORDER BY p.fecha_puja DESC
        """, (id_producto,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        pujas_data = []
        for row in rows:
            # Formatear fecha
            fecha_str = "Fecha no disponible"
            if row[5]:
                try:
                    if isinstance(row[5], datetime):
                        fecha_str = row[5].strftime('%d/%m/%Y %H:%M')
                    else:
                        fecha_str = str(row[5])
                except:
                    fecha_str = str(row[5])
            
            pujas_data.append({
                'id_puja': row[0],
                'id_usuario': row[1],
                'usuario': row[2] or f"Usuario #{row[1]}",
                'email': row[3],
                'monto': float(row[4]) if row[4] else 0,
                'fecha_puja': fecha_str
            })
        
        return jsonify({
            'total': len(pujas_data),
            'pujas': pujas_data
        })
        
    except Exception as e:
        logger.error(f"Error en pujas_producto: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/puja/editar/<int:id_puja>', methods=['POST'])
@admin_required
def editar_puja(id_puja):
    """Editar el monto de una puja con transacción"""
    try:
        data = request.get_json()
        if not data or 'monto' not in data:
            return jsonify({'success': False, 'message': 'Datos incompletos'}), 400
        
        nuevo_monto = float(data['monto'])
        if nuevo_monto < 0:
            return jsonify({'success': False, 'message': 'El monto no puede ser negativo'}), 400
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Obtener información actual de la puja
        cursor.execute("""
            SELECT id_producto, monto, id_usuario
            FROM Pujas WHERE id_puja = ?
        """, (id_puja,))
        
        puja_actual = cursor.fetchone()
        if not puja_actual:
            cursor.close()
            return jsonify({'success': False, 'message': 'Puja no encontrada'}), 404
        
        id_producto = puja_actual[0]
        monto_anterior = puja_actual[1]
        id_usuario = puja_actual[2]
        
        # ============ INICIO DE TRANSACCIÓN ============
        try:
            conn = DatabaseConnection.begin_transaction()
            cursor = conn.cursor()
            
            # 1️⃣ Actualizar el monto de la puja
            cursor.execute("""
                UPDATE Pujas SET monto = ? WHERE id_puja = ?
            """, (nuevo_monto, id_puja))
            
            # 2️⃣ Actualizar el precio actual del producto
            cursor.execute("""
                UPDATE Productos 
                SET precio_actual = ?,
                    updated_at = GETDATE()
                WHERE id_producto = ?
            """, (nuevo_monto, id_producto))
            
            # 3️⃣ Registrar en historial de precios
            cursor.execute("""
                INSERT INTO HistorialPrecios (id_producto, precio_anterior, precio_nuevo, motivo)
                VALUES (?, ?, ?, ?)
            """, (id_producto, monto_anterior, nuevo_monto, f'Edición de puja #{id_puja} por administrador'))
            
            # 4️⃣ Notificar al usuario sobre el cambio
            cursor.execute("""
                INSERT INTO Notificaciones (id_usuario, tipo, titulo, mensaje, enlace)
                VALUES (?, ?, ?, ?, ?)
            """, (
                id_usuario,
                'puja_editada',
                'Tu puja fue modificada',
                f'El administrador ha modificado tu puja de ${monto_anterior:.2f} a ${nuevo_monto:.2f}',
                f'/producto/{id_producto}'
            ))
            
            # ✅ Confirmar transacción
            DatabaseConnection.commit_transaction(conn)
            
            return jsonify({
                'success': True,
                'message': 'Puja actualizada correctamente',
                'nuevo_monto': nuevo_monto
            })
            
        except Exception as e:
            # ❌ Reversar transacción
            DatabaseConnection.rollback_transaction(conn)
            logger.error(f"❌ Error en transacción: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
        finally:
            if cursor:
                cursor.close()
        
    except ValueError:
        return jsonify({'success': False, 'message': 'Monto inválido'}), 400
    except Exception as e:
        logger.error(f"❌ Error en editar_puja: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/puja/eliminar/<int:id_puja>', methods=['POST'])
@admin_required
def eliminar_puja(id_puja):
    """Eliminar una puja con transacción"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar que la puja existe y obtener información
        cursor.execute("""
            SELECT id_producto, monto, id_usuario 
            FROM Pujas WHERE id_puja = ?
        """, (id_puja,))
        
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Puja no encontrada'}), 404
        
        id_producto = row[0]
        monto_eliminado = row[1]
        id_usuario = row[2]
        
        # Obtener el precio actual del producto
        cursor.execute("SELECT precio_actual FROM Productos WHERE id_producto = ?", (id_producto,))
        precio_actual = cursor.fetchone()[0]
        
        # ============ INICIO DE TRANSACCIÓN ============
        try:
            conn = DatabaseConnection.begin_transaction()
            cursor = conn.cursor()
            
            # 1️⃣ Eliminar la puja
            cursor.execute("DELETE FROM Pujas WHERE id_puja = ?", (id_puja,))
            
            # 2️⃣ Actualizar precio del producto (buscar la nueva puja más alta)
            cursor.execute("""
                SELECT TOP 1 monto FROM Pujas 
                WHERE id_producto = ? 
                ORDER BY monto DESC
            """, (id_producto,))
            
            nueva_puja = cursor.fetchone()
            nuevo_precio = float(nueva_puja[0]) if nueva_puja else 0
            
            cursor.execute("""
                UPDATE Productos 
                SET precio_actual = ?, updated_at = GETDATE()
                WHERE id_producto = ?
            """, (nuevo_precio, id_producto))
            
            # 3️⃣ Registrar en historial de precios
            cursor.execute("""
                INSERT INTO HistorialPrecios (id_producto, precio_anterior, precio_nuevo, motivo)
                VALUES (?, ?, ?, ?)
            """, (id_producto, precio_actual, nuevo_precio, f'Eliminación de puja #{id_puja} por administrador'))
            
            # 4️⃣ Notificar al usuario
            cursor.execute("""
                INSERT INTO Notificaciones (id_usuario, tipo, titulo, mensaje, enlace)
                VALUES (?, ?, ?, ?, ?)
            """, (
                id_usuario,
                'puja_eliminada',
                'Tu puja fue eliminada',
                f'El administrador ha eliminado tu puja de ${float(monto_eliminado):.2f}',
                f'/producto/{id_producto}'
            ))
            
            # ✅ Confirmar transacción
            DatabaseConnection.commit_transaction(conn)
            
            return jsonify({
                'success': True,
                'message': 'Puja eliminada correctamente',
                'id_producto': id_producto
            })
            
        except Exception as e:
            # ❌ Reversar transacción
            DatabaseConnection.rollback_transaction(conn)
            logger.error(f"❌ Error en transacción: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
        finally:
            if cursor:
                cursor.close()
        
    except Exception as e:
        logger.error(f"❌ Error en eliminar_puja: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
    #222222222222222222222222222222 ============ RUTAS DE REGISTRO ============
@app.route('/registro', methods=['POST'])
def registro():
    """Registro de nuevos usuarios"""
    try:
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        telefono = request.form.get('telefono')
        direccion = request.form.get('direccion')
        
        # Validaciones
        if not all([nombre, email, password, confirm_password]):
            flash('Todos los campos marcados con * son requeridos', 'danger')
            return redirect(url_for('login'))
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'danger')
            return redirect(url_for('login'))
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'danger')
            return redirect(url_for('login'))
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar si el email ya existe
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE email = ?", (email,))
        if cursor.fetchone():
            cursor.close()
            flash('El email ya está registrado. Por favor, inicia sesión.', 'warning')
            return redirect(url_for('login'))
        
        # Hash de la contraseña
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Insertar nuevo usuario (por defecto es 'cliente')
        cursor.execute("""
            INSERT INTO Usuarios (nombre, email, password, rol, telefono, direccion, activo)
            VALUES (?, ?, ?, 'cliente', ?, ?, 1)
        """, (nombre, email, password_hash, telefono, direccion))
        
        conn.commit()
        cursor.close()
        
        flash('¡Registro exitoso! Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
        
    except Exception as e:
        logger.error(f"Error en registro: {e}")
        flash('Error al registrar usuario', 'danger')
        return redirect(url_for('login'))

# ============ RUTAS DE RECUPERACIÓN DE CONTRASEÑA ============
@app.route('/recuperar-password', methods=['POST'])
def recuperar_password():
    """Recuperación de contraseña"""
    try:
        email = request.form.get('email')
        
        if not email:
            flash('Ingresa tu email', 'danger')
            return redirect(url_for('login'))
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar si el usuario existe
        cursor.execute("SELECT id_usuario, nombre FROM Usuarios WHERE email = ? AND activo = 1", (email,))
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            flash('No se encontró una cuenta con ese email', 'warning')
            return redirect(url_for('login'))
        
        # Generar token de recuperación (simplificado)
        import uuid
        token = str(uuid.uuid4())
        
        # Guardar token en la base de datos (necesitarás agregar una tabla o campo)
        # Por ahora, creamos una tabla temporal si no existe
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='PasswordReset' AND xtype='U')
            CREATE TABLE PasswordReset (
                id INT IDENTITY(1,1) PRIMARY KEY,
                id_usuario INT NOT NULL,
                token VARCHAR(100) NOT NULL,
                fecha_creacion DATETIME DEFAULT GETDATE(),
                usado BIT DEFAULT 0,
                FOREIGN KEY (id_usuario) REFERENCES Usuarios(id_usuario)
            )
        """)
        
        cursor.execute("""
            INSERT INTO PasswordReset (id_usuario, token)
            VALUES (?, ?)
        """, (row[0], token))
        
        conn.commit()
        cursor.close()
        
        # Aquí deberías enviar un email con el enlace de recuperación
        # Por ahora, mostramos el token en un mensaje flash (solo para desarrollo)
        reset_url = f"{request.host_url}reset-password/{token}"
        flash(f'🔑 Enlace de recuperación (desarrollo): {reset_url}', 'info')
        flash('Se ha enviado un enlace de recuperación a tu email.', 'success')
        
        return redirect(url_for('login'))
        
    except Exception as e:
        logger.error(f"Error en recuperar_password: {e}")
        flash('Error al procesar la solicitud', 'danger')
        return redirect(url_for('login'))

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Restablecer contraseña con token"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar token
        cursor.execute("""
            SELECT pr.id_usuario, u.email, u.nombre
            FROM PasswordReset pr
            INNER JOIN Usuarios u ON pr.id_usuario = u.id_usuario
            WHERE pr.token = ? AND pr.usado = 0 
            AND DATEADD(HOUR, 24, pr.fecha_creacion) > GETDATE()
        """, (token,))
        
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            flash('El enlace de recuperación es inválido o ha expirado', 'danger')
            return redirect(url_for('login'))
        
        if request.method == 'POST':
            nueva_password = request.form.get('password')
            confirmar_password = request.form.get('confirm_password')
            
            if not all([nueva_password, confirmar_password]):
                flash('Ambos campos son requeridos', 'danger')
                return render_template('reset_password.html', token=token)
            
            if nueva_password != confirmar_password:
                flash('Las contraseñas no coinciden', 'danger')
                return render_template('reset_password.html', token=token)
            
            if len(nueva_password) < 6:
                flash('La contraseña debe tener al menos 6 caracteres', 'danger')
                return render_template('reset_password.html', token=token)
            
            # Actualizar contraseña
            password_hash = hashlib.sha256(nueva_password.encode()).hexdigest()
            
            cursor.execute("""
                UPDATE Usuarios SET password = ? WHERE id_usuario = ?
            """, (password_hash, row[0]))
            
            # Marcar token como usado
            cursor.execute("""
                UPDATE PasswordReset SET usado = 1 WHERE token = ?
            """, (token,))
            
            conn.commit()
            cursor.close()
            
            flash('¡Contraseña actualizada exitosamente! Ahora puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))
        
        cursor.close()
        return render_template('reset_password.html', token=token, user=session.get('user'))
        
    except Exception as e:
        logger.error(f"Error en reset_password: {e}")
        flash('Error al procesar la solicitud', 'danger')
        return redirect(url_for('login'))
#222222222222222222222222222222222222222
@app.route('/api/pujar', methods=['POST'])
@login_required
def realizar_puja():
    """Realizar una puja con transacción"""
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
        
        # Obtener conexión y cursor
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verificar producto
        cursor.execute('''
            SELECT precio_actual, fecha_fin, estado, nombre, id_usuario_creador
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
        nombre_producto = row[3]
        id_creador = row[4]
        
        # Validaciones
        if estado != 'activo':
            cursor.close()
            return jsonify({'success': False, 'error': 'Esta subasta no está activa'}), 400
        
        if fecha_fin and fecha_fin <= datetime.now():
            cursor.close()
            return jsonify({'success': False, 'error': 'La subasta ha finalizado'}), 400
        
        if monto <= precio_actual:
            cursor.close()
            mensaje = f'Ingrese un monto mayor al ofrecido (Monto actual: ${precio_actual:.2f})'
            return jsonify({'success': False, 'error': mensaje}), 400
        
        # ============ INICIO DE TRANSACCIÓN ============
        try:
            # Iniciar transacción
            conn = DatabaseConnection.begin_transaction()
            cursor = conn.cursor()
            
            # 1️⃣ Guardar la puja
            cursor.execute('''
                INSERT INTO Pujas (id_producto, id_usuario, monto, fecha_puja)
                VALUES (?, ?, ?, GETDATE())
            ''', (id_producto, session['user_id'], monto))
            
            # Obtener ID de la puja insertada
            cursor.execute("SELECT @@IDENTITY")
            id_puja = cursor.fetchone()[0]
            
            # 2️⃣ Actualizar precio del producto
            cursor.execute('''
                UPDATE Productos 
                SET precio_actual = ?, updated_at = GETDATE()
                WHERE id_producto = ?
            ''', (monto, id_producto))
            
            # 3️⃣ Guardar en historial de precios
            cursor.execute('''
                INSERT INTO HistorialPrecios (id_producto, precio_anterior, precio_nuevo, motivo)
                VALUES (?, ?, ?, ?)
            ''', (id_producto, precio_actual, monto, f'Puja del usuario {session.get("user")}'))
            
            # 4️⃣ Notificar al creador del producto
            if id_creador != session['user_id']:
                cursor.execute('''
                    INSERT INTO Notificaciones (id_usuario, tipo, titulo, mensaje, enlace)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    id_creador,
                    'puja_nueva',
                    'Nueva puja en tu producto',
                    f'El usuario {session.get("user")} ha realizado una puja de ${monto:.2f} en "{nombre_producto}"',
                    f'/producto/{id_producto}'
                ))
            
            # 5️⃣ Notificar al usuario anterior con la puja más alta
            cursor.execute('''
                SELECT TOP 1 id_usuario 
                FROM Pujas 
                WHERE id_producto = ? AND id_usuario != ? AND id_puja != ?
                ORDER BY monto DESC
            ''', (id_producto, session['user_id'], id_puja))
            
            anterior = cursor.fetchone()
            if anterior and anterior[0] != session['user_id'] and anterior[0] != id_creador:
                cursor.execute('''
                    INSERT INTO Notificaciones (id_usuario, tipo, titulo, mensaje, enlace)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    anterior[0],
                    'puja_superada',
                    'Te superaron en una puja',
                    f'Te superaron en la subasta "{nombre_producto}" con una puja de ${monto:.2f}',
                    f'/producto/{id_producto}'
                ))
            
            # ✅ Confirmar transacción (GUARDAR TODO)
            DatabaseConnection.commit_transaction(conn)
            
            logger.info(f"✅ Puja registrada: Usuario {session['user_id']}, Producto {id_producto}, Monto {monto}")
            
            return jsonify({
                'success': True,
                'message': '¡Puja realizada con éxito!',
                'nuevo_precio': monto
            })
            
        except Exception as e:
            # ❌ Reversar transacción (DESHACER TODO)
            DatabaseConnection.rollback_transaction(conn)
            logger.error(f"❌ Error en transacción: {e}")
            return jsonify({'success': False, 'error': 'Error al procesar la puja'}), 500
        finally:
            if cursor:
                cursor.close()
        
    except Exception as e:
        logger.error(f"❌ Error en realizar_puja: {e}")
        return jsonify({'success': False, 'error': 'Error al procesar la puja'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)