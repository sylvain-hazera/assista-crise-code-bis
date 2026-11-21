/*
 * L'évaluation des dégâts à pied, logique sans écran (DOSSIER-ADRESSES-ET-DEGATS.md, § 5 ;
 * DOSSIER-PWA-INTERVENANTS.md, lot 5). Portage de `mobile/shared/domaine/.../Degats.kt` : les
 * mêmes règles que l'application Android, pour que le serveur ne voie aucune différence.
 */

/** Les états d'un bien, comme sur le site et dans l'application. */
export const ETATS_BIEN = [
  { code: 'PAS_DE_DEGATS', libelle: 'Pas de dégâts' },
  { code: 'DEGATS_FAIBLES', libelle: 'Dégâts faibles' },
  { code: 'DEGATS_FORTS', libelle: 'Dégâts forts' },
  { code: 'DETRUITE', libelle: 'Détruit' },
] as const;

export const DANGERS = [
  { code: 'STRUCTURE', libelle: 'Structure instable' },
  { code: 'ELECTRICITE', libelle: 'Électricité' },
  { code: 'GAZ', libelle: 'Gaz' },
  { code: 'EAU', libelle: 'Eau' },
  { code: 'AUTRE', libelle: 'Autre danger' },
] as const;

export interface TypeBien { id: string; nom: string; a_une_adresse: boolean; }

/** Un point de la tournée : une adresse du référentiel, ou un bien déjà référencé. */
export interface PointTournee {
  ban_id?: string | null;
  habitation?: string | null;
  libelle: string;
  latitude: number;
  longitude: number;
  distance_m: number;
  statut_evaluation?: string | null;
  type_bien?: string | null;
  position_corrigee?: boolean;
  /** Évalué sur ce téléphone, en attente d'envoi. */
  en_attente?: boolean;
}

export interface BienEmbarque {
  id: string; ban_id: string | null; adresse: string; latitude: number; longitude: number;
  statut_evaluation: string | null; type_bien: string | null; position_corrigee: boolean;
}

/** Ce qui est embarqué pour évaluer hors réseau (GET habitations/secteur/). Les adresses
 * arrivent compactes : [identifiant, libellé, latitude, longitude]. */
export interface SecteurEmbarque {
  crise: string;
  latitude: number;
  longitude: number;
  rayon_m: number;
  genere_le: string;
  adresses: [string, string, number, number][];
  biens: BienEmbarque[];
  dossiers: { id: string; numero: string; titre: string; statut: string; habitation: string }[];
  cercles: number[][][];
  /** Constats faits ici depuis l'embarquement : l'effacement attend leur envoi. */
  constats_faits?: number;
}

/** Le constat, tel qu'il part au serveur (POST habitations/constat/). `id` est tiré ICI : renvoyé
 * dix fois, il ne crée qu'un constat. */
export interface Constat {
  id: string;
  crise: string;
  ban_id?: string | null;
  habitation?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  position_corrigee: boolean;
  type_bien?: string | null;
  type_bien_libre?: string | null;
  description?: string | null;
  statut_evaluation: string;
  dangers: string[];
  personne_sur_place: boolean | null;
  a_reloger: boolean | null;
  ouvrir_dossier: boolean;
  commentaire?: string | null;
  constate_le: string;
}

/** Distance à plat, juste à quelques centimètres près sur quelques kilomètres. */
export function distanceM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const est = (lon2 - lon1) * 111_320 * Math.cos(((lat1 + lat2) / 2) * Math.PI / 180);
  return Math.hypot(est, (lat2 - lat1) * 111_320);
}

export function estEvalue(p: PointTournee): boolean {
  return !!p.en_attente || (!!p.statut_evaluation && p.statut_evaluation !== 'NON_EVALUEE');
}

/**
 * La tournée hors réseau : les adresses du secteur embarqué (avec l'état du bien de cette adresse
 * s'il est référencé), les biens sans adresse, et par-dessus ce qui a été évalué ici et attend
 * d'être envoyé. Du plus proche au plus lointain, dans le rayon.
 */
