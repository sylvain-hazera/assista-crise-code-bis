export type MeshtasticConnexionType = 'MQTT' | 'TCP';

export interface CompagnonMeshtastic {
  id: string;
  nom: string;
  /** MQTT (broker tiers, ex: Gaulix) ou TCP (connexion locale directe à un vrai appareil,
   * usage offline sans internet — voir MeshtasticConnexionType côté Django). */
  connexion_type: MeshtasticConnexionType;
  /** IP/hostname du vrai appareil (mode TCP local uniquement, port par défaut 4403). */
  tcp_host?: string | null;
  tcp_port?: number | null;
  /** Identifiant 32 bits — en mode MQTT, choisi par nous (identité logicielle) ; en mode TCP,
   * le vrai numéro de l'appareil connecté, lu automatiquement à la détection. */
  node_num: number;
  long_name?: string;
  short_name?: string;
  /** Clé publique X25519 dérivée côté serveur (jamais la privée, jamais exposée) — à
   * communiquer au correspondant si on veut qu'il déclare aussi notre clé de son côté, pour
   * un DM chiffré par clé publique dans les deux sens (PKI, firmware 2.5+). Sans objet en
   * mode TCP (le firmware du vrai appareil gère son propre chiffrement). */
  x25519_public_key_hex?: string;

  broker_host: string;
  broker_port: number;
  /** Racine de topic MQTT Meshtastic (ex: "msh/EU_868") — dépend de la région radio du réseau
   * relayé (Gaulix...), pas d'un matériel qu'on ne possède pas. */
  topic_racine: string;

  /** Vide = pas d'authentification (certains brokers publics n'en demandent pas). */
  mqtt_username?: string;
  /** write_only côté API — jamais renvoyé par le serveur une fois enregistré. */
  mqtt_password?: string;
  mqtt_use_tls: boolean;

  institution?: string | null;
  institution_nom?: string | null;

  principal: boolean;
  actif: boolean;
  /** Décoché par défaut (cas Gaulix, jamais confirmé relayer un paquet chiffré) : le pont force
   * alors l'envoi en clair pour ce broker, quel que soit le canal/la clé configurés — purement
   * informatif ici, l'application réelle est faite côté meshtastic-bridge/bridge.py. */
  chiffrement_supporte: boolean;

  /** Renseignés uniquement par le service-pont (meshtastic-bridge/), jamais éditables ici. */
  derniere_connexion?: string | null;
  dernier_etat?: 'CONNECTE' | 'DECONNECTE' | 'ERREUR' | null;
  derniere_erreur?: string | null;

  date_creation?: string;
}
