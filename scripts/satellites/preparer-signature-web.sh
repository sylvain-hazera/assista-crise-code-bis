#!/usr/bin/env bash
# Prepare la cle de signature pour signer depuis la page Satellites, avec la seule phrase de
# passe. A FAIRE UNE FOIS (et a refaire si vous changez de phrase de passe ou de cle).
#
#   scripts/satellites/preparer-signature-web.sh
#
# Ce que fait ce script :
#   1. il vous demande la phrase de passe de la cle (elle n'est ni affichee, ni ecrite) ;
#   2. il "emballe" la cle : il la chiffre avec cette meme phrase, dans un format que les
#      navigateurs savent ouvrir sans bibliotheque (PBKDF2 + AES-GCM) ;
#   3. il verifie que l'emballage s'ouvre et signe correctement ;
#   4. il le depose dans le dossier des secrets du central.
#
# Ensuite, dans la page Satellites : "Signer la derniere version", la phrase de passe, et
# c'est tout. La signature se fait DANS VOTRE NAVIGATEUR : la phrase n'est jamais envoyee au
# serveur, et le serveur ne voit jamais la cle en clair.
#
# CE QUE CELA CHANGE. Une copie CHIFFREE de la cle se trouve desormais sur le central, et la
# page qui signe est servie par lui. Sans la phrase de passe, cette copie ne sert a rien ; mais
# quelqu'un qui prendrait la main sur le central pourrait modifier la page pour capter la
# phrase a votre prochaine signature. Si ce risque ne vous convient plus : videz le fichier
# depose (voir la fin), et signez comme avant avec scripts/satellites/signer-version.sh.
#
# Le fichier d'origine de la cle n'est pas modifie. La copie dechiffree n'existe que quelques
# secondes, en memoire vive (/dev/shm), et elle est ecrasee avant d'etre supprimee.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLE="${ASSISTA_CLE_DOSSIER:-$HOME/.config/assista-crise}/signature-satellites"
SORTIE="${SECRETS_DIR:-$HOME/.config/assista-crise/secrets}/signature_satellites_web.json"
AUTORISEES="${ASSISTA_CLES_AUTORISEES:-$RACINE/backend/core/signature_satellites.pub}"
IMAGE="${ASSISTA_IMAGE_BACKEND:-assista-crise-backend:prod}"

[ -f "$CLE" ] || { echo "Cle introuvable ($CLE). Creez-la : scripts/satellites/creer-cle-signature.sh" >&2; exit 1; }
[ -f "$CLE.pub" ] || { echo "Cle publique introuvable ($CLE.pub)." >&2; exit 1; }
grep -qF "$(cut -d' ' -f2 "$CLE.pub")" "$AUTORISEES" 2>/dev/null || {
    echo "Cette cle n'est pas dans $AUTORISEES :" >&2
    echo "le central refuserait ses signatures. Rien n'a ete fait." >&2; exit 1; }
[ -d "$(dirname "$SORTIE")" ] || { echo "Dossier des secrets introuvable : $(dirname "$SORTIE")" >&2; exit 1; }
[ -d /dev/shm ] || { echo "/dev/shm absent : pas de memoire vive ou travailler." >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "Image $IMAGE introuvable : deployez d'abord le central." >&2; exit 1; }

TRAVAIL="$(mktemp -d /dev/shm/signature-web.XXXXXX)"
chmod 700 "$TRAVAIL"
nettoyer() {
    find "$TRAVAIL" -type f -exec shred -u {} + 2>/dev/null || true
    rm -rf "$TRAVAIL"
}
trap nettoyer EXIT

if [ -t 0 ]; then
    read -rs -p "Phrase de passe de la cle de signature : " PHRASE_SIGNATURE; echo
else
    read -rs PHRASE_SIGNATURE
fi
[ -n "$PHRASE_SIGNATURE" ] || { echo "Phrase de passe vide : rien n'a ete fait." >&2; exit 1; }
export PHRASE_SIGNATURE

# Copie de travail, dechiffree en memoire vive. La phrase est remise a ssh-keygen par un petit
# programme "askpass" et non en argument : un argument se lit dans la liste des processus.
cp "$CLE" "$TRAVAIL/cle"
chmod 600 "$TRAVAIL/cle"
printf '#!/bin/sh\nprintf "%%s\\n" "$PHRASE_SIGNATURE"\n' > "$TRAVAIL/askpass"
chmod 700 "$TRAVAIL/askpass"
if ! SSH_ASKPASS="$TRAVAIL/askpass" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}" \
        ssh-keygen -p -q -N '' -f "$TRAVAIL/cle" </dev/null >/dev/null 2>&1; then
    echo "Phrase de passe incorrecte : rien n'a ete fait." >&2
    exit 1
fi
chmod 644 "$TRAVAIL/cle"      # lu par le conteneur ci-dessous, dans un dossier ferme (700)

# Emballage et controle, dans un conteneur jetable SANS reseau. Le code est celui du depot.
docker run --rm -i --network none --user "$(id -u):$(id -g)" --entrypoint python \
    -e PHRASE_SIGNATURE -v "$RACINE/backend:/app:ro" -v "$TRAVAIL:/travail" -w /app "$IMAGE" - <<'PY'
import json, os
from cryptography.hazmat.primitives import serialization
from core import signature_satellites as s

phrase = os.environ["PHRASE_SIGNATURE"]
cle = serialization.load_ssh_private_key(open("/travail/cle", "rb").read(), password=None)
emballage = s.emballer_cle(cle, phrase)

# Controle : l'emballage se rouvre avec la phrase, signe, et la signature se verifie.
publique = cle.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
commit = "0" * 40
s.verifier(commit, s.signer(s.deballer_cle(emballage, phrase), commit), cles=[publique])
try:
    s.deballer_cle(emballage, phrase + "x")
    raise SystemExit("Controle en echec : une mauvaise phrase ouvre l'emballage.")
except s.SignatureInvalide:
    pass
json.dump(emballage, open("/travail/emballage.json", "w"))
PY

[ -s "$TRAVAIL/emballage.json" ] || { echo "L'emballage n'a pas ete produit : rien n'a ete depose." >&2; exit 1; }

# Ecriture SUR PLACE (meme fichier) : s'il est deja monte dans le conteneur du central, celui-ci
# voit le nouveau contenu sans redemarrage.
cat "$TRAVAIL/emballage.json" > "$SORTIE"
chmod 644 "$SORTIE"

echo
echo "Cle preparee et verifiee : $SORTIE"
echo "Dans la page Satellites, \"Signer la derniere version\" ne demande plus que la phrase de passe."
echo "(Si le cadre ne propose pas encore de signer, le central n'a pas ete redeploye depuis"
echo " l'ajout de cette fonction : scripts/114/deployer.sh backend frontend.)"
echo
echo "Pour revenir en arriere :  : > \"$SORTIE\"   (vide le fichier ; le collage reste possible)."
