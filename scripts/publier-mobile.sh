#!/bin/bash
# Construit l'APK de la marque et le depose la ou le site le sert :
#   https://<domaine de la marque>/mobile/reserve-resilience.apk
# Il part ensuite avec le site, au prochain deploiement du frontend.
#
# L'APK publie couvre les telephones 64 bits et 32 bits ; pas l'emulateur.
set -euo pipefail
racine="$(cd "$(dirname "$0")/.." && pwd)"
"$racine/scripts/tester-mobile.sh" -Pabis=arm64-v8a,armeabi-v7a

version=$(grep -o 'versionName = "[^"]*"' "$racine/mobile/androidApp/build.gradle.kts" | cut -d'"' -f2)
cible="$racine/frontend/public/mobile"
mkdir -p "$cible"
# Une application par marque. Le site propose l'une ou l'autre selon le domaine visite
# (frontend/src/app/public/home/home.component.ts, lienDeLApplication).
publier() {  # saveur, nom du fichier servi
  cp "$racine/mobile/androidApp/build/outputs/apk/$1/debug/androidApp-$1-debug.apk" "$cible/$2"
  echo "Publie : $cible/$2 (version $version, $(du -h "$cible/$2" | cut -f1))"
}
publier reserveResilience reserve-resilience.apk
publier assistaCrise assista-crise.apk
# `fichier` reste celui de Reserve Resilience : c'est ce que lisaient les versions precedentes.
printf '{"version": "%s", "fichier": "reserve-resilience.apk", "applications": {"reserve-resilience": "reserve-resilience.apk", "assista-crise": "assista-crise.apk"}}\n' "$version" > "$cible/version.json"
