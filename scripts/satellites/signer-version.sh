#!/usr/bin/env bash
# Signe une version pour les satellites, et affiche ce qu'il faut coller dans la page
# Satellites du central (cadre "Versions signees").
#
#   scripts/satellites/signer-version.sh            # signe le dernier commit pousse (origin/main)
#   scripts/satellites/signer-version.sh <commit>   # signe ce commit-la
#
# Ne signe QUE ce qui est deja sur le depot distant : un satellite recupere son code la-bas,
# et une version signee qu'il ne peut pas telecharger est un ordre qui echoue partout.
#
# Signer, c'est declarer "cette version peut etre installee sur tous les satellites". La
# phrase de passe de la cle vous est demandee a chaque fois : c'est voulu.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLE="${ASSISTA_CLE_DOSSIER:-$HOME/.config/assista-crise}/signature-satellites"
ESPACE="assista-crise-satellite"   # identique a backend/core/signature_satellites.py

[ -f "$CLE" ] || { echo "Cle introuvable ($CLE). Creez-la : scripts/satellites/creer-cle-signature.sh" >&2; exit 1; }

git -C "$RACINE" fetch --quiet origin || { echo "Depot distant injoignable (git fetch)." >&2; exit 1; }
BRANCHE="$(git -C "$RACINE" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)"
COMMIT="$(git -C "$RACINE" rev-parse --verify --quiet "${1:-$BRANCHE}^{commit}")" \
    || { echo "Commit inconnu : ${1:-$BRANCHE}" >&2; exit 1; }

if ! git -C "$RACINE" merge-base --is-ancestor "$COMMIT" "$BRANCHE"; then
    echo "Ce commit n'est pas sur $BRANCHE : il n'est pas pousse, les satellites ne" >&2
    echo "pourraient pas le recuperer. Poussez d'abord, puis relancez." >&2
    exit 1
fi

echo "Version a signer :"
git -C "$RACINE" log -1 --format='  %H%n  %cd  %s' --date=short "$COMMIT"
echo

SIGNATURE="$(printf '%s/v1\ncommit=%s\n' "$ESPACE" "$COMMIT" | ssh-keygen -Y sign -f "$CLE" -n "$ESPACE")"

echo
echo "================ A COLLER DANS LA PAGE SATELLITES ================"
echo "Numero de version :"
echo "$COMMIT"
echo
echo "Signature :"
echo "$SIGNATURE"
echo "=================================================================="
