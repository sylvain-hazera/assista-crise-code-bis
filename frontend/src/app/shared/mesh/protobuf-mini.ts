/**
 * Le strict minimum de l'encodage protobuf, pour parler à une radio Meshtastic.
 *
 * Pourquoi pas `@bufbuild/protobuf` ou `@meshtastic/protobufs` : une dépendance et un schéma
 * entier pour lire une dizaine de champs. Ce qui est ici tient en une page, se relit, et — c'est
 * le point — **est vérifié octet pour octet contre la bibliothèque protobuf officielle** (voir
 * `meshtastic-trames.spec.ts`, dont les vecteurs sont produits par `mesh_pb2` dans l'image du
 * pont Meshtastic).
 *
 * Trois types de fil suffisent : varint (0), 64 bits (1, sauté), longueur préfixée (2) et
 * 32 bits fixes (5). Les nombres sont manipulés en `number` : les champs utiles (numéros de
 * nœud, identifiants) tiennent sur 32 bits non signés, soit bien moins que 2^53.
 */

export const FIL = { VARINT: 0, I64: 1, LONGUEUR: 2, I32: 5 } as const;

// ══ Écriture ═════════════════════════════════════════════════════════════════

export class EcrivainProtobuf {
  private octets: number[] = [];

  private varintBrut(valeur: number): void {
    // Division plutôt que décalages : `>>>` tronque à 32 bits signés en JavaScript.
    let v = Math.floor(valeur);
    while (v >= 0x80) {
      this.octets.push((v % 0x80) | 0x80);
      v = Math.floor(v / 0x80);
    }
    this.octets.push(v);
  }

  private cle(numero: number, fil: number): void {
    this.varintBrut(numero * 8 + fil);
  }

  /** uint32 / bool / enum. Une valeur nulle n'est pas écrite (proto3), comme la bibliothèque. */
  varint(numero: number, valeur: number | boolean): this {
    const v = typeof valeur === 'boolean' ? (valeur ? 1 : 0) : valeur;
    if (!v) { return this; }
    this.cle(numero, FIL.VARINT);
    this.varintBrut(v);
    return this;
  }

  /** fixed32, petit-boutiste. */
  fixed32(numero: number, valeur: number): this {
    if (!valeur) { return this; }
    this.cle(numero, FIL.I32);
    const v = valeur >>> 0;
    this.octets.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff);
    return this;
  }

  octetsBruts(numero: number, valeur: Uint8Array): this {
    if (!valeur.length) { return this; }
    this.cle(numero, FIL.LONGUEUR);
    this.varintBrut(valeur.length);
    for (const o of valeur) { this.octets.push(o); }
    return this;
  }

  /**
   * Sous-message. **Écrit même vide** : `ToRadio{heartbeat: Heartbeat{}}` doit produire
   * `3a 00`, sinon la radio reçoit un ToRadio sans rien dedans.
   */
  message(numero: number, sous: EcrivainProtobuf): this {
    const contenu = sous.fin();
    this.cle(numero, FIL.LONGUEUR);
    this.varintBrut(contenu.length);
    for (const o of contenu) { this.octets.push(o); }
    return this;
  }

  fin(): Uint8Array {
    return Uint8Array.from(this.octets);
  }
}

// ══ Lecture ══════════════════════════════════════════════════════════════════

export interface ChampProtobuf {
  numero: number;
  fil: number;
  /** varint et fixed32 */
  nombre?: number;
  /** longueur préfixée : sous-message, octets ou chaîne */
  octets?: Uint8Array;
}

/**
 * Lit tous les champs d'un message, **sans schéma**. L'appelant prend ceux qu'il connaît et
 * ignore les autres — c'est ce qui rend ce lecteur tolérant aux évolutions du firmware, qui
 * ajoute régulièrement des champs.
 *
 * Lève une erreur sur un message tronqué ou un type de fil inconnu : mieux vaut écarter une
 * trame corrompue que d'en tirer un numéro de nœud faux.
 */
export function lireChamps(octets: Uint8Array): ChampProtobuf[] {
  const champs: ChampProtobuf[] = [];
  let i = 0;

  const varint = (): number => {
    let resultat = 0;
    let facteur = 1;
    for (let n = 0; n < 10; n++) {
      if (i >= octets.length) { throw new Error('protobuf tronqué'); }
      const o = octets[i++];
      // Au-delà de 2^53 la valeur perd sa précision ; aucun champ que nous LISONS n'y monte,
      // mais il faut quand même consommer les 10 octets d'un int32 négatif (rx_rssi).
      resultat += (o & 0x7f) * facteur;
      facteur *= 0x80;
      if (!(o & 0x80)) { return resultat; }
    }
    throw new Error('varint trop long');
  };

  while (i < octets.length) {
    const cle = varint();
    const numero = Math.floor(cle / 8);
    const fil = cle % 8;
    if (fil === FIL.VARINT) {
      champs.push({ numero, fil, nombre: varint() });
    } else if (fil === FIL.I32) {
      if (i + 4 > octets.length) { throw new Error('protobuf tronqué'); }
      const v = (octets[i] | (octets[i + 1] << 8) | (octets[i + 2] << 16)
                 | (octets[i + 3] << 24)) >>> 0;
      i += 4;
      champs.push({ numero, fil, nombre: v });
    } else if (fil === FIL.I64) {
      if (i + 8 > octets.length) { throw new Error('protobuf tronqué'); }
      i += 8;
    } else if (fil === FIL.LONGUEUR) {
      const n = varint();
      if (i + n > octets.length) { throw new Error('protobuf tronqué'); }
      champs.push({ numero, fil, octets: octets.slice(i, i + n) });
      i += n;
    } else {
      throw new Error(`type de fil protobuf inconnu : ${fil}`);
    }
  }
  return champs;
}

/** Le premier champ portant ce numéro, ou undefined. */
export function champ(champs: ChampProtobuf[], numero: number): ChampProtobuf | undefined {
  return champs.find(c => c.numero === numero);
}

export function texte(octets: Uint8Array | undefined): string {
  return octets ? new TextDecoder('utf-8').decode(octets) : '';
}
