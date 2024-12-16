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

# Définir les chemins absolus
WWW_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www')
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp')

# S'assurer que les dossiers existent
os.makedirs(WWW_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

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

            # Utiliser le dossier temporaire personnalisé
            output_template = os.path.join(TEMP_FOLDER, f'yt_{request_id}_%(title)s.%(ext)s')

            ydl_opts = {
                'format': 'bestaudio',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_template,
                'quiet': False,
                'no_warnings': False,
                'progress_hooks': [progress_hook],
                'verbose': True,
                'no_color': True,
                'geo_bypass': True,
                'nocheckcertificate': True,
                'ignoreerrors': False,
                'extract_flat': False,
                'youtube_include_dash_manifest': False,
                'cookiesfrombrowser': ('chrome',),
                'extractor_args': {
                    'youtube': {
                        'player_skip': ['js', 'webpage', 'configs'],
                        'skip': ['hls', 'dash', 'translated_subs'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate',
                    'Origin': 'https://www.youtube.com',
                    'Referer': 'https://www.youtube.com/',
                },
                'socket_timeout': 30,
                'retries': 3,
            }

            # Créer un fichier de cookies temporaire
            cookies_path = os.path.join(TEMP_FOLDER, f'cookies_{request_id}.txt')
            try:
                # Essayer d'exporter les cookies de Chrome
                import browser_cookie3
                cj = browser_cookie3.chrome(domain_name='.youtube.com')
                with open(cookies_path, 'w') as f:
                    for cookie in cj:
                        f.write(f'{cookie.domain}\tTRUE\t{cookie.path}\t'
                               f'{"TRUE" if cookie.secure else "FALSE"}\t{cookie.expires}\t'
                               f'{cookie.name}\t{cookie.value}\n')
                ydl_opts['cookiefile'] = cookies_path
            except Exception as e:
                logger.warning(f"Impossible d'exporter les cookies : {e}")

            logger.info(f"Début du téléchargement avec yt-dlp pour {request_id}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        # Tenter d'extraire les informations
                        logger.info("Tentative d'extraction des informations...")
                        info_dict = ydl.extract_info(url, download=False)
                        
                        if not info_dict:
                            raise Exception("Aucune information extraite")
                            
                        video_id = info_dict.get('id', 'unknown')
                        title = info_dict.get('title', 'video')
                        duration = info_dict.get('duration', 0)
                        
                        logger.info(f"ID de la vidéo : {video_id}")
                        logger.info(f"Titre : {title}")
                        logger.info(f"Durée : {duration} secondes")
                        
                        # Vérifier si la vidéo est trop longue (plus de 30 minutes)
                        if duration > 1800:
                            raise Exception("La vidéo est trop longue (maximum 30 minutes)")
                            
                        # Vérifier si la vidéo est disponible
                        if info_dict.get('is_live'):
                            raise Exception("Les lives ne sont pas supportés")
                            
                        # Télécharger la vidéo
                        logger.info("Début du téléchargement...")
                        ydl.download([url])
                        
                        output_path = os.path.join(TEMP_FOLDER, f'yt_{request_id}_{title}.mp3')
                        logger.info(f"Chemin de sortie attendu : {output_path}")
                        
                        if not os.path.exists(output_path):
                            possible_files = os.listdir(TEMP_FOLDER)
                            logger.info(f"Fichiers dans le dossier temp : {possible_files}")
                            matching_files = [f for f in possible_files if f.startswith(f'yt_{request_id}_') and f.endswith('.mp3')]
                            if matching_files:
                                output_path = os.path.join(TEMP_FOLDER, matching_files[0])
                                logger.info(f"Fichier trouvé : {output_path}")
                            else:
                                raise Exception("Le fichier MP3 n'a pas été créé")
                                
                    except yt_dlp.utils.DownloadError as e:
                        logger.error(f"Erreur yt-dlp : {str(e)}")
                        raise Exception(f"Erreur lors du téléchargement : {str(e)}")
                    except Exception as e:
                        logger.error(f"Erreur inattendue : {str(e)}")
                        raise

                    finally:
                        # Supprimer le fichier de cookies
                        if os.path.exists(cookies_path):
                            try:
                                os.remove(cookies_path)
                                logger.info("Fichier de cookies supprimé")
                            except Exception as e:
                                logger.warning(f"Impossible de supprimer le fichier de cookies : {e}")

                    # Informer que le traitement est terminé
                    send_progress_update(request_id, {
                        'progress': 100,
                        'status': 'finished',
                        'message': 'Téléchargement terminé !'
                    })

                    # Lire le fichier en mémoire avant de l'envoyer
                    try:
                        with open(output_path, 'rb') as file:
                            file_data = file.read()
                    except Exception as e:
                        logger.error(f"Erreur lors de la lecture du fichier : {str(e)}")
                        raise Exception(f"Erreur lors de la lecture du fichier : {str(e)}")

                    # Créer la réponse avec les données du fichier
                    try:
                        response = send_file(
                            io.BytesIO(file_data),
                            as_attachment=True,
                            download_name=f"{title}.mp3",
                            mimetype="audio/mpeg"
                        )
                        response.headers['Connection'] = 'close'
                        return response
                    except Exception as e:
                        logger.error(f"Erreur lors de l'envoi du fichier : {str(e)}")
                        raise Exception(f"Erreur lors de l'envoi du fichier : {str(e)}")

            except Exception as e:
                error_message = str(e)
                logger.error(f"Erreur lors du téléchargement pour {request_id}: {error_message}")
                send_progress_update(request_id, {
                    'status': 'error',
                    'message': error_message
                })
                return jsonify({'error': error_message}), 500

        except Exception as e:
            error_message = str(e)
            logger.error(f"Erreur lors du téléchargement pour {request_id}: {error_message}")
            send_progress_update(request_id, {
                'status': 'error',
                'message': error_message
            })
            return jsonify({'error': error_message}), 500

    except Exception as e:
        error_message = str(e)
        logger.error(f"Erreur générale: {error_message}")
        return jsonify({'error': error_message}), 500

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
