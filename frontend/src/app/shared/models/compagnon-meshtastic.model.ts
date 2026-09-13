export interface CompagnonMeshtastic {
  id: string;
  nom: string;
  /** Identifiant 32 bits de cette identité logicielle sur le mesh Meshtastic (choisi à la
   * création, pas dérivé d'un matériel réel — ce companion n'est pas un appareil physique). */
  node_num: number;
  long_name?: string;
  short_name?: string;

  broker_host: string;
  broker_port: number;
  /** Racine de topic MQTT Meshtastic (ex: "msh/EU_868") — dépend de la région radio du réseau
   * relayé (Gaulix...), pas d'un matériel qu'on ne possède pas. */
  topic_racine: string;

  institution?: string | null;
  institution_nom?: string | null;

  principal: boolean;
  actif: boolean;

  /** Renseignés uniquement par le service-pont (meshtastic-bridge/), jamais éditables ici. */
  derniere_connexion?: string | null;
  dernier_etat?: 'CONNECTE' | 'DECONNECTE' | 'ERREUR' | null;
  derniere_erreur?: string | null;

  date_creation?: string;
}
