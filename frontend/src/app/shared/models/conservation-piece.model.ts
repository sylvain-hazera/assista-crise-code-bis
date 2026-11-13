/** Politique de conservation des pièces justificatives.
 *
 * Servie par `/api/conservation-pieces/` et par chaque titre du catalogue (`conservation`).
 * Elle n'est pas recopiée ici : c'est la MÊME table qui, côté serveur, décide de détruire le
 * fichier (`core/pieces_conformite.py`). Une copie dans le navigateur finirait par diverger,
 * et l'écran promettrait alors une destruction qui n'aurait pas lieu.
 */

export type RegimeConservation =
  'VERIFIER_DETRUIRE' | 'CONSERVER_ENGAGEMENT' | 'DUREE_LEGALE';

export interface RegimeDescription {
  code: RegimeConservation;
  libelle: string;
  resume: string;
  pourquoi: string;
}

export interface FamilleConservation {
  code: string;
  libelle: string;
}

export interface PieceConservation {
  cle: string;
  libelle: string;
  famille: string;
  regime: RegimeConservation;
  duree: string;
  /** Le texte applicable, cité. Sans lui, la durée est une affirmation de plus. */
  base_legale: string;
  /** Pourquoi on demande cette pièce, dit à celui à qui on la demande. */
  pourquoi: string;
  /** Vrai quand un texte impose la durée ; faux quand elle est recommandée. Présenter une
   * recommandation comme une obligation est une faute symétrique de l'inverse. */
  ferme: boolean;
  /** Vrai pour les pièces qu'un bénévole dépose lui-même. Les autres sont là pour que
   * l'association ait la table complète. */
  deposable: boolean;
  /** Présent quand la règle accompagne une pièce précise plutôt que la table générale. */
  jours_avant_purge_non_validee?: number;
}

export interface TableConservation {
  regimes: RegimeDescription[];
  familles: FamilleConservation[];
  pieces: PieceConservation[];
  jours_avant_purge_non_validee: number;
  jours_avant_rappel_purge: number;
}
