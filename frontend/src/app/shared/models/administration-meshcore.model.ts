/** Administration à distance des répéteurs MeshCore (voir backend/core/models.py :
 * TacheAdminMeshCore, et meshcore-bridge/admin_meshcore.py pour l'exécution).
 *
 * Deux choses à savoir, et elles viennent du firmware MeshCore :
 *
 * 1. **Une écriture exige une preuve de contrôle faite** sur le répéteur. Il n'existe ici aucun
 *    équivalent de `security.admin_key` : qui a le mot de passe écrit. La vérification n'est
 *    donc pas un confort, c'est la condition.
 * 2. **`RADIO_TEMPORAIRE` est la voie des essais radio** : ses paramètres reviennent seuls au
 *    bout du délai, qui est obligatoire. C'est ce qui manque côté Meshtastic, où un réglage
 *    faux peut rendre un nœud muet sans retour possible. */
export type TypeTacheAdminMeshCore =
  | 'VERIFIER_ACCES'
  | 'LIRE_STATUT'
  | 'LIRE_VOISINS'
  | 'LIRE_REGIONS'
  | 'LIRE_TELEMETRIE'
  | 'RADIO_TEMPORAIRE'
  | 'DEFINIR_REGLAGE'
  | 'ANNONCER'
  | 'REDEMARRER';

export type StatutTacheAdminMeshCore = 'EN_ATTENTE' | 'EN_COURS' | 'TERMINEE' | 'ECHEC';

export interface TacheAdminMeshCore {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  pubkey_cible: string;
  type_tache: TypeTacheAdminMeshCore;
  type_tache_libelle?: string;
  parametres?: Record<string, unknown> | null;
  statut: StatutTacheAdminMeshCore;
  tentatives: number;
  /** Chiffrée au repos côté serveur, rendue en JSON ici. */
  reponse?: string | null;
  erreur?: string | null;
  est_ecriture?: boolean;
  demande_par?: string | null;
  date_creation: string;
  date_prise?: string | null;
  date_reponse?: string | null;
}

/** Les opérations proposées à l'écran, avec ce que chacune coûte en cas d'erreur.
 *
 * Servie depuis le frontend et non depuis l'API, contrairement au catalogue de réglages
 * Meshtastic : il n'y a ici ni borne ni type à tenir synchronisés — les bornes de
 * `RADIO_TEMPORAIRE` sont dans le serializer, et le serveur revalide de toute façon. */
export interface OperationMeshCore {
  type: TypeTacheAdminMeshCore;
  libelle: string;
  /** Vrai quand l'opération écrit sur le répéteur, donc exige une preuve faite. */
  ecriture: boolean;
  aide: string;
}
