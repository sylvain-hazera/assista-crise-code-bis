#!/usr/bin/env bash
# Cree la cle qui signe les versions des satellites. A FAIRE UNE SEULE FOIS.
#
#   scripts/satellites/creer-cle-signature.sh
#
# - La cle PRIVEE est ecrite dans ~/.config/assista-crise/signature-satellites, protegee par
#   une phrase de passe que vous choisissez. Elle ne va ni dans le depot, ni sur le serveur.
#   Gardez-en une copie hors de cette machine (cle USB rangee) : perdue, il faudra repasser
#   sur CHAQUE satellite pour lui en donner une nouvelle.
# - La cle PUBLIQUE est ajoutee a backend/core/signature_satellites.pub, a enregistrer dans le
#   depot : le central s'en sert pour refuser une signature fausse, et chaque satellite en
#   garde une copie a son installation.
#
# Voir backend/core/signature_satellites.py pour le pourquoi.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOSSIER="${ASSISTA_CLE_DOSSIER:-$HOME/.config/assista-crise}"
CLE="$DOSSIER/signature-satellites"
PUBLIQUES="$RACINE/backend/core/signature_satellites.pub"

command -v ssh-keygen >/dev/null 2>&1 || { echo "ssh-keygen est requis (paquet openssh-client)." >&2; exit 1; }

if [ -e "$CLE" ]; then
    echo "Une cle existe deja : $CLE"
    echo "Rien n'a ete fait. Pour en changer, deplacez d'abord l'ancienne — et sachez que les"
    echo "satellites deja installes continueront de n'accepter que l'ancienne."
    exit 1
fi

mkdir -p "$DOSSIER"
chmod 700 "$DOSSIER"

echo "Creation de la cle de signature des satellites."
echo "Choisissez une PHRASE DE PASSE : elle vous sera demandee a chaque version signee."
echo "Ne la laissez pas vide — une cle sans phrase de passe est une cle en clair sur le disque."
echo
# Sans -N : ssh-keygen demande lui-meme la phrase de passe, deux fois, sans l'afficher.
ssh-keygen -t ed25519 -C "signature-satellites-assista-crise" -f "$CLE"

# Refuse une cle sans phrase de passe : "ssh-keygen -y -P ''" ne reussit que si elle est vide.
if ssh-keygen -y -P "" -f "$CLE" >/dev/null 2>&1; then
    rm -f "$CLE" "$CLE.pub"
    echo >&2
    echo "Phrase de passe vide : la cle a ete supprimee. Relancez et choisissez-en une." >&2
    exit 1
fi

if ! grep -qF "$(cut -d' ' -f2 "$CLE.pub")" "$PUBLIQUES" 2>/dev/null; then
    cat "$CLE.pub" >> "$PUBLIQUES"
fi

echo
echo "Cle creee."
echo "  privee   : $CLE   (a sauvegarder hors de cette machine)"
echo "  publique : ajoutee a backend/core/signature_satellites.pub"
echo
echo "Reste a faire :"
echo "  1. enregistrer ce fichier dans le depot et le pousser ;"
echo "  2. redeployer le central (il lit la cle a la construction de son image) ;"
echo "  3. sur chaque satellite deja installe, une derniere fois sur place :"
echo "       ./installer.sh mettre-a-jour"
echo "     (c'est ce passage qui lui donne la cle et l'agent de mise a jour)."
