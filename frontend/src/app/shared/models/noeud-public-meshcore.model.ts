/** Résumé de la cartographie publique importée : d'où elle vient, quand, et ce qu'elle contient.
 *
 * Servi par `/api/noeuds-publics-meshcore/resume/`. Il est affiché à côté de la carte parce
 * qu'une carte sans sa provenance ni sa date se lit comme un fait : celle-ci est l'état d'une
 * instance tierce à l'instant de l'import, pas la réalité du réseau à l'instant où on regarde. */
export interface ResumeCartographiePublique {
  instances: string[];
  total: number;
  par_role: Record<string, number>;
  actifs: number;
  /** Nombre de nœuds par taille de préfixe, en octets. Un préfixe d'un octet n'a que
   * 256 valeurs : les sauts de ces nœuds ne prouvent aucune topologie. */
  par_taille_hash: Record<string, number>;
  importe_le: string | null;
  vu_entre: [string | null, string | null];
}
