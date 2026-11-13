import { Pipe, PipeTransform } from '@angular/core';

/** Indicatifs français, pour réécrire un E.164 dans sa forme nationale.
 *
 * Source de vérité : `backend/core/telephone.py`, qui fait la conversion inverse à
 * l'enregistrement. Cette table-ci n'en est qu'un reflet d'affichage — si elle vieillit, le
 * pire qui arrive est qu'un numéro reste écrit « +262692123456 » au lieu de « 06 92 12 34 56 ».
 * Dégradé, jamais faux : c'est pourquoi cette duplication est acceptable, là où dupliquer la
 * conversion d'ENVOI ne le serait pas. */
const INDICATIFS_FR = ['33', '262', '590', '596', '594'];

/** Affiche un numéro de téléphone dans l'écriture du pays qui le porte.
 *
 * Les numéros sont enregistrés en E.164 (`+33612345678`) : c'est la seule écriture que tous
 * les fournisseurs de SMS acceptent, et la seule qui dise de quel pays il s'agit. Mais un
 * E.164 ne se lit pas à l'œil sur une fiche consultée en urgence — d'où ce filtre, qui rend
 * « 06 12 34 56 78 » pour un numéro français et laisse l'E.164 tel quel pour un numéro
 * étranger, où il est la bonne écriture.
 *
 * N'est JAMAIS utilisé pour composer un lien `tel:` ni pour envoyer : ceux-là prennent la
 * valeur brute, qui est universelle.
 */
@Pipe({ name: 'telephone', standalone: true })
export class TelephonePipe implements PipeTransform {
  transform(valeur: string | null | undefined): string {
    const numero = (valeur ?? '').trim();
    if (!numero.startsWith('+')) {
      // Saisie ancienne ou texte libre (« voir le standard ») : rendue telle quelle. On
      // n'interprète pas ce qu'on n'est pas sûr de lire.
      return numero;
    }
    const chiffres = numero.slice(1);
    // Du plus long au plus court : « 262 » doit être essayé avant « 2 » n'existerait-il.
    for (const indicatif of [...INDICATIFS_FR].sort((a, b) => b.length - a.length)) {
      if (!chiffres.startsWith(indicatif)) { continue; }
      const national = '0' + chiffres.slice(indicatif.length);
      if (national.length === 10) {
        return national.replace(/(\d{2})(?=\d)/g, '$1 ');
      }
    }
    return numero;
  }
}
