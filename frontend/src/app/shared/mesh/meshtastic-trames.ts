/**
 * Protocole client Meshtastic : cadrage série, et les quelques messages dont un relais a besoin.
 *
 * **Tout est relevé dans la bibliothèque Python `meshtastic` 2.7** dont dépend déjà notre pont —
 * `stream_interface.py` (cadrage), `ble_interface.py` (UUID), `mesh_interface.py`
 * (configuration, battement) et les descripteurs de `mesh_pb2` / `channel_pb2` pour les numéros
 * de champs. Les tests comparent nos octets à ceux que produit `mesh_pb2` lui-même.
 *
 * **Portée** : se présenter et lire la configuration (`want_config_id`), garder la liaison
 * (`heartbeat`), envoyer un message texte, lire les messages texte reçus. Ni administration, ni
 * positions, ni télémétrie : tout cela reste au pont Python.
 *
 * **Aucune cryptographie ici** : c'est le firmware qui chiffre, en PSK de canal ou en PKI pour
 * un message direct dont il connaît la clé du destinataire. Le lien USB, Bluetooth ou HTTP
 * transporte du clair entre la radio et ce navigateur.
 *
 * Les protobufs Meshtastic sont sous GPL-3.0. Ce fichier n'en reprend aucun : il réécrit
 * l'encodage de quelques champs à partir de leurs numéros, qui sont des faits d'interface. Il
 * vit de toute façon dans l'application web, sous AGPL-3.0, compatible avec la GPL-3.0
 * (article 13 de chacune).
 */
import { EcrivainProtobuf, champ, lireChamps, texte } from './protobuf-mini';

/** Cadrage série : `0x94 0xC3`, longueur sur 2 octets GROS-boutistes, puis le protobuf. */
export const MT_START1 = 0x94;
export const MT_START2 = 0xc3;
/** `MAX_TO_FROM_RADIO_SIZE` de stream_interface.py. */
export const MT_TAILLE_MAX = 512;

/** Destinataire « tout le monde » (`BROADCAST_NUM`). */
export const MT_DIFFUSION = 0xffffffff;

/** `PortNum.TEXT_MESSAGE_APP`. */
export const PORT_TEXTE = 1;

/**
 * Charge utile maximale d'un paquet. Le firmware refuse au-delà (`Constants.h`,
 * `DATA_PAYLOAD_LEN` = 233) ; on garde de la marge pour les en-têtes que le firmware ajoute
 * selon le mode de chiffrement.
 */
export const MT_CHARGE_MAX = 200;

/** UUID GATT relevés dans `ble_interface.py`. */
export const MESHTASTIC_BLE = {
  SERVICE: '6ba1b218-15a8-461f-9fa8-5dcae273eafd',
  TO_RADIO: 'f75c76d2-129e-4dad-a1dd-7866124401e7',
  FROM_RADIO: '2c55e69e-4993-11ed-b878-0242ac120002',
  /** Notifié quand quelque chose attend dans FROM_RADIO : il faut alors le lire en boucle. */
  FROM_NUM: 'ed9da18c-a800-4f66-a670-aa7547e34453',
} as const;

/**
 * Octets envoyés avant tout sur une liaison série : 32 fois `START2`. Repris de
 * `stream_interface.py::connect` — ils réveillent un appareil endormi et le forcent à se
 * resynchroniser sur un début de trame.
 */
export function octetsDeReveil(): Uint8Array {
  return new Uint8Array(32).fill(MT_START2);
}

export function encadrerMeshtastic(charge: Uint8Array): Uint8Array {
  if (charge.length > MT_TAILLE_MAX) {
    throw new Error(`Trame Meshtastic trop longue (${charge.length} > ${MT_TAILLE_MAX}).`);
  }
  const trame = new Uint8Array(4 + charge.length);
  trame[0] = MT_START1;
  trame[1] = MT_START2;
  trame[2] = (charge.length >> 8) & 0xff;
  trame[3] = charge.length & 0xff;
  trame.set(charge, 4);
  return trame;
}

/**
 * Découpe un flux série en protobufs `FromRadio`. Même logique que `stream_interface.py` : on
 * cherche `0x94`, puis `0xC3`, puis la longueur ; une longueur au-delà de 512 trahit du bruit et
 * fait reprendre la recherche. Entre les trames, le firmware écrit parfois ses journaux en
 * texte clair sur le même port : ils sont simplement sautés.
 */
