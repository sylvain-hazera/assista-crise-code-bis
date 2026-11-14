/**
 * Protocole companion MeshCore : cadrage et le strict minimum de commandes.
 *
 * **Tout ce qui est ici est relevé dans la bibliothèque Python `meshcore`** (MIT) dont dépend
 * déjà `meshcore-bridge` — `reader.py`, `packets.py`, `commands/messaging.py`, `commands/base.py`.
 * Rien n'est deviné, rien ne vient d'une documentation de seconde main. C'est ce qui permet
 * d'écrire ce client sans radio sous la main et de le tester sur des vecteurs.
 *
 * **Portée volontairement minuscule.** Un relais a besoin de quatre choses : s'annoncer,
 * relever les messages en attente, en envoyer un, et lister les contacts. Tout le reste —
 * canaux, télémétrie, administration de répéteurs — reste au pont Python. Ce n'est pas une
 * réimplémentation du protocole, c'est le strict nécessaire d'un relais.
 *
 * **Aucune cryptographie ici, et c'est normal** : c'est la radio qui chiffre. Le lien série
 * transporte du clair — voir l'avertissement de la page de relais.
 */

/** Début de trame sur le lien série, puis deux octets de longueur en little-endian. */
export const DEBUT_TRAME = 0x3e;

/** Commandes (meshcore/packets.py, CommandType). */
export const CMD = {
  APP_START: 1,
  SEND_TXT_MSG: 2,
  GET_CONTACTS: 4,
  SYNC_NEXT_MESSAGE: 10,
} as const;

/** Réponses et notifications (meshcore/packets.py, PacketType). */
export const REP = {
  OK: 0,
  ERROR: 1,
  CONTACT_START: 2,
  CONTACT: 3,
  CONTACT_END: 4,
  SELF_INFO: 5,
  MSG_SENT: 6,
  CONTACT_MSG_RECV: 7,
  NO_MORE_MSGS: 10,
  CONTACT_MSG_RECV_V3: 16,
  MESSAGES_WAITING: 0x83,
} as const;

/** Un message direct reçu, tel qu'un relais a besoin de le connaître. */
export interface MessageRecu {
  pubkeyPrefix: string;
  texte: string;
  horodatageExpediteur: number;
}

/**
 * Découpe un flux d'octets en trames complètes.
 *
 * Conscient des trames, **aveugle au contenu** : il ne fait que rendre des charges utiles. Et
 * il conserve le reliquat, parce qu'une lecture série coupe une trame n'importe où — c'est la
 * première chose qui casse quand on l'oublie.
 *
 * Resynchronisation : tout octet qui n'est pas `0x3e` avant un début de trame est jeté. C'est
 * exactement ce que fait `reader.py`, et c'est à cela que sert l'octet de début — un
 * branchement à chaud ou une reconnexion laisse du bruit sur le fil.
 */
export class DecoupeurDeTrames {
  private reliquat = new Uint8Array(0);

  pousser(octets: Uint8Array): Uint8Array[] {
    const mis = new Uint8Array(this.reliquat.length + octets.length);
    mis.set(this.reliquat, 0);
    mis.set(octets, this.reliquat.length);

    const trames: Uint8Array[] = [];
    let i = 0;
    for (;;) {
      while (i < mis.length && mis[i] !== DEBUT_TRAME) { i++; }
      if (mis.length - i < 3) { break; }
      const taille = mis[i + 1] | (mis[i + 2] << 8);
      if (mis.length - i - 3 < taille) { break; }
      trames.push(mis.slice(i + 3, i + 3 + taille));
      i += 3 + taille;
    }
    this.reliquat = mis.slice(i);
    return trames;
  }

  /** Vide le reliquat. À appeler à la reconnexion : une demi-trame d'avant n'a plus de sens. */
  reinitialiser(): void {
    this.reliquat = new Uint8Array(0);
  }
}

/** Habille une charge utile de son cadrage série. */
export function encadrer(charge: Uint8Array): Uint8Array {
  const trame = new Uint8Array(3 + charge.length);
  trame[0] = DEBUT_TRAME;
  trame[1] = charge.length & 0xff;
  trame[2] = (charge.length >> 8) & 0xff;
  trame.set(charge, 3);
  return trame;
}

export function commandeSimple(code: number): Uint8Array {
  return new Uint8Array([code]);
}

/**
 * `SEND_TXT_MSG` — relevé dans `commands/messaging.py::send_msg` :
 * `0x02 0x00 | tentative(1) | horodatage(4, LE) | destination(6) | texte utf-8`.
 *
 * La destination est le **préfixe de 6 octets** de la clé publique du contact
 * (`commands/base.py::_validate_destination`, `prefix_length=6`), pas la clé entière.
 */
export function commandeEnvoiMessage(
  pubkeyHex: string, texte: string, horodatage = Math.floor(Date.now() / 1000),
): Uint8Array {
  const destination = hexVersOctets(pubkeyHex).slice(0, 6);
  if (destination.length < 6) {
    throw new Error('Clé publique du destinataire trop courte : 6 octets au minimum.');
  }
  const corps = new TextEncoder().encode(texte);
  const charge = new Uint8Array(2 + 1 + 4 + 6 + corps.length);
  charge[0] = CMD.SEND_TXT_MSG;
  charge[1] = 0;                      // TxtType.PLAIN
  charge[2] = 0;                      // première et unique tentative
  new DataView(charge.buffer).setUint32(3, horodatage, true);
  charge.set(destination, 7);
  charge.set(corps, 13);
  return charge;
}

/**
 * Lit un message direct reçu. Gère les deux formats, et la différence n'est pas cosmétique :
 * `CONTACT_MSG_RECV_V3` (firmware >= 3) préfixe trois octets — SNR puis deux réservés — avant
 * le préfixe de clé publique. Les confondre décale tout le reste de la trame.
 */
export function lireMessageRecu(charge: Uint8Array): MessageRecu | null {
  const type = charge[0];
  if (type !== REP.CONTACT_MSG_RECV && type !== REP.CONTACT_MSG_RECV_V3) { return null; }
  let i = 1;
  if (type === REP.CONTACT_MSG_RECV_V3) { i += 3; }   // SNR (1) + réservé (2)

  if (charge.length < i + 12) { return null; }
  const pubkeyPrefix = octetsVersHex(charge.slice(i, i + 6));
  i += 6;
  i += 1;                                              // longueur/mode de chemin
  const txtType = charge[i]; i += 1;
  const horodatageExpediteur = new DataView(
    charge.buffer, charge.byteOffset + i, 4).getUint32(0, true);
  i += 4;
  if (txtType === 2) { i += 4; }                       // signature
  return {
    pubkeyPrefix,
    horodatageExpediteur,
    texte: new TextDecoder('utf-8').decode(charge.slice(i)),
  };
}

export function hexVersOctets(hex: string): Uint8Array {
  const propre = (hex || '').replace(/[^0-9a-fA-F]/g, '');
  const octets = new Uint8Array(Math.floor(propre.length / 2));
  for (let i = 0; i < octets.length; i++) {
    octets[i] = parseInt(propre.substr(i * 2, 2), 16);
  }
  return octets;
}

export function octetsVersHex(octets: Uint8Array): string {
  return Array.from(octets).map(o => o.toString(16).padStart(2, '0')).join('');
}
