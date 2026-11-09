/** Réponse de `GET /api/contacts-meshtastic/routage/` — voir backend/core/routage_meshtastic.py,
 * qui explique pourquoi « quelle passerelle a entendu ce nœud » et « par où l'atteindre » sont
 * deux questions distinctes. */

export interface PasserelleEntendue {
  node_num: number;
  nom: string;
  snr: number | null;
  rssi: number | null;
  nombre: number;
  dernier_vu: string | null;
  /** Une de NOS passerelles (node_num d'un companion) ou celle d'un tiers sur le même broker :
   * dans le second cas son `downlink_enabled` nous est inconnu, la descente n'est pas garantie. */
  nous: boolean;
  retour_prouve: boolean;
}

export interface EtapeChemin {
  de: number;
  nom_de: string;
  vers: number;
  nom_vers: string;
  snr: number | null;
  sources: string[];
  /** Le sens inverse a-t-il été observé ? Sinon ce saut sert à écouter, pas forcément à parler. */
  retour_prouve: boolean;
}

export interface RouteMeshtastic {
  node_num: number;
  nom: string;
  actif: boolean;
  dernier_advert: string | null;
  /** Companion par lequel émettre : le broker cloisonne, publier ailleurs n'atteint pas ce nœud. */
  compagnon_id: string | null;
  compagnon_nom: string | null;
  broker: string | null;
  passerelles: PasserelleEntendue[];
  passerelles_a_nous: number;
  /** Nombre de sauts jusqu'à la passerelle la plus proche ; null = aucune ne l'a entendu. */
  sauts: number | null;
  chemin: EtapeChemin[];
  relais_obligatoire: { node_num: number; nom: string } | null;
  retour_prouve: boolean;
  hop_limit_suffisant: boolean | null;
  /** Phrase lisible : l'opérateur doit pouvoir contester la conclusion. */
  raison: string;
}

export interface RoutageMeshtastic {
  routes: RouteMeshtastic[];
  fenetre_jours: number;
  hop_limit_defaut: number;
  hop_limit_max: number;
  calcule_le: string;
}
