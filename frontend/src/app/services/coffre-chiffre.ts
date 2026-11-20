/**
 * Un coffre chiffré dans le navigateur, un par usage (DOSSIER-PWA-INTERVENANTS.md, lot 3).
 *
 * Même principe que `file-attente-chiffree.ts` (règle du projet : rien en clair, y compris sur
 * le téléphone) : une clé AES-GCM créée dans le navigateur, NON EXTRACTIBLE, rangée dans la même
 * base IndexedDB que les données. Le code de la page peut s'en servir, mais ni lui ni une copie du
 * stockage ne peuvent la lire : cela protège d'une lecture du disque ou d'une sauvegarde, pas
 * d'une personne qui tient l'appareil déverrouillé et ouvre l'application.
 *
 * Une base par usage : les copies hors ligne et la file des envois ne se mélangent pas, ni avec
 * la file des formulaires de terrain, qui relit toute la sienne.
 */
const MAGASIN = 'coffre';
const CLE_ID = '__cle__';

export interface EntreeCoffre<T> { identifiant: string; valeur: T; }

export class CoffreChiffre {
  constructor(private readonly base: string) {}

  private ouvrir(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const demande = indexedDB.open(this.base, 1);
      demande.onupgradeneeded = () => demande.result.createObjectStore(MAGASIN);
      demande.onsuccess = () => resolve(demande.result);
      demande.onerror = () => reject(demande.error);
    });
  }

  private requete<T>(base: IDBDatabase, mode: IDBTransactionMode, faire: (m: IDBObjectStore) => IDBRequest<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      const demande = faire(base.transaction(MAGASIN, mode).objectStore(MAGASIN));
      demande.onsuccess = () => resolve(demande.result);
      demande.onerror = () => reject(demande.error);
    });
  }

  private async cle(base: IDBDatabase): Promise<CryptoKey> {
    const existante = await this.requete<CryptoKey | undefined>(base, 'readonly', m => m.get(CLE_ID));
    if (existante) return existante;
    const neuve = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    await this.requete(base, 'readwrite', m => m.put(neuve, CLE_ID));
    return neuve;
  }

  /** Range `valeur` sous `identifiant`, chiffrée (remplace l'ancienne). */
  async deposer(identifiant: string, valeur: unknown): Promise<void> {
    const base = await this.ouvrir();
    try {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const clair = new TextEncoder().encode(JSON.stringify(valeur));
      const chiffre = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await this.cle(base), clair);
      await this.requete(base, 'readwrite', m => m.put({ iv, chiffre }, identifiant));
    } finally {
      base.close();
    }
  }

  /** La valeur rangée sous `identifiant`, déchiffrée ; null si absente ou illisible. */
  async lire<T>(identifiant: string): Promise<T | null> {
    const base = await this.ouvrir();
    try {
      const entree = await this.requete<{ iv: Uint8Array<ArrayBuffer>; chiffre: ArrayBuffer } | undefined>(
        base, 'readonly', m => m.get(identifiant));
      if (!entree) return null;
      const clair = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: entree.iv }, await this.cle(base), entree.chiffre);
      return JSON.parse(new TextDecoder().decode(clair)) as T;
    } catch {
      return null;
    } finally {
      base.close();
    }
  }

  /** Tout le contenu, déchiffré. Une entrée illisible est ignorée, jamais fatale. */
  async tout<T>(): Promise<EntreeCoffre<T>[]> {
    const base = await this.ouvrir();
    const identifiants = (await this.requete<IDBValidKey[]>(base, 'readonly', m => m.getAllKeys()))
      .map(String).filter(i => i !== CLE_ID);
    base.close();
    const resultat: EntreeCoffre<T>[] = [];
    for (const identifiant of identifiants) {
      const valeur = await this.lire<T>(identifiant);
      if (valeur !== null) resultat.push({ identifiant, valeur });
    }
    return resultat;
  }

  async retirer(identifiant: string): Promise<void> {
    const base = await this.ouvrir();
    try {
      await this.requete(base, 'readwrite', m => m.delete(identifiant));
    } finally {
      base.close();
    }
  }

  /** Efface tout, clé comprise : à la déconnexion, rien ne reste pour la personne suivante. */
  vider(): Promise<void> {
    return new Promise((resolve) => {
      const demande = indexedDB.deleteDatabase(this.base);
      demande.onsuccess = demande.onerror = demande.onblocked = () => resolve();
    });
  }
}
