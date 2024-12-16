from flask import Flask, send_from_directory, render_template
from flask_cors import CORS
import os
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Définir les chemins absolus
WWW_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www')
STORAGE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'storage')

# S'assurer que les dossiers existent
os.makedirs(WWW_FOLDER, exist_ok=True)
os.makedirs(STORAGE_FOLDER, exist_ok=True)

app = Flask(__name__, 
            static_url_path='',
            static_folder=WWW_FOLDER)

CORS(app)

@app.route('/')
def home():
    logger.info("Accès à la page d'accueil")
    return app.send_static_file('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    logger.info(f"Demande de fichier statique : {filename}")
    return send_from_directory(os.path.join(WWW_FOLDER, 'static'), filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'www'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/health')
def health_check():
    """Endpoint pour vérifier si le serveur est en ligne"""
    return {"status": "ok", "message": "Service is running"}, 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
