/** « Ce nœud est à nous » — qui répond d'un répéteur que personne ne porte.
 *
 * Distinct de `NoeudUtilisateurMeshtastic`, qui dit « ce nœud EST cette personne » et sert à
 * résoudre l'expéditeur d'un message. Ici on ne dit pas qui est le nœud, on dit qui en répond
 * (voir backend/core/models.py:RattachementNoeudRadio). */
export interface RattachementNoeudRadio {
  id: string;
  node_num: number;
  institution: string | null;
  institution_nom?: string | null;
  utilisateur: string | null;
  utilisateur_nom?: string | null;
  /** Un seul libellé pour l'affichage : l'interface n'a pas à savoir laquelle des deux cibles
   * est renseignée. */
  responsable?: string | null;
  libelle: string;
  note: string;
  rattache_par?: string | null;
  date_rattachement?: string;
}
