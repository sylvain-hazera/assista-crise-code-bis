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
 * Les ajouts cochés d'office : autant qu'il y a d'emplacements LIBRES, jamais plus — rien n'est
 * retiré de la radio sans que la personne le décide. Le canal de la commune d'abord (il dure
 * au-delà de chaque crise), puis les crises dans l'ordre du serveur (les plus récentes
 * d'abord). Les autres restent proposés, décochés (revue du 19/11/2026 : 9 canaux cochés pour
 * 6 places, et la commune abandonnée en dernier).
 */
export function ajoutsParDefaut(proposition: PropositionPlan): string[] {
  const parPriorite = [...proposition.ajouts].sort((a, b) =>
    Number(b.entree.role === 'commune') - Number(a.entree.role === 'commune'));
  return parPriorite.slice(0, proposition.libres.length).map(a => a.entree.nom);
}

/** Combien d'ajouts retenus ne tiendront pas, même en libérant tout ce qui peut l'être. */
export function ajoutsSansPlacePossible(proposition: PropositionPlan, retenus: number): number {
  return Math.max(0, retenus - proposition.libres.length - proposition.supprimables.length);
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

// ══ Emplacement par emplacement (19/11/2026) ════════════════════════════════
//
// Demande de Sylvain : « proposer 2 choses : une forme de mapping (translate), et supprimer tel
// canal pour mettre tel canal ». Un choix par emplacement de la radio :
// - garder          : rien ne change ;
// - relier          : le canal présent EST tel canal d'Assista-Crise (correspondance enregistrée
//                     sur le serveur, la radio n'est pas réécrite) ;
// - remplacer       : tel canal est supprimé pour mettre tel canal, dans CET emplacement ;
// - vider           : le canal est supprimé ;
// - ajouter         : un emplacement libre reçoit tel canal.

export type ActionEmplacement = 'garder' | 'relier' | 'remplacer' | 'vider' | 'ajouter';

export interface ChoixEmplacement {
  index: number;
  action: ActionEmplacement;
  /** Nom de l'entrée du plan visée (relier, remplacer, ajouter). */
  cible: string | null;
}

export interface OperationsChoix {
  supprimer: number[];
  ecrire: { index: number; entree: EntreePlan }[];
  /** nom du canal sur la radio (minuscules) → identifiant du canal d'Assista-Crise. */
  correspondances: Record<string, string>;
  /** Ce qui empêche d'appliquer : à corriger avant. */
  erreurs: string[];
}

const occupe = (e: EmplacementCanal | undefined) => !!e && e.role !== ROLE_CANAL.DESACTIVE;

/**
 * Le choix proposé d'office : garder ce qui est occupé (relié s'il l'était déjà), et remplir les
 * emplacements libres avec ce qui tient (ajoutsParDefaut). Rien n'est retiré d'office.
 */
export function choixParDefaut(emplacements: EmplacementCanal[], proposition: PropositionPlan,
                               plan: EntreePlan[], correspondances: Record<string, string> = {},
                               total = EMPLACEMENTS): ChoixEmplacement[] {
  const aPlacer = ajoutsParDefaut(proposition);
  const choix: ChoixEmplacement[] = [];
  for (let index = 0; index < total; index++) {
    const e = emplacements.find(x => x.index === index);
    if (occupe(e)) {
      const relie = e!.nom ? correspondances[e!.nom.trim().toLowerCase()] : undefined;
      const entree = relie ? plan.find(p => p.canal === relie) : undefined;
      choix.push(entree ? { index, action: 'relier', cible: entree.nom } : { index, action: 'garder', cible: null });
    } else if (index !== 0 && aPlacer.length) {
      choix.push({ index, action: 'ajouter', cible: aPlacer.shift()! });
    } else {
      choix.push({ index, action: 'garder', cible: null });
    }
  }
  return choix;
}

/** Les opérations que ces choix demandent, et ce qui empêche de les appliquer. */
export function operationsChoix(emplacements: EmplacementCanal[], choix: ChoixEmplacement[],
                                plan: EntreePlan[]): OperationsChoix {
  const ops: OperationsChoix = { supprimer: [], ecrire: [], correspondances: {}, erreurs: [] };
  const parNom = (nom: string | null) => (nom ? plan.find(p => memeNom(p.nom, nom)) : undefined);
  // Où chaque canal d'Assista-Crise se retrouvera : une seule place par canal.
  const places = new Map<string, number[]>();
  const placer = (entree: EntreePlan, index: number) =>
    places.set(entree.nom.toLowerCase(), [...(places.get(entree.nom.toLowerCase()) ?? []), index]);

  for (const c of choix) {
    const e = emplacements.find(x => x.index === c.index);
    const nomRadio = occupe(e) ? (e!.nom || '').trim() : '';
    const entree = parNom(c.cible);
    switch (c.action) {
      case 'garder': {
        const deja = nomRadio ? parNom(nomRadio) : undefined;
        if (deja) { placer(deja, c.index); }
        break;
      }
      case 'relier':
        if (!nomRadio) { ops.erreurs.push(`Emplacement ${c.index} : un canal sans nom ne peut pas être relié.`); break; }
        if (!entree?.canal) { ops.erreurs.push(`Emplacement ${c.index} : choisissez le canal d'Assista-Crise à relier.`); break; }
        ops.correspondances[nomRadio.toLowerCase()] = entree.canal;
        placer(entree, c.index);
        break;
      case 'remplacer':
      case 'ajouter':
        if (c.index === 0) { ops.erreurs.push('Le canal primaire (emplacement 0) ne se remplace pas d\'ici.'); break; }
        if (!entree) { ops.erreurs.push(`Emplacement ${c.index} : choisissez le canal à mettre.`); break; }
        if (!entree.disponible) { ops.erreurs.push(`« ${entree.nom} » : clé inconnue d'Assista-Crise, impossible à écrire.`); break; }
        ops.ecrire.push({ index: c.index, entree });
        placer(entree, c.index);
        break;
      case 'vider':
        if (c.index === 0) { ops.erreurs.push('Le canal primaire (emplacement 0) ne se supprime pas.'); break; }
        if (occupe(e)) { ops.supprimer.push(c.index); }
        break;
    }
  }
  for (const [nom, indexes] of places) {
    if (indexes.length > 1) {
      ops.erreurs.push(`« ${parNom(nom)?.nom ?? nom} » se retrouverait sur ${indexes.length} emplacements (${indexes.join(', ')}).`);
    }
  }
  return ops;
}
