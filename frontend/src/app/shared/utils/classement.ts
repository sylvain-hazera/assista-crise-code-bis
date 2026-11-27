/**
 * Classement « quoi + pour qui » (27/11/2026), miroir de backend/core/classement.py.
 *
 * La famille dit l'action (Transport / évacuation, Hébergement, Soins, Nourriture…) ; le « pour
 * qui » n'est demandé que si la famille en admet plusieurs ; la catégorie d'animaux, seulement
 * pour des animaux. Ainsi « transport d'animaux » et « animaux à évacuer » sont un seul chemin.
 */
export type Beneficiaire = 'PERSONNES' | 'ANIMAUX' | 'BIENS';
export type AxeClassement = 'demande' | 'offre';

const P: Beneficiaire = 'PERSONNES';
const A: Beneficiaire = 'ANIMAUX';
const B: Beneficiaire = 'BIENS';

/** Une demande de soins pour une personne n'existe pas (une urgence médicale, c'est le 15). */
export const FAMILLES: Record<string, Record<AxeClassement, Beneficiaire[]>> = {
  EVAC: { demande: [P, A, B], offre: [P, A, B] },
  ABRI: { demande: [P, A], offre: [P, A] },
  SOIN: { demande: [A], offre: [P, A] },
  NOUR: { demande: [P, A], offre: [P, A] },
  PSY: { demande: [P], offre: [P] },
  ADMIN: { demande: [P], offre: [P] },
  LANG: { demande: [], offre: [] },
  NETT: { demande: [B], offre: [B] },
  MAT: { demande: [], offre: [] },
  AUTRE: { demande: [P, A, B], offre: [P, A, B] },
};

export const LIBELLES_BENEFICIAIRE: Record<Beneficiaire, string> = {
  PERSONNES: 'Des personnes',
  ANIMAUX: 'Des animaux',
  BIENS: 'Des biens (maison, matériel…)',
};

export const COURT_BENEFICIAIRE: Record<Beneficiaire, string> = {
  PERSONNES: 'personnes', ANIMAUX: 'animaux', BIENS: 'biens',
};

export const CATEGORIES_ANIMAUX: { value: string; label: string }[] = [
  { value: 'COMPAGNIE', label: 'Compagnie (chiens, chats…)' },
  { value: 'EQUIDES', label: 'Chevaux, ânes' },
  { value: 'BETAIL', label: 'Bétail (vaches, moutons, chèvres, porcs)' },
  { value: 'VOLAILLES', label: 'Volailles' },
  { value: 'AUTRES', label: 'Autres animaux' },
];

/** Un type de demande ou d'offre tel que servi par l'API (`code` sur la famille seulement). */
export interface TypeClasse { id: string; type: string; code?: string | null; parent?: string | null }

/** Le code de la famille d'un type : le sien, sinon celui de son parent. */
export function codeFamille(type: TypeClasse | undefined, parId: Map<string, TypeClasse>): string | null {
  if (!type) return null;
  if (type.code) return type.code;
  return type.parent ? parId.get(type.parent)?.code ?? null : null;
}

/**
 * Les « pour qui » à proposer : ceux qu'admet la famille, restreints à ceux qu'écoute une
 * institution (`ecoutes`, servi par types-a-lecoute ; absent = tous).
 */
export function beneficiairesAdmis(code: string | null, axe: AxeClassement, ecoutes?: string[]): Beneficiaire[] {
  const admis = code ? FAMILLES[code]?.[axe] ?? [] : [];
  if (!ecoutes || ecoutes.length === 0) return admis;
  const filtres = admis.filter(b => ecoutes.includes(b));
  return filtres.length ? filtres : admis;
}

/** Le « pour qui » retenu d'office quand il n'y a pas à le demander. */
export function beneficiaireParDefaut(admis: Beneficiaire[]): Beneficiaire | '' {
  return admis.length === 1 ? admis[0] : '';
}

/** « Transport · animaux » : pour les listes et compteurs du pilotage. */
export function libelleClasse(type: string | null | undefined, beneficiaire?: string | null): string {
  const t = type || 'Autre';
  const court = beneficiaire ? COURT_BENEFICIAIRE[beneficiaire as Beneficiaire] : '';
  return court ? `${t} · ${court}` : t;
}
