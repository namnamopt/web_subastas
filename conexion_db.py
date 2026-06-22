import pyodbc
from flask import g
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseConnection:
    @staticmethod
    def get_connection():
        if 'db' not in g:
            try:
                # Conexión con Autenticación de Windows
                connection_string = (
                    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                    f'SERVER={Config.DB_SERVER};'
                    f'DATABASE={Config.DB_NAME};'
                    f'Trusted_Connection=yes;'
                    f'TrustServerCertificate=yes;'
                )
                g.db = pyodbc.connect(connection_string)
                logger.info("✅ Conexión a BD establecida con Autenticación de Windows")
            except Exception as e:
                logger.error(f"❌ Error de conexión: {e}")
                raise e
        return g.db
    
    @staticmethod
    def close_connection(exception=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()
            logger.info("Conexión a BD cerrada")