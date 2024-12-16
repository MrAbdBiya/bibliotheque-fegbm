#!/bin/bash

# Créer le dossier www s'il n'existe pas
mkdir -p www/static

# Copier les fichiers statiques
cp -r static/* www/static/
cp static/index.html www/

# Créer un fichier .gitkeep pour s'assurer que le dossier est inclus dans git
touch www/.gitkeep 