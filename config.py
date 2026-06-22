import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'mi-clave-secreta-12345')
    
    # Configuración SQL Server
    DB_SERVER = os.getenv('DB_SERVER', 'localhost')
    DB_NAME = os.getenv('DB_NAME', 'SubastasDB')
    
    # Configuración de archivos
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}