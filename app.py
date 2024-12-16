from flask import Flask, request, jsonify, send_file, Response, send_from_directory, render_template
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import logging
import json
import queue
import threading
import time
from datetime import datetime
import io

# Définir le chemin absolu du dossier www
WWW_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www')

app = Flask(__name__, 
            static_url_path='',
            static_folder=WWW_FOLDER)

CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Configuration du logging plus détaillée
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Dictionnaire pour stocker les files de progression et les timestamps
progress_queues = {}
download_timestamps = {}
thread_to_request_id = {}

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

def send_progress_update(request_id, progress_data):
    """Fonction utilitaire pour envoyer les mises à jour de progression"""
    if request_id in progress_queues:
        try:
            progress_queues[request_id].put(progress_data)
            download_timestamps[request_id] = datetime.now()
            logger.info(f"Mise à jour envoyée pour {request_id}: {progress_data}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la progression: {e}")
    return False

def progress_hook(d):
    thread_id = threading.get_ident()
    request_id = thread_to_request_id.get(thread_id)

    if not request_id:
        logger.error("Impossible de trouver le request_id pour le thread actuel")
        return

    try:
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)

            if total > 0:
                progress = (downloaded / total) * 100
                logger.info(f"Progression {progress:.1f}% - Speed: {speed/1024/1024:.1f} MB/s")

                send_progress_update(request_id, {
                    'progress': progress,
                    'status': 'downloading',
                    'speed': speed,
                    'downloaded': downloaded,
                    'total': total
                })
        elif d['status'] == 'finished':
            logger.info("Téléchargement terminé, début de la conversion...")
            send_progress_update(request_id, {
                'progress': 95,
                'status': 'processing'
            })
    except Exception as e:
        logger.error(f"Erreur dans progress_hook: {str(e)}")
        send_progress_update(request_id, {
            'status': 'error',
            'message': str(e)
        })

@app.route('/')
def home():
    logger.info("Accès à la page d'accueil")
    try:
        logger.info(f"Dossier statique : {app.static_folder}")
        logger.info(f"Contenu du dossier www : {os.listdir(WWW_FOLDER)}")
        return app.send_static_file('index.html')
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de index.html: {e}")
        return str(e), 500

@app.route('/static/<path:filename>')
def serve_static(filename):
    logger.info(f"Demande de fichier statique : {filename}")
    try:
        return send_from_directory(os.path.join(WWW_FOLDER, 'static'), filename)
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier statique {filename}: {e}")
        return str(e), 404

@app.route('/progress/<request_id>')
def get_progress(request_id):
    def generate():
        q = queue.Queue()
        progress_queues[request_id] = q
        download_timestamps[request_id] = datetime.now()
        logger.info(f"Nouvelle connexion SSE établie pour {request_id}")

        try:
            # Envoyer un événement initial
            yield f"data: {json.dumps({'status': 'connected', 'progress': 0})}\n\n"

            while True:
                try:
                    # Vérifier si le téléchargement est actif
                    last_update = download_timestamps.get(request_id)
                    if last_update and (datetime.now() - last_update).seconds > 30:
                        logger.warning(f"Pas de mise à jour depuis 30 secondes pour {request_id}")
                        yield f"data: {json.dumps({'status': 'error', 'message': 'Timeout'})}\n\n"
                        break

                    progress_data = q.get(timeout=2)
                    logger.info(f"Envoi de la progression pour {request_id}: {progress_data}")
                    yield f"data: {json.dumps(progress_data)}\n\n"

                    if progress_data.get('status') in ['finished', 'error']:
                        break

                except queue.Empty:
                    yield f"data: {json.dumps({'status': 'heartbeat'})}\n\n"
                    continue

        finally:
            if request_id in progress_queues:
                del progress_queues[request_id]
            if request_id in download_timestamps:
                del download_timestamps[request_id]
            logger.info(f"Nettoyage effectué pour {request_id}")

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route('/download', methods=['POST'])
def download_video():
    output_path = None
    thread_id = threading.get_ident()
    
    try:
        data = request.get_json()
        if not data:
            logger.error("Pas de données JSON reçues")
            return jsonify({'error': 'Données JSON requises'}), 400

        url = data.get('url')
        request_id = data.get('requestId')

        logger.info(f"Nouvelle demande de téléchargement - URL: {url}, RequestID: {request_id}")

        if not url:
            logger.error("URL manquante dans la requête")
            return jsonify({'error': 'URL requise'}), 400
        if not request_id:
            logger.error("RequestID manquant dans la requête")
            return jsonify({'error': 'RequestID requis'}), 400

        # Associer le thread actuel au request_id
        thread_to_request_id[thread_id] = request_id

        try:
            # Envoyer un événement de début
            send_progress_update(request_id, {
                'progress': 0,
                'status': 'starting',
                'message': 'Démarrage du téléchargement...'
            })

            temp_dir = tempfile.gettempdir()
            output_template = os.path.join(temp_dir, f'yt_{request_id}_%(title)s.%(ext)s')

            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_template,
                'quiet': False,
                'no_warnings': True,
                'progress_hooks': [progress_hook],
                'cookiesfrombrowser': ('chrome',),
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            }

            logger.info(f"Début du téléchargement avec yt-dlp pour {request_id}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info['title']
                output_path = os.path.join(temp_dir, f'yt_{request_id}_{title}.mp3')

                logger.info(f"Téléchargement terminé pour {request_id}: {output_path}")

                # Informer que le traitement est terminé
                send_progress_update(request_id, {
                    'progress': 100,
                    'status': 'finished',
                    'message': 'Téléchargement terminé !'
                })

                # Lire le fichier en mémoire avant de l'envoyer
                with open(output_path, 'rb') as file:
                    file_data = file.read()

                # Créer la réponse avec les données du fichier
                response = send_file(
                    io.BytesIO(file_data),
                    as_attachment=True,
                    download_name=f"{title}.mp3",
                    mimetype="audio/mpeg"
                )

                response.headers['Connection'] = 'close'
                return response

        except Exception as e:
            error_message = str(e)
            logger.error(f"Erreur lors du téléchargement pour {request_id}: {error_message}")
            send_progress_update(request_id, {
                'status': 'error',
                'message': error_message
            })
            return jsonify({'error': f"Erreur lors du téléchargement: {error_message}"}), 500

    except Exception as e:
        logger.error(f"Erreur générale: {str(e)}")
        return jsonify({'error': str(e)}), 500

    finally:
        # Nettoyer l'association thread-requestId
        if thread_id in thread_to_request_id:
            del thread_to_request_id[thread_id]

        # Essayer de supprimer le fichier temporaire après un court délai
        def delete_temp_file(file_path):
            try:
                time.sleep(2)  # Attendre 2 secondes
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Fichier temporaire supprimé: {file_path}")
            except Exception as e:
                logger.warning(f"Impossible de supprimer le fichier temporaire {file_path}: {e}")

        if output_path:
            threading.Thread(target=delete_temp_file, args=(output_path,)).start()

@app.route('/health')
def health_check():
    """Endpoint pour vérifier si le serveur est en ligne"""
    return jsonify({"status": "ok", "message": "Service is running"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
