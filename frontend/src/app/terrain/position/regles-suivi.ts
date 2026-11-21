/*
 * Le suivi de position en mission, règles sans appareil (DOSSIER-PWA-INTERVENANTS.md, lot 5).
 * Portage de `ReglesSuivi` (mobile/shared/domaine/.../Position.kt) : mêmes seuils, même
 * consentement, même plafond que l'application Android. Seule différence, imposée par Safari :
 * rien ne part application fermée ou écran éteint.
 */

export interface Releve { latitude: number; longitude: number; instant: number; precision_m: number; }

export interface EtatSuivi {
  /** La personne a accepté d'être suivie en mission. Sans cela, rien ne démarre jamais. */
  consentement: boolean;
  /** Instant de démarrage du suivi en cours, ou null s'il est arrêté. */
  depuis: number | null;
  /** Engagement (`engagement_debut` de l'équipe) arrêté à la main : pas de reprise seule pour
   * celui-là. Un nouvel engagement relance le suivi. */
  engagement_arrete: string | null;
  dernier_envoi: Releve | null;
}

export const ETAT_INITIAL: EtatSuivi = { consentement: false, depuis: null, engagement_arrete: null, dernier_envoi: null };

export type MotifArret = 'FIN_D_ENGAGEMENT' | 'PLAFOND' | 'MANUEL';

/** Plafond dur : au-delà, le suivi s'arrête quoi qu'il arrive. */
export const PLAFOND_MS = 12 * 3_600_000;
/** On n'envoie pas plus souvent, même en mouvement. */
export const INTERVALLE_MIN_MS = 30_000;
/** À l'arrêt, on confirme tout de même sa présence à ce rythme. */
export const INTERVALLE_IMMOBILE_MS = 5 * 60_000;
/** En deçà, on considère que la personne n'a pas bougé (bruit du GPS). */
export const DEPLACEMENT_MIN_M = 25;

/** Distance à vol d'oiseau, en mètres (haversine). */
export function distanceEntre(a: Releve, b: Releve): number {
  const r = 6_371_000;
  const rad = (d: number) => d * Math.PI / 180;
  const dLat = rad(b.latitude - a.latitude);
  const dLon = rad(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

/** L'engagement en cours, s'il y en a un : celui de la première équipe engagée. */
export function engagementCourant(equipes: { engagement_debut?: string | null }[]): string | null {
  const debuts = equipes.map(e => e.engagement_debut).filter((d): d is string => !!d).sort();
  return debuts[0] ?? null;
}

export function estActif(etat: EtatSuivi): boolean { return etat.depuis !== null; }

/** Le suivi doit-il démarrer maintenant ? */
export function doitDemarrer(etat: EtatSuivi, equipes: { engagement_debut?: string | null }[]): boolean {
  const engagement = engagementCourant(equipes);
  return !!engagement && etat.consentement && !estActif(etat) && engagement !== etat.engagement_arrete;
}

/** Le suivi doit-il s'arrêter ? `equipes` vaut null quand on ne sait pas (pas de réseau) :
 * l'absence de nouvelles n'arrête rien, seul le plafond joue. */
export function motifArret(etat: EtatSuivi, equipes: { engagement_debut?: string | null }[] | null,
                           maintenant: number): MotifArret | null {
  if (etat.depuis === null) return null;
  if (maintenant - etat.depuis >= PLAFOND_MS) return 'PLAFOND';
  if (equipes !== null && engagementCourant(equipes) === null) return 'FIN_D_ENGAGEMENT';
  return null;
}

/** Cadence adaptative : ce relevé mérite-t-il d'être envoyé ? */
export function doitEnvoyer(dernier: Releve | null, nouveau: Releve): boolean {
  if (!dernier) return true;
  const ecoule = nouveau.instant - dernier.instant;
  if (ecoule < INTERVALLE_MIN_MS) return false;
  return ecoule >= INTERVALLE_IMMOBILE_MS || distanceEntre(dernier, nouveau) >= DEPLACEMENT_MIN_M;
}
