import pyodbc
import os
from dotenv import load_dotenv
import getpass

load_dotenv()

server = os.getenv('DB_SERVER', 'localhost')
database = os.getenv('DB_NAME', 'SubastasDB')

print("=" * 50)
print("🔍 PROBANDO CONEXIÓN A SQL SERVER")
print("=" * 50)
print(f"   Servidor: {server}")
print(f"   Base de datos: {database}")
print(f"   Autenticación: Windows (tu usuario: {getpass.getuser()})")
print("-" * 50)

try:
    # Conexión con Autenticación de Windows
    connection_string = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={server};'
        f'DATABASE={database};'
        f'Trusted_Connection=yes;'
        f'TrustServerCertificate=yes;'
    )
    
    print("🔄 Conectando...")
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()
    
    # Consulta de prueba
    cursor.execute("SELECT @@VERSION")
    version = cursor.fetchone()[0]
    print("✅ ¡Conexión exitosa!")
    print(f"   Versión SQL Server: {version[:60]}...")
    
    # Verificar tablas
    cursor.execute("SELECT COUNT(*) FROM Usuarios")
    total_usuarios = cursor.fetchone()[0]
    print(f"   Usuarios en la base de datos: {total_usuarios}")
    
    # Mostrar algunos usuarios
    if total_usuarios > 0:
        cursor.execute("SELECT TOP 3 nombre, email, rol FROM Usuarios")
        print("\n👥 Usuarios registrados:")
        for row in cursor.fetchall():
            print(f"   - {row.nombre} ({row.email}) - {row.rol}")
    else:
        print("\n⚠️ No hay usuarios registrados")
    
    cursor.close()
    conn.close()
    print("\n✅ ¡Prueba completada con éxito!")
    
except Exception as e:
    print(f"\n❌ ERROR de conexión: {e}")
    print("\n📝 POSIBLES SOLUCIONES:")
    print("1. Verifica que SQL Server esté corriendo")
    print("2. Asegúrate que el driver ODBC esté instalado")
    print("3. Verifica que la base de datos 'SubastasDB' existe")
    print("4. En SSMS, ejecuta: USE SubastasDB; CREATE USER [TU_USUARIO] FOR LOGIN [TU_USUARIO]; ALTER ROLE db_owner ADD MEMBER [TU_USUARIO];")