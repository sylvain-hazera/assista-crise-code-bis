/**
 * Proposition de plan de canaux au branchement d'une radio Meshtastic.
 *
 * Règle fixée par Sylvain le 14/11/2026 (voir backend/core/canaux_locaux.py) : on lit les
 * emplacements de la radio ; on propose d'ajouter `Fr_Balise` puis `Fr_EMCOM` s'ils manquent ;
 * on regarde combien d'emplacements restent ; on propose d'y mettre le canal de la crise et
 * celui de la commune, en proposant d'en supprimer d'autres s'il n'y a pas la place.
 *
 * Fonction pure : elle ne touche ni à la radio ni au serveur, elle ne fait que proposer. Rien
 * n'est écrit sans l'accord de la personne.
 */
import { EmplacementCanal } from './pilotes';
import { EMPLACEMENTS, ROLE_CANAL } from './meshtastic-trames';

/** Une entrée du plan servi par le serveur (`/relais-serie/plan-canaux/`). */
export interface EntreePlan {
  nom: string;
  psk_hex: string;
  role: 'communautaire' | 'crise' | 'commune';
  libelle: string;
  canal: string | null;
  public: boolean;
  /** Faux pour un canal communautaire dont Assista-Crise ne connaît pas la clé. */
  disponible: boolean;
}

export interface AjoutPropose {
  entree: EntreePlan;
  /** Emplacement libre attribué, ou null s'il faut d'abord en libérer un. */
  index: number | null;
}

export interface PropositionPlan {
  /** Entrées du plan déjà présentes sur la radio (même nom). */
  presents: { entree: EntreePlan; index: number }[];
  /** Entrées à ajouter, dans l'ordre de priorité du plan. */
  ajouts: AjoutPropose[];
  /** Entrées qu'on ne peut pas pousser (clé inconnue d'Assista-Crise). */
  indisponibles: EntreePlan[];
  /** Emplacements libres (hors primaire). */
  libres: number[];
  /** Combien d'emplacements il faudrait libérer pour tout ajouter. */
  manque: number;
  /** Ce qu'on peut proposer de supprimer : canaux secondaires étrangers au plan. Jamais le
   * primaire, jamais un canal du plan. */
  supprimables: EmplacementCanal[];
}

const memeNom = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

export function proposerPlan(emplacements: EmplacementCanal[], plan: EntreePlan[],
                             total = EMPLACEMENTS): PropositionPlan {
  const actifs = emplacements.filter(e => e.role !== ROLE_CANAL.DESACTIVE);
  const presents: { entree: EntreePlan; index: number }[] = [];
  const manquants: EntreePlan[] = [];
  const indisponibles: EntreePlan[] = [];

  for (const entree of plan) {
    const trouve = actifs.find(e => e.nom && memeNom(e.nom, entree.nom));
    if (trouve) {
      presents.push({ entree, index: trouve.index });
    } else if (!entree.disponible) {
      indisponibles.push(entree);
    } else {
      manquants.push(entree);
    }
  }

  // Emplacements libres : désactivés ou jamais décrits par la radio, primaire exclu — on
  // n'écrase jamais le canal par défaut de la radio.
  const occupes = new Set(actifs.map(e => e.index));
  const libres: number[] = [];
  for (let i = 1; i < total; i++) {
    if (!occupes.has(i)) { libres.push(i); }
  }

  const ajouts: AjoutPropose[] = manquants.map((entree, n) => ({
    entree, index: n < libres.length ? libres[n] : null,
  }));

  const nomsDuPlan = plan.map(e => e.nom);
  const supprimables = actifs.filter(e =>
    e.index !== 0 && e.role !== ROLE_CANAL.PRIMAIRE
    && !nomsDuPlan.some(n => e.nom && memeNom(n, e.nom)));

  return {
    presents, ajouts, indisponibles, libres,
    manque: Math.max(0, manquants.length - libres.length),
    supprimables,
  };
}

/**
 * Les opérations à exécuter, une fois la personne d'accord : d'abord les suppressions qu'elle a
 * cochées, puis les ajouts qu'elle a gardés, dans les emplacements libres puis libérés.
 * Renvoie aussi les ajouts qui ne trouvent toujours pas de place.
 */
export function operationsPlan(proposition: PropositionPlan, ajoutsRetenus: EntreePlan[],
                               aSupprimer: number[])
    : { supprimer: number[]; ecrire: { index: number; entree: EntreePlan }[];
        sansPlace: EntreePlan[] } {
  const places = [...proposition.libres, ...aSupprimer.filter(i => i !== 0)]
    .filter((v, i, t) => t.indexOf(v) === i);
  const ecrire: { index: number; entree: EntreePlan }[] = [];
  const sansPlace: EntreePlan[] = [];
  for (const entree of ajoutsRetenus) {
    const index = places.shift();
    if (index === undefined) { sansPlace.push(entree); } else { ecrire.push({ index, entree }); }
  }
  return { supprimer: aSupprimer.filter(i => i !== 0), ecrire, sansPlace };
}
