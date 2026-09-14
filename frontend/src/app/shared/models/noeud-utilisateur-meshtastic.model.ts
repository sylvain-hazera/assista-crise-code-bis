export interface NoeudUtilisateurMeshtastic {
  id: string;
  utilisateur: string;
  utilisateur_nom?: string;
  node_num: number;
  nom_noeud?: string;
  actif: boolean;
  date_association?: string;
}

/** Corps d'erreur 400 de NoeudUtilisateurMeshtasticViewSet.reclamer quand le broker MQTT ne
 * peut pas être déduit tout seul (jamais détecté, ou détecté sur plusieurs brokers à la fois)
 * — voir la doc de l'action côté Django. */
export interface ReclamerMeshtasticBrokerRequis {
  detail: string;
  compagnon_requis: true;
  compagnons_candidats: { id: string; nom: string }[] | null;
}
