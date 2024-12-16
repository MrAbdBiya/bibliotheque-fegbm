// Configuration de l'API
const API_BASE_URL = 'https://youtube-mp3-converter-xxxx.onrender.com'; // Remplacez par votre URL Render

// Fonction pour vérifier la connexion au serveur
async function checkServerConnection() {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        if (!response.ok) {
            throw new Error('Serveur non disponible');
        }
        console.log('Connexion au serveur établie');
        return true;
    } catch (error) {
        console.error('Erreur de connexion au serveur:', error);
        return false;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const urlInput = document.getElementById('youtubeUrl');
    const convertBtn = document.getElementById('convertBtn');
    const status = document.getElementById('status');
    const loader = document.getElementById('loader');
    const progressContainer = document.getElementById('progressContainer');
    const progress = document.getElementById('progress');
    const progressText = document.getElementById('progressText');
    const progressStatus = document.getElementById('progressStatus');
    const progressDetails = document.getElementById('progressDetails');

    // Vérifier la connexion au démarrage
    const isConnected = await checkServerConnection();
    if (!isConnected) {
        showError('Le service est temporairement indisponible. Veuillez réessayer plus tard.');
        return;
    }

    let eventSource = null;
    let lastProgressUpdate = null;
    let isDownloading = false;

    function formatSize(bytes) {
        const sizes = ['B', 'KB', 'MB', 'GB'];
        if (bytes === 0) return '0 B';
        const i = parseInt(Math.floor(Math.log(bytes) / Math.log(1024)));
        return Math.round(bytes / Math.pow(1024, i), 2) + ' ' + sizes[i];
    }

    function formatSpeed(speedBytesPerSec) {
        if (!speedBytesPerSec) return '0 MB/s';
        const mbps = speedBytesPerSec / 1024 / 1024;
        return `${mbps.toFixed(1)} MB/s`;
    }

    function formatTime(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}s`;
        return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    }

    function updateProgressUI(percentage, message, data = {}) {
        if (!isDownloading && percentage > 0) {
            isDownloading = true;
            progressContainer.style.display = 'block';
        }

        progress.style.width = `${percentage}%`;
        progressText.textContent = `${Math.round(percentage)}%`;

        if (message) {
            progressStatus.textContent = message;
        }

        if (data.speed > 0) {
            const speedFormatted = formatSpeed(data.speed);
            const downloaded = formatSize(data.downloaded || 0);
            const total = formatSize(data.total || 0);
            const remainingBytes = data.total - data.downloaded;
            const remainingTime = remainingBytes / data.speed;

            progressDetails.textContent =
                `${downloaded} / ${total} - ` +
                `Vitesse : ${speedFormatted} - ` +
                `Temps restant : ${formatTime(remainingTime)}`;
        }

        lastProgressUpdate = Date.now();
    }

    function showError(message) {
        status.textContent = message;
        status.className = 'status error';
    }

    function showSuccess(message) {
        status.textContent = message;
        status.className = 'status success';
    }

    function resetProgress() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        progress.style.width = '0%';
        progressText.textContent = '0%';
        progressContainer.style.display = 'none';
        progressStatus.textContent = '';
        progressDetails.textContent = '';
        status.textContent = '';
        status.className = 'status';
        lastProgressUpdate = null;
        isDownloading = false;
    }

    function validateYouTubeUrl(url) {
        const regex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$/;
        return regex.test(url);
    }

    function setupEventSource(requestId) {
        return new Promise((resolve, reject) => {
            eventSource = new EventSource(`/progress/${requestId}`);
            let downloadStarted = false;

            function checkProgress() {
                if (lastProgressUpdate && Date.now() - lastProgressUpdate > 30000) {
                    console.warn('Pas de mise à jour depuis 30 secondes');
                    eventSource.close();
                    reject(new Error('Le téléchargement semble bloqué. Veuillez réessayer.'));
                }
            }

            const progressChecker = setInterval(checkProgress, 5000);

            eventSource.onmessage = (event) => {
                console.log('Event received:', event.data);
                const data = JSON.parse(event.data);

                if (data.status === 'connected') {
                    console.log('Connexion établie');
                    updateProgressUI(0, 'Connexion établie...');
                    return;
                }

                if (data.status === 'heartbeat') {
                    console.log('Heartbeat reçu');
                    return;
                }

                if (data.status === 'starting') {
                    updateProgressUI(0, data.message || 'Démarrage du téléchargement...');
                } else if (data.status === 'downloading') {
                    downloadStarted = true;
                    updateProgressUI(
                        data.progress,
                        'Téléchargement en cours...',
                        data
                    );
                } else if (data.status === 'processing') {
                    updateProgressUI(95, 'Conversion en MP3...');
                } else if (data.status === 'finished') {
                    clearInterval(progressChecker);
                    updateProgressUI(100, data.message || 'Finalisation...');
                    resolve();
                } else if (data.status === 'error') {
                    clearInterval(progressChecker);
                    reject(new Error(data.message || 'Erreur pendant le téléchargement'));
                }
            };

            eventSource.onerror = (error) => {
                console.error('SSE Error:', error);
                clearInterval(progressChecker);
                if (!downloadStarted) {
                    reject(new Error('Erreur de connexion au serveur. Veuillez réessayer.'));
                }
            };

            setTimeout(() => {
                if (!downloadStarted && !lastProgressUpdate) {
                    clearInterval(progressChecker);
                    reject(new Error('Le téléchargement n\'a pas démarré. Veuillez vérifier l\'URL et réessayer.'));
                }
            }, 10000);
        });
    }

    async function startDownload(url, requestId) {
        try {
            const response = await fetch('/download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url, requestId }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Erreur lors de la conversion');
            }

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = 'audio.mp3';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Erreur lors du téléchargement:', error);
            throw error;
        }
    }

    convertBtn.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        
        if (!url) {
            showError('Veuillez entrer une URL YouTube');
            return;
        }

        if (!validateYouTubeUrl(url)) {
            showError('Veuillez entrer une URL YouTube valide');
            return;
        }

        // Vérifier la connexion avant de commencer
        const isConnected = await checkServerConnection();
        if (!isConnected) {
            showError('Le service est temporairement indisponible. Veuillez réessayer plus tard.');
            return;
        }

        try {
            resetProgress();
            progressStatus.textContent = 'Initialisation...';
            loader.style.display = 'none';
            convertBtn.disabled = true;
            progressContainer.style.display = 'block';
            
            const requestId = Date.now().toString();
            
            // Établir la connexion SSE d'abord
            const progressPromise = setupEventSource(requestId);
            
            // Attendre que la connexion SSE soit établie
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Démarrer le téléchargement
            const response = await fetch(`${API_BASE_URL}/download`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url, requestId }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Erreur lors de la conversion');
            }

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = 'audio.mp3';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            document.body.removeChild(a);

            showSuccess('Conversion réussie ! Votre fichier MP3 va être téléchargé.');
            urlInput.value = '';
        } catch (error) {
            showError(error.message);
            console.error('Erreur détaillée:', error);
        } finally {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            convertBtn.disabled = false;
            loader.style.display = 'none';
            setTimeout(resetProgress, 3000);
        }
    });

    // Permettre l'utilisation de la touche Entrée
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !convertBtn.disabled) {
            convertBtn.click();
        }
    });
});
