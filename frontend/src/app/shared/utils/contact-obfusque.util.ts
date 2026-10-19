/** Coordonnées du sous-traitant/hébergeur (/rgpd, /mentions-legales) masquées aux robots qui
 * lisent le HTML ou le bundle sans exécuter le JS : ROT13 pour les lettres, décalage de 5
 * modulo 10 pour les chiffres. Le décalage est son propre inverse (une seule fonction). */
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