export function tourneeHorsLigne(secteur: SecteurEmbarque, enFile: Constat[], latitude: number, longitude: number,
                                 rayonM = 150, nombre = 200): PointTournee[] {
  const biensParAdresse = new Map(secteur.biens.filter(b => b.ban_id).map(b => [b.ban_id!, b]));
  const evaluesIci = new Set(enFile.map(c => c.ban_id).filter((x): x is string => !!x));
  const biensEvaluesIci = new Set(enFile.map(c => c.habitation).filter((x): x is string => !!x));
  const points: Omit<PointTournee, 'distance_m'>[] = [
    ...secteur.adresses.map(([banId, libelle, lat, lon]) => {
      const bien = biensParAdresse.get(banId);
      return {
        ban_id: banId, habitation: bien?.id ?? null, libelle,
        latitude: bien?.latitude ?? lat, longitude: bien?.longitude ?? lon,
        statut_evaluation: bien?.statut_evaluation ?? null, type_bien: bien?.type_bien ?? null,
        position_corrigee: bien?.position_corrigee ?? false, en_attente: evaluesIci.has(banId),
      };
    }),
    ...secteur.biens.filter(b => !b.ban_id).map(b => ({
      habitation: b.id, libelle: b.adresse, latitude: b.latitude, longitude: b.longitude,
      statut_evaluation: b.statut_evaluation, type_bien: b.type_bien, en_attente: biensEvaluesIci.has(b.id),
    })),
    ...enFile.filter(c => !c.ban_id && !c.habitation && c.latitude != null && c.longitude != null).map(c => ({
      libelle: c.description || 'Point ajouté ici', latitude: c.latitude!, longitude: c.longitude!,
      statut_evaluation: c.statut_evaluation, en_attente: true,
    })),
  ];
  return points
    .map(p => ({ ...p, distance_m: distanceM(latitude, longitude, p.latitude, p.longitude) }))
    .filter(p => p.distance_m <= rayonM)
    .sort((a, b) => a.distance_m - b.distance_m)
    .slice(0, nombre);
}

/** Les points du serveur, marqués de ce qui a été évalué ici et attend d'être envoyé. */
export function marquerEnAttente(points: PointTournee[], enFile: Constat[]): PointTournee[] {
  const adresses = new Set(enFile.map(c => c.ban_id).filter(Boolean));
  const biens = new Set(enFile.map(c => c.habitation).filter(Boolean));
  return points.map(p => ((p.ban_id && adresses.has(p.ban_id)) || (p.habitation && biens.has(p.habitation))
    ? { ...p, en_attente: true } : p));
}

export function cleDuPoint(p: PointTournee): string {
  return p.ban_id ?? p.habitation ?? `${p.latitude},${p.longitude}`;
}

/** Le point le plus proche qui reste à évaluer : « Suivant : 14 rue des Pins, à 20 m ». */
export function prochainPoint(points: PointTournee[], sauf: string | null = null): PointTournee | null {
  return points.find(p => !estEvalue(p) && cleDuPoint(p) !== sauf) ?? null;
}

/** Le secteur embarqué s'efface dès la synchronisation de ce qui y a été saisi (décision du
 * 20/11/2026) : au moins un constat fait, et plus aucun constat ni photo de constat en file. */
export function secteurAEffacer(secteur: SecteurEmbarque | null, genresEnFile: string[]): boolean {
  return !!secteur && (secteur.constats_faits ?? 0) > 0
    && !genresEnFile.some(g => g === 'constat' || g === 'photo_constat');
}

export function libelleEtat(p: PointTournee): string {
  if (p.en_attente) return 'évalué ici, en attente d\'envoi';
  if (!p.statut_evaluation || p.statut_evaluation === 'NON_EVALUEE') return 'à évaluer';
  return ETATS_BIEN.find(e => e.code === p.statut_evaluation)?.libelle ?? p.statut_evaluation;
}
