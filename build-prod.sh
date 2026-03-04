#!/bin/bash

set -e

REGISTRY="im2ag-harbor.univ-grenoble-alpes.fr"
PROJECT="assista-crise"
TAG="latest"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'


echo -e "\n${BLUE}[0/4] Nettoyage de l'environnement local...${NC}"
docker compose -f docker-compose.prod.yml down --remove-orphans || true

# 1. FRONTEND (Angular Prod)
echo -e "\n${BLUE}[1/4] Build FRONTEND (Mode Production)...${NC}"
# On utilise le même tag que la prod pour que docker-compose le trouve tout seul
docker build --platform linux/amd64 -f frontend/Dockerfile.prod -t $REGISTRY/$PROJECT/frontend:$TAG ./frontend

# 2. BACKEND (Django)
echo -e "\n${BLUE}[2/4] Build BACKEND...${NC}"
docker build --platform linux/amd64 -t $REGISTRY/$PROJECT/backend:$TAG ./backend

# 3. PROXY (Nginx)
echo -e "\n${BLUE}[3/4] Build PROXY...${NC}"
docker build --platform linux/amd64 -t $REGISTRY/$PROJECT/proxy:$TAG ./proxy

echo -e "\n${GREEN} BUILD TERMINÉ ! Les images sont prêtes localement.${NC}"

# 4. Lancement pour vérification
echo -e "\n${BLUE}[4/4] Lancement des conteneurs PROD en local...${NC}"

docker compose -f docker-compose.prod.yml up -d
