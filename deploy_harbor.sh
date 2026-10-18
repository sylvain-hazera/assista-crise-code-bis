#!/bin/bash

set -e

REGISTRY="im2ag-harbor.univ-grenoble-alpes.fr"
PROJECT="assista-crise"
TAG="latest"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# 1. Connexion à Harbor
echo -e "${BLUE}=== DÉBUT DU DÉPLOIEMENT VERS HARBOR ===${NC}"

echo -e "\n${BLUE}[1/5] Connexion à Harbor...${NC}"
docker login $REGISTRY

# 2. FRONTEND (Angular)
echo -e "\n${BLUE}[2/5] Traitement du FRONTEND (Mode Production)...${NC}"

docker build --platform linux/amd64 -f frontend/Dockerfile.prod -t $REGISTRY/$PROJECT/frontend:$TAG ./frontend
echo -e "${GREEN}Frontend buildé. Envoi en cours...${NC}"
docker push $REGISTRY/$PROJECT/frontend:$TAG

# 3. BACKEND (Django)
echo -e "\n${BLUE}[3/5] Traitement du BACKEND...${NC}"

docker build --platform linux/amd64 -t $REGISTRY/$PROJECT/backend:$TAG ./backend
echo -e "${GREEN}Backend buildé. Envoi en cours...${NC}"
docker push $REGISTRY/$PROJECT/backend:$TAG

# 4. PROXY (Nginx Gateway)
echo -e "\n${BLUE}[4/5] Traitement du PROXY...${NC}"
docker build --platform linux/amd64 -t $REGISTRY/$PROJECT/proxy:$TAG ./proxy
echo -e "${GREEN}Proxy buildé. Envoi en cours...${NC}"
docker push $REGISTRY/$PROJECT/proxy:$TAG

# 5. MONITORING (Prometheus, Alertmanager, Grafana : image officielle + configuration intégrée)
# Le build échoue si une règle d'alerte est invalide ou si un test d'alerte échoue.
echo -e "\n${BLUE}[5/5] Traitement du MONITORING...${NC}"
for svc in prometheus alertmanager grafana; do
    docker build --platform linux/amd64 -t $REGISTRY/$PROJECT/$svc:$TAG ./monitoring/$svc
    docker push $REGISTRY/$PROJECT/$svc:$TAG
done
echo -e "${GREEN}Images de monitoring envoyées.${NC}"

echo -e "\n${GREEN}✅ SUCCÈS ! Toutes les images sont sur Harbor.${NC}"
echo -e "Tu n'as plus qu'à aller sur ton serveur et faire :"
echo -e "1. docker login $REGISTRY"
echo -e "2. docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring pull"
echo -e "3. docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring up -d"