export class DecoupeurMeshtastic {
  private reliquat = new Uint8Array(0);

  pousser(octets: Uint8Array): Uint8Array[] {
    const mis = new Uint8Array(this.reliquat.length + octets.length);
    mis.set(this.reliquat, 0);
    mis.set(octets, this.reliquat.length);

    const trames: Uint8Array[] = [];
    let i = 0;
    for (;;) {
      while (i < mis.length && mis[i] !== MT_START1) { i++; }
      if (mis.length - i < 4) { break; }
      if (mis[i + 1] !== MT_START2) { i++; continue; }
      const taille = (mis[i + 2] << 8) | mis[i + 3];
      if (taille > MT_TAILLE_MAX) { i++; continue; }
      if (mis.length - i - 4 < taille) { break; }
      trames.push(mis.slice(i + 4, i + 4 + taille));
      i += 4 + taille;
    }
    this.reliquat = mis.slice(i);
    return trames;
  }

  reinitialiser(): void {
    this.reliquat = new Uint8Array(0);
  }
}

// ══ ToRadio ══════════════════════════════════════════════════════════════════
// Numéros de champs relevés dans les descripteurs de mesh_pb2 (ToRadio, MeshPacket, Data).

/**
 * Poignée de main en deux temps, reprise du client web officiel (`sdk/src/core/client/
 * handshake.ts`, partagé avec Android) : d'abord la configuration seule, puis la base de nœuds
 * seule. **Le firmware traite ces deux valeurs à part** : il ne faut pas les remplacer par des
 * identifiants aléatoires — ce que faisait notre première version, qui recevait tout d'un bloc.
 */
export const NONCE_CONFIG = 69420;
export const NONCE_NOEUDS = 69421;

/** `ToRadio{want_config_id}`. */
export function toRadioVeutConfig(identifiant: number): Uint8Array {
  return new EcrivainProtobuf().varint(3, identifiant).fin();
}

/**
 * Premier nonce de battement, puis on incrémente. Relevé dans le client officiel, et c'est
 * bloquant : **depuis le firmware 2.7.23, la radio jette un `ToRadio` identique au précédent**,
 * donc un battement fixe ne passe qu'une fois ; et le nonce 1 lui demande de **diffuser sa fiche
 * sur tout le maillage**. Notre première version envoyait un battement vide, toujours le même.
 */
export const PREMIER_NONCE_BATTEMENT = 2;

/** `ToRadio{heartbeat: {nonce}}`. */
export function toRadioBattement(nonce: number): Uint8Array {
  return new EcrivainProtobuf()
    .message(7, new EcrivainProtobuf().varint(1, nonce))
    .fin();
}

/** Le nonce suivant : jamais 0 ni 1, et on reboucle sur 2 avant de sortir de 32 bits. */
export function nonceSuivant(nonce: number): number {
  return nonce >= 0xffffffff ? PREMIER_NONCE_BATTEMENT : nonce + 1;
}

/**
 * `ToRadio{packet: MeshPacket{to, channel, decoded: Data{portnum: TEXT, payload}, id, want_ack}}`.
 *
 * `from` n'est pas renseigné : c'est la radio qui le remplit. Pour un message direct, le
 * firmware choisit seul le chiffrement par clé publique s'il connaît celle du destinataire.
 */
export function toRadioTexte(destinataire: number, contenu: string, identifiant: number,
                             canal = 0, accuse = true): Uint8Array {
  const data = new EcrivainProtobuf()
    .varint(1, PORT_TEXTE)
    .octetsBruts(2, new TextEncoder().encode(contenu));
  const paquet = new EcrivainProtobuf()
    .fixed32(2, destinataire)
    .varint(3, canal)
    .message(4, data)
    .fixed32(6, identifiant)
    .varint(10, accuse);
  return new EcrivainProtobuf().message(1, paquet).fin();
}

/**
 * Découpe un texte sous la charge maximale d'un paquet, sans couper un caractère UTF-8 en
 * deux. Le serveur découpe déjà les messages de canal ; pas toujours les messages directs.
 */
export function decouperTexte(contenu: string, maximum = MT_CHARGE_MAX): string[] {
  const morceaux: string[] = [];
  let courant = '';
  let taille = 0;
  for (const caractere of contenu) {
    const n = new TextEncoder().encode(caractere).length;
    if (taille + n > maximum && courant) {
      morceaux.push(courant);
      courant = '';
      taille = 0;
    }
    courant += caractere;
    taille += n;
  }
  if (courant || !morceaux.length) { morceaux.push(courant); }
  return morceaux;
}

