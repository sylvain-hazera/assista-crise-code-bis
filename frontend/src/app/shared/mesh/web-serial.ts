/**
 * Le strict minimum de l'API Web Serial, décrit ici plutôt qu'importé.
 *
 * `SerialPort` n'existe pas dans les types standards de TypeScript, et le paquet
 * `@types/w3c-web-serial` ajouterait une dépendance pour une trentaine de lignes de
 * déclarations. On décrit donc ce que nous utilisons, et rien de plus : une surface réduite
 * est aussi une surface qu'on relit.
 *
 * Disponible sur **Chrome et Edge uniquement**, sur ordinateur ou Android, et seulement en
 * HTTPS ou sur localhost. Ni Firefox, ni Safari, ni iOS — d'où `serieDisponible()`, appelé
 * avant d'afficher quoi que ce soit.
 */

export interface PortSerie {
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readonly readable: ReadableStream<Uint8Array> | null;
  readonly writable: WritableStream<Uint8Array> | null;
}

interface ApiSerie {
  /** Exige un geste de l'utilisateur : aucune page ne choisit un port toute seule. */
  requestPort(): Promise<PortSerie>;
  /** Les ports DÉJÀ autorisés : c'est ce qui permet de reprendre après un débranchement
   * sans redemander à la personne de cliquer. */
  getPorts(): Promise<PortSerie[]>;
}

export function serieDisponible(): boolean {
  return typeof navigator !== 'undefined' && 'serial' in navigator;
}

export function apiSerie(): ApiSerie {
  const api = (navigator as unknown as { serial?: ApiSerie }).serial;
  if (!api) {
    throw new Error("Ce navigateur n'expose pas l'accès au port série.");
  }
  return api;
}

/** Verrou d'écran : demandé, jamais exigé. Tous les navigateurs ne l'ont pas, et un relais
 * doit fonctionner sans — l'écran dit de toute façon de ne pas fermer l'onglet. */
export interface VerrouEcran { release(): Promise<void>; }

export async function prendreVerrouEcran(): Promise<VerrouEcran | null> {
  try {
    const api = (navigator as unknown as {
      wakeLock?: { request(type: 'screen'): Promise<VerrouEcran> };
    }).wakeLock;
    return api ? await api.request('screen') : null;
  } catch {
    return null;
  }
}
