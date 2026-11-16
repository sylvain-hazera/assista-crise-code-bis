#!/bin/bash
# Teste la logique partagee de l'application mobile, puis construit l'APK de developpement.
# Sur le modele de tester-frontend.sh : un echec a n'importe quelle etape arrete tout.
#
#   scripts/tester-mobile.sh                      tests + APK visant le serveur de la marque
#   scripts/tester-mobile.sh -PurlSite=http://…   idem, APK visant un autre serveur
#
# Il faut un JDK complet (javac), pas seulement un JRE, et le SDK Android. Le script prend
# ceux de l'environnement s'ils existent, sinon ceux installes dans le dossier personnel.
set -euo pipefail
cd "$(dirname "$0")/../mobile"

if ! command -v javac >/dev/null 2>&1 && [ -z "${JAVA_HOME:-}" ]; then
  jdk=$(ls -d "$HOME"/.local/opt/jdk-* 2>/dev/null | sort | tail -1 || true)
  [ -n "$jdk" ] || { echo "Aucun JDK trouve : installez un JDK 17 ou 21, ou definissez JAVA_HOME." >&2; exit 1; }
  export JAVA_HOME="$jdk"
fi
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
[ -d "$ANDROID_HOME/platforms" ] || { echo "SDK Android introuvable dans $ANDROID_HOME." >&2; exit 1; }

./gradlew --quiet :shared:domaine:jvmTest :shared:donnees:jvmTest :shared:lien:jvmTest
# Une application par marque : meme code, autre nom, autre embleme, autre domaine.
./gradlew --quiet :androidApp:assembleReserveResilienceDebug :androidApp:assembleAssistaCriseDebug "$@"

echo "Tests passes."
for saveur in reserveResilience assistaCrise; do
  apk=androidApp/build/outputs/apk/$saveur/debug/androidApp-$saveur-debug.apk
  echo "APK $saveur : $PWD/$apk ($(du -h "$apk" | cut -f1))"
done