/** Un identifiant de paquet : 32 bits, jamais nul (un id nul vaut « absent »). */
export function nouvelIdentifiant(): number {
  const tirage = new Uint32Array(1);
  crypto.getRandomValues(tirage);
  return tirage[0] || 1;
}

// ══ FromRadio ════════════════════════════════════════════════════════════════

export type EvenementMeshtastic =
  | { genre: 'mon_noeud'; numero: number }
  /** Une trame de la poignée de main qui ne nous sert pas (config, métadonnées…) : elle prouve
   * que la radio progresse, et réarme le délai d'inactivité. */
  | { genre: 'progression' }
  | { genre: 'noeud'; numero: number; nomLong: string; clePubliqueHex: string }
  | { genre: 'canal'; index: number; nom: string; actif: boolean }
  | { genre: 'config_terminee'; identifiant: number }
  | { genre: 'texte'; de: number; vers: number; canal: number; texte: string; id: number }
  | { genre: 'autre' };

function hex(octets: Uint8Array | undefined): string {
  return octets ? Array.from(octets).map(o => o.toString(16).padStart(2, '0')).join('') : '';
}

/**
 * Décode un `FromRadio` en l'événement qui intéresse un relais. Tout le reste — positions,
 * télémétrie, paquets que la radio n'a pas pu déchiffrer — devient `autre` : on les compte, on
 * ne les interprète pas.
 */
export function lireFromRadio(octets: Uint8Array): EvenementMeshtastic {
  const racine = lireChamps(octets);

  const monNoeud = champ(racine, 3)?.octets;
  if (monNoeud) {
    return { genre: 'mon_noeud', numero: champ(lireChamps(monNoeud), 1)?.nombre ?? 0 };
  }

  const infoNoeud = champ(racine, 4)?.octets;
  if (infoNoeud) {
    const n = lireChamps(infoNoeud);
    const utilisateur = champ(n, 2)?.octets;
    const u = utilisateur ? lireChamps(utilisateur) : [];
    return {
      genre: 'noeud',
      numero: champ(n, 1)?.nombre ?? 0,
      nomLong: texte(champ(u, 2)?.octets),
      clePubliqueHex: hex(champ(u, 8)?.octets),
    };
  }

  const canal = champ(racine, 10)?.octets;
  if (canal) {
    const c = lireChamps(canal);
    const reglages = champ(c, 2)?.octets;
    // Rôle 0 = DISABLED, 1 = PRIMARY, 2 = SECONDARY (channel_pb2.Channel.Role).
    return {
      genre: 'canal',
      index: champ(c, 1)?.nombre ?? 0,
      nom: texte(reglages ? champ(lireChamps(reglages), 3)?.octets : undefined),
      actif: (champ(c, 3)?.nombre ?? 0) !== 0,
    };
  }

  const fin = champ(racine, 7);
  if (fin && fin.nombre !== undefined) {
    return { genre: 'config_terminee', identifiant: fin.nombre };
  }

  // config (5), moduleConfig (9), metadata (13), fileInfo (15), deviceuiConfig (17), et les
  // variantes plus récentes que notre relevé ne connaît pas encore (≥ 19, regionPresets…).
  if (racine.some(c => [5, 9, 13, 15, 17].includes(c.numero) || c.numero >= 19)) {
    return { genre: 'progression' };
  }

  const paquet = champ(racine, 2)?.octets;
  if (paquet) {
    const p = lireChamps(paquet);
    const decode = champ(p, 4)?.octets;
    if (!decode) { return { genre: 'autre' }; }   // chiffré pour quelqu'un d'autre
    const d = lireChamps(decode);
    if ((champ(d, 1)?.nombre ?? 0) !== PORT_TEXTE) { return { genre: 'autre' }; }
    return {
      genre: 'texte',
      de: champ(p, 1)?.nombre ?? 0,
      vers: champ(p, 2)?.nombre ?? 0,
      canal: champ(p, 3)?.nombre ?? 0,
      texte: texte(champ(d, 2)?.octets),
      id: champ(p, 6)?.nombre ?? 0,
    };
  }

  return { genre: 'autre' };
}
