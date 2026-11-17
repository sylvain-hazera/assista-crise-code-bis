export type PublicDon = 'HOMME' | 'FEMME' | 'GARCON' | 'FILLE' | 'BEBE';
export const LABELS_PUBLIC_DON: Record<PublicDon, string> = { HOMME: 'Homme', FEMME: 'Femme', GARCON: 'Garçon', FILLE: 'Fille', BEBE: 'Bébé' };

/** Un article du catalogue : pour qui, et dans quelles tailles (par public ; clé vide = sans public). */
export interface ArticleCatalogueDon {
  designation: string;
  publics: PublicDon[];
  /** « haut », « bas », « pointure », « couches », ou vide : pas de taille. */
  mesure: string;
  neuf_exige: boolean;
  quantite: number;
  /** Ce qu'il faut tout de suite, sur ce qu'il faut pour durer. */
  quantite_urgence: number;
  tailles: Record<string, string[]>;
}
export interface FamilleCatalogueDon { famille: string; libelle: string; articles: ArticleCatalogueDon[]; }

/** Une ligne de besoin, précise : « T-shirt, homme, L, 3 ». */
export interface LigneDon {
  famille: string;
  designation: string;
  public: PublicDon | '';
  taille: string;
  neuf_exige: boolean;
  /** Ce qu'il faut pour durer. */
  quantite: number;
  /** Ce qu'il faut pour passer les premiers jours. */
  quantite_urgence?: number;
  /** Un mot personnel : « son vélo rose ». Lu de tous : jamais de nom. */
  message?: string;
}

export interface PersonneFoyer { id?: string; public: PublicDon; age: number | null; taille_haut: string; taille_bas: string; pointure: string; }
export type EtatBesoinFoyer = 'A_COUVRIR' | 'DEPANNE' | 'COUVERT';
export const LABELS_ETAT_BESOIN: Record<EtatBesoinFoyer, string> = { A_COUVRIR: 'à couvrir', DEPANNE: 'dépanné', COUVERT: 'couvert' };
export interface BesoinFoyer extends LigneDon { id?: string; quantite_remise?: number; etat?: EtatBesoinFoyer; }

export interface FoyerSinistre {
  id: string;
  reference: string;
  nom: string;
  contact: string;
  adresse: string;
  commentaire: string;
  crise: string | null;
  crise_nom: string | null;
  personnes: PersonneFoyer[];
  besoins: BesoinFoyer[];
}

export interface EngagementDon {
  id: string;
  institution_nom: string;
  quantite: number;
  quantite_recue: number | null;
  statut: 'PROMIS' | 'EXPEDIE' | 'RECU' | 'RELACHE' | 'ANNULE';
  statut_libelle: string;
  expire_le: string;
  envoi: string | null;
  le_mien: boolean;
}

export interface BesoinDon {
  id: string;
  famille: string;
  designation: string;
  public: PublicDon | '';
  taille: string;
  neuf_exige: boolean;
  precision: string;
  libelle: string;
  /** Le mot personnel de la demande, s'il y en a un. */
  message: string;
  nb_beneficiaires: number;
  /** « pour 14 hommes », « pour 3 foyers ». */
  pour_qui: string;
  /** La ligne telle qu'on la lit : « T-shirt, taille L — pour 14 hommes (56 pièces) ». */
  formulation: string;
  quantite_urgente: number;
  urgent: boolean;
  quantite_voulue: number;
  quantite_recue: number;
  quantite_promise: number;
  /** Ce qu'il reste à couvrir : zéro, la ligne est fermée, inutile d'en collecter. */
  reste: number;
  engagements: EngagementDon[];
}

export interface EnvoiDon {
  id: string;
  institution_nom: string;
  statut: 'ANNONCE' | 'RECU';
  statut_libelle: string;
  date_expedition: string;
  arrivee_prevue: string | null;
  transporteur: string;
  contact: string;
  commentaire: string;
  recu_le: string | null;
  lignes: { engagement: string; libelle: string; quantite: number; quantite_recue: number | null }[];
}

export interface AppelAuxDons {
  id: string;
  institution_nom: string;
  crise: string | null;
  crise_nom: string | null;
  titre: string;
  description: string;
  statut: 'BROUILLON' | 'OUVERT' | 'CLOS';
  statut_libelle: string;
  point: string | null;
  point_nom: string | null;
  depot: string | null;
  depot_nom: string | null;
  livraison_adresse: string;
  livraison_horaires: string;
  contact_nom: string;
  contact_telephone: string;
  contact_email: string;
  delai_engagement_jours: number;
  /** Rayon de l'appel en kilomètres ; null : toute la France. */
  portee_km: number | null;
  /** « dans un rayon de 100 km », « dans toute la France ». */
  portee: string;
  /** À combien mon institution se trouve de l'appel ; null pour le mien, ou si on ne sait pas. */
  distance_km: number | null;
  le_mien: boolean;
  besoins: BesoinDon[];
  envois: EnvoiDon[];
  avancement: { lignes: number; lignes_couvertes: number; pieces_voulues: number; pieces_recues: number; pieces_promises: number; pieces_restantes: number };
  reprise?: { foyers: number; lignes_creees: number; lignes_ajustees: number };
  entre_en_stock?: boolean;
  depot_nom_reception?: string | null;
}

/** Un avis public : ce qu'il faut et ce qui reste, sans contact ni lieu de livraison. */
export interface AvisDons {
  id: string;
  titre: string;
  description: string;
  institution_nom: string;
  crise_nom: string | null;
  date_ouverture: string | null;
  portee_km: number | null;
  portee: string;
  pieces_voulues: number;
  pieces_restantes: number;
  lignes: { famille: string; famille_libelle: string; formulation: string; message: string; neuf_exige: boolean; reste: number; couvert: boolean; urgent: boolean }[];
}

/** Portées proposées pour un appel, en kilomètres ; null : toute la France. */
export const PORTEES_APPEL: { km: number | null; libelle: string }[] = [
  { km: 50, libelle: '50 km' }, { km: 100, libelle: '100 km' }, { km: 200, libelle: '200 km' }, { km: 500, libelle: '500 km' },
  { km: null, libelle: 'Toute la France' },
];
