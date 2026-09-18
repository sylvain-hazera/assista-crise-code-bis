/** Coordonnées du sous-traitant/hébergeur (voir /rgpd section 1 et /mentions-legales),
 * protégées d'une lecture directe par un robot moissonnant le HTML brut ou le bundle JS
 * compilé — chiffrées par un simple décalage auto-inverse (lettres : ROT13 ; chiffres :
 * décalage de 5 modulo 10), décodées à l'exécution. Ne protège pas d'un robot qui exécute du
 * JavaScript (aucune protection côté client ne le peut réellement), seulement des collecteurs
 * qui ne font que lire le texte source — demande explicite de l'utilisateur du 2026-09-18.
 * Une seule fonction pour chiffrer ET déchiffrer : le décalage est son propre inverse. */
export function decoderContact(texte: string): string {
  return texte.replace(/[a-zA-Z0-9]/g, (c) => {
    if (c >= '0' && c <= '9') {
      return String.fromCharCode(((c.charCodeAt(0) - 48 + 5) % 10) + 48);
    }
    const base = c <= 'Z' ? 65 : 97;
    return String.fromCharCode(((c.charCodeAt(0) - base + 13) % 26) + base);
  });
}

export const CONTACT_NOM = decoderContact('Flyinva UNMREN');
export const CONTACT_ADRESSE = decoderContact('0 cynpr Tnoevry Snheé, 88755 Obeqrnhk');
export const CONTACT_EMAIL = decoderContact('pbagnpg@nffvfgn-pevfr.se');
export const CONTACT_TELEPHONE = decoderContact('51.33.33.31.62');
