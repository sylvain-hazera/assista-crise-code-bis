# Outillage satellite — phase de cadrage

Premiers briques logicielles pour les "satellites" (Raspberry Pi déployés sur site) décrits
dans le cadrage "Chantier B" du plan de développement — voir `decouverte_lan.py` pour la
première pièce implémentée : la découverte des nœuds MeshCore/Meshtastic sur le réseau local
d'un satellite, utile au wizard d'installation (pas encore écrit).

**Ce répertoire n'est pas encore intégré au docker-compose du projet** — il n'existe pas
encore de conteneur/service satellite à construire, seulement l'outillage qui le préparera.

## `decouverte_lan.py`

Combine deux méthodes pour repérer les nœuds MeshCore/Meshtastic sur le LAN d'un satellite à
l'installation :
- **mDNS** (zeroconf) — un nœud peut s'annoncer sur le réseau. Les noms de service utilisés
  (`SERVICE_TYPES_MDNS` dans le fichier) sont des hypothèses **non confirmées sur du vrai
  matériel** — à ajuster une fois testés en conditions réelles.
- **Scan TCP du port 5000** (port MeshCore par défaut) sur le sous-réseau local — protocole-
  agnostique, plus lent mais indépendant de toute annonce.

Ne fait pas encore le handshake protocolaire de confirmation (MeshCore vs Meshtastic vs rien) —
juste une liste de candidats. La confirmation réutilisera la même logique que
`MeshLocalDetecterView` côté Django (`backend/core/views.py` :
`_detecter_meshcore_local`/`_detecter_meshtastic_local`).

Usage en ligne de commande (depuis une machine sur le LAN à sonder) :
```bash
python3 decouverte_lan.py
```

## Installer les dépendances et lancer les tests

```bash
pip install -r requirements-dev.txt
pytest
```

Les tests ne nécessitent aucun matériel MeshCore/Meshtastic réel : le scan de port est vérifié
contre un serveur TCP local factice, et la découverte mDNS est vérifiée sur son repli (zeroconf
absent) plutôt que contre un vrai service annoncé (pas reproductible en CI).
