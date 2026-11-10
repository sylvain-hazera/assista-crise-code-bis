/** Un nœud ENTENDU par nos passerelles, proposé à l'utilisateur pour qu'il reconnaisse le sien.
 *
 * Servis par `/api/noeuds-meshcore/candidats/` et `/api/noeuds-meshtastic/candidats/`, ouverts à
 * tout compte connecté : rattacher son nœud est ce qui OUVRE le droit radio, donc la liste qui
 * sert à le trouver ne peut pas être derrière ce droit.
 *
 * La charge est volontairement minimale — de quoi reconnaître son appareil, rien de plus. Ni
 * position ni télémétrie : la position d'un companion est très souvent un domicile. */
export interface CandidatNoeudMeshCore {
  pubkey_hex: string;
  nom: string;
  dernier_advert: string | null;
  /** Déjà rattaché à un compte — lequel n'est pas dit. */
  deja_associe: boolean;
  /** Rattaché à MON compte : se libère, au lieu de ne pas pouvoir être réclamé. */
  a_moi: boolean;
}

export interface CandidatNoeudMeshtastic {
  node_num: number;
  /** `!a1b2c3d4` : la forme sous laquelle l'appareil lui-même l'affiche. Un entier décimal
   * n'est reconnaissable par personne. */
  node_id: string;
  long_name: string;
  short_name: string;
  hardware_model: string;
  /** La passerelle qui l'a entendu : `reclamer` a besoin de savoir par quel broker passer
   * quand plusieurs l'ont entendu. */
  compagnon_id: string;
  compagnon_nom: string;
  dernier_advert: string | null;
  deja_associe: boolean;
  a_moi: boolean;
}
