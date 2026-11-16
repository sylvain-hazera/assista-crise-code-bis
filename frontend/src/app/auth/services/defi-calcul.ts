/** Le calcul que le serveur demande avant de créer un compte (voir core/defi_inscription.py
 * côté serveur) : retrouver le nombre dont l'empreinte SHA-256, précédée d'un sel, vaut celle
 * du défi, en essayant 0, 1, 2… jusqu'à `maximum`.
 *
 * SHA-256 est écrit ici plutôt que demandé au navigateur : `crypto.subtle.digest` rend une
 * promesse par appel, ce qui plafonne à quelques dizaines de milliers d'essais par seconde.
 * Cette version, synchrone, en fait plusieurs centaines de milliers — et c'est ce qui rend le
 * niveau ordinaire imperceptible sur un téléphone. */

export interface DefiInscription {
  sel: string;
  empreinte: string;
  maximum: number;
  emis: number;
  expire: number;
  niveau: string;
  signature: string;
}

export interface DefiResolu extends DefiInscription {
  nombre: number;
}

const K = new Int32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const W = new Int32Array(64);

/** Empreinte SHA-256 d'un message de 55 octets au plus (un seul bloc), rangée dans `sortie`
 * (huit mots de 32 bits). `bloc` fait 64 octets ; les `longueur` premiers portent le message. */
function sha256UnBloc(bloc: Uint8Array, longueur: number, sortie: Int32Array): void {
  bloc[longueur] = 0x80;
  for (let i = longueur + 1; i < 62; i++) bloc[i] = 0;
  bloc[62] = (longueur * 8) >>> 8;
  bloc[63] = (longueur * 8) & 0xff;

  for (let i = 0; i < 16; i++) {
    const j = i * 4;
    W[i] = (bloc[j] << 24) | (bloc[j + 1] << 16) | (bloc[j + 2] << 8) | bloc[j + 3];
  }
  for (let i = 16; i < 64; i++) {
    const a = W[i - 15], b = W[i - 2];
    const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
    const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
    W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
  }

  let a = 0x6a09e667, b = 0xbb67ae85 | 0, c = 0x3c6ef372, d = 0xa54ff53a | 0;
  let e = 0x510e527f, f = 0x9b05688c | 0, g = 0x1f83d9ab, h = 0x5be0cd19;
  for (let i = 0; i < 64; i++) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
    const t1 = (h + S1 + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
    const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
    h = g; g = f; f = e; e = (d + t1) | 0;
    d = c; c = b; b = a; a = (t1 + t2) | 0;
  }
  sortie[0] = (a + 0x6a09e667) | 0; sortie[1] = (b + 0xbb67ae85) | 0;
  sortie[2] = (c + 0x3c6ef372) | 0; sortie[3] = (d + 0xa54ff53a) | 0;
  sortie[4] = (e + 0x510e527f) | 0; sortie[5] = (f + 0x9b05688c) | 0;
  sortie[6] = (g + 0x1f83d9ab) | 0; sortie[7] = (h + 0x5be0cd19) | 0;
}

/** SHA-256 en hexadécimal d'un texte court (55 octets au plus). Sert aux tests et au contrôle. */
export function sha256Hex(texte: string): string {
  const octets = new TextEncoder().encode(texte);
  if (octets.length > 55) throw new Error('texte trop long pour un seul bloc');
  const bloc = new Uint8Array(64);
  bloc.set(octets);
  const mots = new Int32Array(8);
  sha256UnBloc(bloc, octets.length, mots);
  return Array.from(mots, (m) => (m >>> 0).toString(16).padStart(8, '0')).join('');
}

/** Rend la main au navigateur (affichage, saisie) entre deux tranches de calcul.
 *
 * Par un message et non par `setTimeout` : dans un onglet passé à l'arrière-plan, les
 * minuteries sont ralenties à une par seconde, et le calcul le plus long — une centaine de
 * tranches — durerait alors plusieurs minutes pour quelqu'un qui a changé d'application en
 * attendant. */
function pause(): Promise<void> {
  return new Promise<void>((suite) => {
    if (typeof MessageChannel === 'undefined') { setTimeout(suite, 0); return; }
    const canal = new MessageChannel();
    canal.port1.onmessage = () => { canal.port1.close(); suite(); };
    canal.port2.postMessage(0);
  });
}

/** Cherche le nombre du défi. Rend la main à l'affichage toutes les `tranche` valeurs, pour
 * que la page reste fluide pendant le calcul (la personne continue de remplir le formulaire).
 * `null` si aucune valeur ne convient — un défi mal formé, jamais un défi du serveur. */
export async function resoudreDefi(defi: DefiInscription, tranche = 20_000): Promise<number | null> {
  const sel = new TextEncoder().encode(defi.sel);
  if (sel.length > 40 || !/^[0-9a-f]{64}$/.test(defi.empreinte)) return null;

  const cible = new Int32Array(8);
  for (let i = 0; i < 8; i++) cible[i] = parseInt(defi.empreinte.slice(i * 8, i * 8 + 8), 16) | 0;

  const bloc = new Uint8Array(64);
  bloc.set(sel);
  const mots = new Int32Array(8);
  const chiffres = new Uint8Array(12);

  for (let nombre = 0; nombre <= defi.maximum; nombre++) {
    // Écrit `nombre` en chiffres décimaux à la suite du sel.
    let n = nombre, k = 0;
    do { chiffres[k++] = 48 + (n % 10); n = (n / 10) | 0; } while (n > 0);
    for (let i = 0; i < k; i++) bloc[sel.length + i] = chiffres[k - 1 - i];

    sha256UnBloc(bloc, sel.length + k, mots);
    if (mots[0] === cible[0] && mots[1] === cible[1] && mots[2] === cible[2] && mots[3] === cible[3]
        && mots[4] === cible[4] && mots[5] === cible[5] && mots[6] === cible[6] && mots[7] === cible[7]) {
      return nombre;
    }
    if (nombre % tranche === tranche - 1) await pause();
  }
  return null;
}
