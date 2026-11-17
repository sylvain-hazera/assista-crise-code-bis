/**
 * Une petite file d'attente gardée dans le navigateur, **chiffrée**.
 *
 * Sert aux réponses de terrain saisies sans réseau : elles doivent survivre à la fermeture de
 * l'onglet, mais elles parlent de personnes et de logements — on ne les pose pas en clair sur
 * un téléphone (règle du projet : rien en clair).
 *
 * La clé AES-GCM est créée dans le navigateur, **non extractible**, et rangée dans IndexedDB
 * à côté des données : le code de la page peut s'en servir, mais ni lui ni une copie du
 * stockage ne peuvent la lire. Cela protège d'une lecture du disque ou d'une sauvegarde du
 * profil, pas d'une personne qui tient l'appareil déverrouillé et ouvre l'application.
 */
const BASE = 'assista-crise-terrain';
const MAGASIN = 'file';
const CLE_ID = '__cle__';

function ouvrir(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const demande = indexedDB.open(BASE, 1);
    demande.onupgradeneeded = () => demande.result.createObjectStore(MAGASIN);
    demande.onsuccess = () => resolve(demande.result);
    demande.onerror = () => reject(demande.error);
  });
}

function requete<T>(base: IDBDatabase, mode: IDBTransactionMode, faire: (m: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const demande = faire(base.transaction(MAGASIN, mode).objectStore(MAGASIN));
    demande.onsuccess = () => resolve(demande.result);
    demande.onerror = () => reject(demande.error);
  });
}

async function cle(base: IDBDatabase): Promise<CryptoKey> {
  const existante = await requete<CryptoKey | undefined>(base, 'readonly', m => m.get(CLE_ID));
  if (existante) return existante;
  const neuve = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  await requete(base, 'readwrite', m => m.put(neuve, CLE_ID));
  return neuve;
}

/** Range `valeur` sous `identifiant`, chiffrée. */
export async function deposer(identifiant: string, valeur: unknown): Promise<void> {
  const base = await ouvrir();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const clair = new TextEncoder().encode(JSON.stringify(valeur));
  const chiffre = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await cle(base), clair);
  await requete(base, 'readwrite', m => m.put({ iv, chiffre }, identifiant));
  base.close();
}

/** Tout ce qui attend, déchiffré. Une entrée illisible est ignorée, jamais fatale. */
export async function relever<T>(): Promise<{ identifiant: string; valeur: T }[]> {
  const base = await ouvrir();
  const identifiants = (await requete<IDBValidKey[]>(base, 'readonly', m => m.getAllKeys()))
    .map(String).filter(i => i !== CLE_ID);
  const secret = await cle(base);
  const resultat: { identifiant: string; valeur: T }[] = [];
  for (const identifiant of identifiants) {
    try {
      const entree = await requete<{ iv: Uint8Array<ArrayBuffer>; chiffre: ArrayBuffer }>(base, 'readonly', m => m.get(identifiant));
      const clair = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: entree.iv }, secret, entree.chiffre);
      resultat.push({ identifiant, valeur: JSON.parse(new TextDecoder().decode(clair)) as T });
    } catch {
      // Clé perdue ou entrée abîmée : on ne bloque pas les autres.
    }
  }
  base.close();
  return resultat;
}

export async function retirer(identifiant: string): Promise<void> {
  const base = await ouvrir();
  await requete(base, 'readwrite', m => m.delete(identifiant));
  base.close();
}
