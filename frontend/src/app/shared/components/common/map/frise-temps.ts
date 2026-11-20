/**
 * Une seule frise de temps pour la météo de la carte (demande du 20/11/2026 : « pourquoi deux
 * barres de temps ? une seule, avec une bascule automatique entre le passé et le futur »).
 *
 * De gauche à droite :
 * - SELON LES RELEVÉS : les images observées du radar (l'heure écoulée, jusqu'à « maintenant ») ;
 * - NOS ESTIMATIONS : l'heure qui vient, extrapolée des images radar (pas une prévision) ;
 * - PRÉVISION MÉTÉO-FRANCE : au-delà, jusqu'à trois heures (AROME-PI).
 *
 * Décision du 20/11/2026 : sur la première heure, la pluie montrée est celle de nos estimations,
 * plus fine (pas de cinq minutes) ; la pluie prévue par Météo-France prend le relais ensuite. Les
 * autres prévisions (rafales, neige, verglas, grêle) se montrent sur tout le futur, jamais sur le
 * passé : une prévision d'une heure déjà écoulée n'a rien à faire à côté du relevé.
 *
 * Fonctions pures, testées sans carte.
 */

export type NaturePas = 'releve' | 'estimation' | 'prevision';

/** Une image de la boucle du radar, telle que la carte la garde. */
export interface ImageRadarFrise {
  instant: number; heure: string; estimation: boolean; minutes: number;
}

export interface PasFrise {
  instant: number;
  heure: string;
  nature: NaturePas;
  /** Rang de l'image du radar à montrer (relevé ou estimation), ou null. */
  radar: number | null;
  /** Minutes d'avance d'une estimation (« +20 min »). */
  minutes: number;
  /** Échéance de prévision Météo-France à montrer pour les rafales, la neige… ou null. */
  prevision: string | null;
}

/** Ce que la carte montre à un pas donné. */
export interface CalquesDuPas {
  radar: boolean;
  /** Pluie prévue par Météo-France. */
  pluie: boolean;
  /** Rafales, neige, verglas, grêle prévus. */
  autresPrevisions: boolean;
}

const QUART_D_HEURE_DEMI_MS = 7.5 * 60_000;

function plusProche(echeances: { iso: string; t: number }[], instant: number): { iso: string; t: number } | null {
  let meilleure: { iso: string; t: number } | null = null;
  for (const e of echeances) {
    if (!meilleure || Math.abs(e.t - instant) < Math.abs(meilleure.t - instant)) meilleure = e;
  }
  return meilleure;
}

/**
 * La frise : les images du radar (relevés puis estimations), puis les échéances de prévision
 * qui vont au-delà de la dernière image. Sans radar, la frise n'est faite que des échéances ;
 * sans prévision, que du radar.
 */
export function construireFrise(radar: ImageRadarFrise[], echeances: string[]): PasFrise[] {
  const triees = echeances.map(iso => ({ iso, t: new Date(iso).getTime() }))
    .filter(e => !Number.isNaN(e.t)).sort((a, b) => a.t - b.t);
  if (!radar.length) {
    return triees.map(e => ({ instant: e.t, heure: e.iso, nature: 'prevision' as const, radar: null, minutes: 0,
                              prevision: e.iso }));
  }
  const pas: PasFrise[] = radar.map((image, rang) => {
    // Une estimation porte la prévision Météo-France du même quart d'heure (rafales, neige…).
    const proche = image.estimation ? plusProche(triees, image.instant) : null;
    return {
      instant: image.instant, heure: image.heure, nature: image.estimation ? 'estimation' : 'releve',
      radar: rang, minutes: image.minutes,
      prevision: proche && Math.abs(proche.t - image.instant) <= QUART_D_HEURE_DEMI_MS ? proche.iso : null,
    };
  });
  const derniere = radar[radar.length - 1].instant;
  for (const e of triees) {
    // Au moins un demi-pas au-delà de la dernière image : pas deux crans pour le même instant.
    if (e.t > derniere + 2.5 * 60_000) {
      pas.push({ instant: e.t, heure: e.iso, nature: 'prevision', radar: null, minutes: 0, prevision: e.iso });
    }
  }
  return pas;
}

/** Rang de « maintenant » : la dernière image observée ; sans radar, l'échéance la plus proche
 * de l'heure qu'il est. */
export function rangMaintenant(frise: PasFrise[], maintenant = Date.now()): number {
  if (!frise.length) return 0;
  let dernierReleve = -1;
  frise.forEach((p, i) => { if (p.nature === 'releve') dernierReleve = i; });
  if (dernierReleve >= 0) return dernierReleve;
  let meilleur = 0;
  frise.forEach((p, i) => {
    if (Math.abs(p.instant - maintenant) < Math.abs(frise[meilleur].instant - maintenant)) meilleur = i;
  });
  return meilleur;
}

/** Rang du pas le plus proche d'un instant choisi (la frise se reconstruit à chaque image). */
export function rangDeLInstant(frise: PasFrise[], instant: number): number {
  let meilleur = 0;
  frise.forEach((p, i) => {
    if (Math.abs(p.instant - instant) < Math.abs(frise[meilleur].instant - instant)) meilleur = i;
  });
  return meilleur;
}

export function calquesDuPas(pas: PasFrise | null): CalquesDuPas {
  if (!pas) return { radar: true, pluie: true, autresPrevisions: true };
  return {
    radar: pas.radar !== null,
    pluie: pas.nature === 'prevision',
    autresPrevisions: pas.prevision !== null,
  };
}

/** « maintenant », « dans 45 min », « dans 1 h 30 », « il y a 15 min ». */
export function ecartLisible(instant: number, maintenant = Date.now()): string {
  const minutes = Math.round((instant - maintenant) / 60000);
  if (Math.abs(minutes) < 3) return 'maintenant';
  const absolu = Math.abs(minutes);
  const duree = absolu < 60 ? `${absolu} min`
    : `${Math.floor(absolu / 60)} h${absolu % 60 ? ' ' + String(absolu % 60).padStart(2, '0') : ''}`;
  return minutes > 0 ? `dans ${duree}` : `il y a ${duree}`;
}
