/** Signature d'une version de satellite DANS LE NAVIGATEUR (15/11/2026).
 *
 * Le serveur remet à l'administrateur la clé de signature « emballée » — chiffrée avec sa
 * phrase de passe. Ce module la déballe avec la phrase tapée dans la page, signe le numéro de
 * version, et rend le bloc de signature. **La phrase de passe et la clé en clair ne quittent
 * jamais le navigateur** : seuls le numéro de version et sa signature partent vers le serveur,
 * qui les vérifie comme avant.
 *
 * Tout repose sur ce que le navigateur sait faire nativement (WebCrypto) : PBKDF2, AES-GCM,
 * SHA-512, Ed25519. Aucune bibliothèque de chiffrement n'est embarquée — moins il y a de code
 * autour d'une clé, mieux elle est gardée.
 *
 * Le bloc produit est celui de `ssh-keygen -Y sign`, à l'octet près : un satellite le vérifie
 * avec `ssh-keygen`, il ne doit voir aucune différence. Le test le compare à une vraie sortie
 * d'OpenSSH (voir backend/core/signature_satellites.py pour le format et le pourquoi). */

export interface CleEmballee {
  version: number;
  derivation: string;
  iterations: number;
  sel: string;
  vecteur: string;
  chiffre: string;
  cle_publique: string;
}

/** Identiques à backend/core/signature_satellites.py. */
const ESPACE_DE_NOMS = 'assista-crise-satellite';
const CONTEXTE_EMBALLAGE = 'assista-crise-satellite/cle-web/v1';

export class PhraseIncorrecte extends Error {
  constructor() { super('Phrase de passe incorrecte.'); }
}

export class NavigateurInsuffisant extends Error {
  constructor() {
    super('Ce navigateur ne sait pas signer (Ed25519) : mettez-le à jour, ou signez depuis un terminal.');
  }
}

const texte = new TextEncoder();

function depuisBase64(valeur: string): Uint8Array {
  const binaire = atob(valeur);
  const octets = new Uint8Array(binaire.length);
  for (let i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
  return octets;
}

function versBase64(octets: Uint8Array): string {
  let binaire = '';
  for (const octet of octets) binaire += String.fromCharCode(octet);
  return btoa(binaire);
}

/** Copie dans un tampon neuf : c'est ce type-là que WebCrypto accepte quelle que soit la
 * version de TypeScript. */
function tampon(octets: Uint8Array): ArrayBuffer {
  const copie = new ArrayBuffer(octets.length);
  new Uint8Array(copie).set(octets);
  return copie;
}

function coller(...morceaux: Uint8Array[]): Uint8Array {
  const resultat = new Uint8Array(morceaux.reduce((total, m) => total + m.length, 0));
  let position = 0;
  for (const morceau of morceaux) { resultat.set(morceau, position); position += morceau.length; }
  return resultat;
}

/** Chaîne au format SSH : longueur sur quatre octets, puis le contenu. */
function chaine(contenu: Uint8Array | string): Uint8Array {
  const octets = typeof contenu === 'string' ? texte.encode(contenu) : contenu;
  const longueur = new Uint8Array(4);
  new DataView(longueur.buffer).setUint32(0, octets.length);
  return coller(longueur, octets);
}

/** Vrai si ce navigateur sait signer en Ed25519 (Chrome 137+, Firefox 129+, Safari 17+). */
export async function navigateurSaitSigner(): Promise<boolean> {
  try {
    await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
    return true;
  } catch {
    return false;
  }
}

/** Déballe la clé avec la phrase de passe. La clé rendue n'est pas extractible : même un
 * script de la page ne peut plus en lire les octets, seulement lui faire signer. */
async function deballer(emballage: CleEmballee, phrase: string): Promise<CryptoKey> {
  if (emballage.version !== 1 || emballage.derivation !== 'PBKDF2-SHA256') {
    throw new Error('Clé emballée dans un format que cette page ne connaît pas : rechargez la page.');
  }
  const base = await crypto.subtle.importKey('raw', tampon(texte.encode(phrase)), 'PBKDF2', false, ['deriveKey']);
  const cleEmballage = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: tampon(depuisBase64(emballage.sel)), iterations: emballage.iterations },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  let pkcs8: ArrayBuffer;
  try {
    pkcs8 = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: tampon(depuisBase64(emballage.vecteur)), additionalData: tampon(texte.encode(CONTEXTE_EMBALLAGE)) },
      cleEmballage, tampon(depuisBase64(emballage.chiffre)));
  } catch {
    // AES-GCM authentifie : un échec de déchiffrement, c'est une phrase fausse.
    throw new PhraseIncorrecte();
  }
  try {
    return await crypto.subtle.importKey('pkcs8', pkcs8, { name: 'Ed25519' }, false, ['sign']);
  } catch {
    throw new NavigateurInsuffisant();
  } finally {
    new Uint8Array(pkcs8).fill(0);
  }
}

/** Signe `commit` (40 caractères hexadécimaux) et rend le bloc « BEGIN SSH SIGNATURE ». */
export async function signerVersion(emballage: CleEmballee, phrase: string, commit: string): Promise<string> {
  if (!/^[0-9a-f]{40}$/.test(commit)) throw new Error('Numéro de version incomplet.');
  const cle = await deballer(emballage, phrase);

  const message = texte.encode(`${ESPACE_DE_NOMS}/v1\ncommit=${commit}\n`);
  const empreinte = new Uint8Array(await crypto.subtle.digest('SHA-512', tampon(message)));
  const magie = texte.encode('SSHSIG');
  const aSigner = coller(magie, chaine(ESPACE_DE_NOMS), chaine(''), chaine('sha512'), chaine(empreinte));
  const signature = new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, cle, tampon(aSigner)));

  const version = new Uint8Array([0, 0, 0, 1]);
  const bloc = coller(
    magie, version,
    chaine(coller(chaine('ssh-ed25519'), chaine(depuisBase64(emballage.cle_publique)))),
    chaine(ESPACE_DE_NOMS), chaine(''), chaine('sha512'),
    chaine(coller(chaine('ssh-ed25519'), chaine(signature))),
  );
  const lignes = versBase64(bloc).match(/.{1,70}/g) ?? [];
  return ['-----BEGIN SSH SIGNATURE-----', ...lignes, '-----END SSH SIGNATURE-----'].join('\n');
}
