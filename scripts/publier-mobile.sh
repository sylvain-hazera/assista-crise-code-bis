#!/bin/bash
# Construit l'APK de la marque et le depose la ou le site le sert :
#   https://<domaine de la marque>/mobile/reserve-resilience.apk
# Il part ensuite avec le site, au prochain deploiement du frontend.
#
# L'APK publie couvre les telephones 64 bits et 32 bits ; pas l'emulateur.
set -euo pipefail
racine="$(cd "$(dirname "$0")/.." && pwd)"
"$racine/scripts/tester-mobile.sh" -Pabis=arm64-v8a,armeabi-v7a

apk="$racine/mobile/androidApp/build/outputs/apk/reserveResilience/debug/androidApp-reserveResilience-debug.apk"
version=$(grep -o 'versionName = "[^"]*"' "$racine/mobile/androidApp/build.gradle.kts" | cut -d'"' -f2)
cible="$racine/frontend/public/mobile"
mkdir -p "$cible"
cp "$apk" "$cible/reserve-resilience.apk"
printf '{"version": "%s", "fichier": "reserve-resilience.apk"}\n' "$version" > "$cible/version.json"
echo "Publie : $cible/reserve-resilience.apk (version $version, $(du -h "$cible/reserve-resilience.apk" | cut -f1))"
