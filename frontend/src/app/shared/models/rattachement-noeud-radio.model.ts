/** « Ce nœud est à nous » — qui répond d'un répéteur que personne ne porte.
 *
 * Distinct de `NoeudUtilisateurMeshtastic`, qui dit « ce nœud EST cette personne » et sert à
 * résoudre l'expéditeur d'un message. Ici on ne dit pas qui est le nœud, on dit qui en répond
 * (voir backend/core/models.py:RattachementNoeudRadio). */
/** Par quoi on est autorisé à administrer le nœud — ce qu'on remplit en le réclamant.
 *
 * Les deux moyens MeshCore viennent du firmware (`simple_repeater/MyMesh.cpp` : un mot de passe
 * vide fait vérifier l'ACL, sinon il est comparé à celui de l'administrateur puis de l'invité).
 * `AUCUN` est le cas Meshtastic, où l'autorisation est la clé publique de la passerelle posée
 * dans `security.admin_key` du nœud — ni lisible ni vérifiable à distance. */
export type MoyenAdminRadio = 'AUCUN' | 'MOT_DE_PASSE' | 'ACL';

/** Où en est la démonstration qu'on contrôle vraiment ce nœud. MeshCore permet de la faire :
 * un mot de passe se teste, une entrée d'ACL se teste. Tant qu'elle n'est pas `VERIFIEE`, le
 * rattachement dit seulement qui prétend répondre du nœud. */
export type StatutPreuveRadio = 'NON_VERIFIE' | 'EN_ATTENTE' | 'VERIFIEE' | 'ECHEC';

export interface RattachementNoeudRadio {
  id: string;
  /** Identité Meshtastic. Vide pour un nœud MeshCore : une et une seule des deux. */
  node_num: number | null;
  /** Identité MeshCore : clé publique Ed25519, 64 caractères hexadécimaux. */
  pubkey_hex: string;
  /** Déduit de l'identité par le serveur, jamais stocké. */
  protocole?: 'MESHTASTIC' | 'MESHCORE';
  institution: string | null;
  institution_nom?: string | null;
  utilisateur: string | null;
  utilisateur_nom?: string | null;
  /** Un seul libellé pour l'affichage : l'interface n'a pas à savoir laquelle des deux cibles
   * est renseignée. */
  responsable?: string | null;
  libelle: string;
  note: string;
  moyen_admin: MoyenAdminRadio;
  moyen_admin_libelle?: string;
  /** Jamais renvoyé par l'API : il part vers le serveur, il n'en revient pas. */
  mot_de_passe?: string;
  /** Companion qui ouvrira la session, et dont la clé publique doit figurer dans l'ACL. */
  compagnon_meshcore: string | null;
  statut_preuve?: StatutPreuveRadio;
  statut_preuve_libelle?: string;
  /** Vrai quand l'écriture est réellement ouverte sur ce nœud. */
  preuve_faite?: boolean;
  date_verification?: string | null;
  erreur_verification?: string;
  rattache_par?: string | null;
  date_rattachement?: string;
}
