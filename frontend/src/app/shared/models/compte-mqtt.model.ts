/** Compte du broker MQTT (voir backend/core/models.py:CompteMqtt).
 *
 * `mot_de_passe` n'est JAMAIS renvoyé par la liste : il s'obtient par l'action dédiée
 * `mot-de-passe/`, qui laisse une trace au journal d'audit. */
export type RoleCompteMqtt = 'RADIO' | 'SUPERVISION';

export interface CompteMqtt {
  id: string;
  nom: string;
  role: RoleCompteMqtt;
  role_libelle: string;
  racine_topic: string;
  description: string;
  /** Compte nécessaire au broker (exporteur de supervision, pont) : non supprimable. */
  infrastructure: boolean;
  actif: boolean;
  date_creation: string;
  modifie_le: string;
}

/** Réponse des actions `mot-de-passe/` et `regenerer/`. */
export interface MotDePasseCompteMqtt {
  nom: string;
  mot_de_passe: string;
}
