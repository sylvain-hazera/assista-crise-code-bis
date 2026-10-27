/** Enjeu du territoire pour le plan de sauvegarde communal : école, EHPAD, site industriel,
 * gymnase… Pré-alimenté depuis les bases publiques nationales (voir backend core/opendata/) et
 * toujours déposé en `PROPOSE` : une base ouverte se trompe et vieillit, la commune décide. */
export type SourceSiteSensible =
  'ANNUAIRE_EDUCATION' | 'FINESS' | 'ICPE' | 'EQUIPEMENTS_SPORTIFS' | 'SIRENE' | 'SAISIE';

export type CategorieSiteSensible =
  'ENSEIGNEMENT' | 'PETITE_ENFANCE' | 'SOINS' | 'INDUSTRIE' | 'ELEVAGE' | 'VETERINAIRE'
  | 'HEBERGEMENT' | 'RASSEMBLEMENT' | 'MOYENS' | 'APPROVISIONNEMENT' | 'FUNERAIRE' | 'AUTRE';

export type StatutSiteSensible = 'PROPOSE' | 'RETENU' | 'ECARTE';

/** Qui a la charge du site. C'est ce qui permet à une collectivité supra-communale de ne relire
 * que sa compétence : sur les 852 établissements scolaires du Finistère, 75 collèges publics
 * relèvent du département, 374 écoles publiques des communes, 40 lycées de la région. */
export type EchelonCompetence =
  'COMMUNE' | 'EPCI' | 'DEPARTEMENT' | 'REGION' | 'ETAT' | 'PRIVE' | 'INDETERMINE';

/** Niveau de secteur d'une institution, tel que son type le lui donne. */
export type NiveauSecteur = 'commune' | 'epci' | 'departement' | 'region' | 'national';

/** Ce qu'une AUTRE collectivité a décidé de la même fiche. C'est ce qui rend le partage
 * visible : une mairie voit que le département a retenu son collège, et réciproquement. */
export interface DecisionAutre {
  institution_nom: string;
  statut: StatutSiteSensible;
  statut_libelle: string;
  convention: boolean;
}

export interface SiteSensible {
  id: string;
  /** Qui a fait entrer la fiche — une trace, pas une appartenance : la fiche est partagée par
   * les collectivités du territoire. */
  institution_origine: string | null;
  commune_code: string | null;
  commune_nom: string | null;
  source: SourceSiteSensible;
  source_libelle: string;
  source_id: string;
  categorie: CategorieSiteSensible;
  categorie_libelle: string;
  statut: StatutSiteSensible;
  statut_libelle: string;
  nom: string;
  adresse: string | null;
  latitude: number | null;
  longitude: number | null;
  telephone: string | null;
  /** À estimer par la commune : aucune source ouverte ne donne d'effectif fiable. */
  effectif_estime: number | null;
  /** Brut utile de la source : statut Seveso, régime ICPE, internat, cantine, accessibilité,
   * et pour un élevage les espèces et l'effectif animal autorisé (`especes`, `cheptel`). */
  attributs: Record<string, unknown>;
  commentaire: string | null;
  echelon_competence: EchelonCompetence;
  echelon_libelle: string;
  /** Les décisions des autres collectivités sur cette même fiche. */
  decisions_autres: DecisionAutre[];
  /** À protéger : le site subit la crise (école, cheptel, camping occupé). */
  est_enjeu: boolean;
  /** Mobilisable : le site aide à y répondre (car, pelle, lits, cuisine, vétérinaire). */
  est_ressource: boolean;
  /** La source désigne une personne physique, donc une adresse de domicile. */
  personne_physique: boolean;
  /** Une ressource recensée n'est pas une ressource acquise : seule une convention engage. */
  convention_existe: boolean;
  convention_numero: string | null;
  convention_date_signature: string | null;
  /** Une convention expirée est plus dangereuse qu'une absence de convention : on compte
   * dessus. */
  convention_echeance: string | null;
  /** Le document n'est jamais servi comme URL (chiffré au repos, préfixe bloqué par nginx) :
   * ce booléen dit seulement qu'il existe. */
  a_convention_document: boolean;
  /** Vrai quand `adresse`, `latitude` et `longitude` sont volontairement nuls : il faut passer
   * par `devoiler()`, qui laisse une trace en main courante. */
  adresse_masquee: boolean;
  valide_par_nom: string | null;
  /** Date de la donnée source telle qu'annoncée par le producteur, pas la date d'import. */
  date_source: string | null;
  date_import: string;
  /** Rempli quand le site a été transformé en point opérationnel. */
  point_operationnel: string | null;
}

export interface ImportOpenData {
  id: string;
  source: SourceSiteSensible;
  source_libelle: string;
  statut: 'EN_COURS' | 'TERMINEE' | 'ECHEC';
  resultat: { crees?: number; mis_a_jour?: number; inchanges?: number; total?: number };
  erreur: string | null;
  date_lancement: string;
  date_fin: string | null;
}

export interface LigneSynthese {
  categorie: CategorieSiteSensible;
  libelle: string;
  PROPOSE: number;
  RETENU: number;
  ECARTE: number;
}

/** Un thème recensable par SIRENE. Plus fin qu'une catégorie : à l'échelle d'un département,
 * « moyens et travaux » en bloc rend 3 270 établissements, « transport de voyageurs » 57. */
export interface ThemeSirene {
  code: string;
  libelle: string;
  categorie: CategorieSiteSensible;
  defaut: boolean;
}

export interface SyntheseSitesSensibles {
  institution: string;
  institution_nom: string;
  commune_code: string | null;
  commune_nom: string | null;
  /** Niveau de la collectivité connectée, et nom de son secteur (« Finistère »). */
  niveau: NiveauSecteur;
  secteur_nom: string | null;
  /** Son échelon de compétence : ce qu'elle valide dans SON plan. */
  echelon_propre: EchelonCompetence;
  /** Les périmètres qu'elle a le droit de demander à l'import (jamais plus large que son
   * niveau). */
  perimetres_possibles: NiveauSecteur[];
  par_categorie: LigneSynthese[];
  /** Sites en PROPOSE relevant de sa compétence : le travail réel qui reste. */
  a_relire: number;
  /** Tous échelons confondus : rien n'est caché, c'est le compteur qui est cadré. */
  a_relire_tous_echelons: number;
  imports: ImportOpenData[];
  sources: { code: SourceSiteSensible; libelle: string }[];
  themes: ThemeSirene[];
  echelons: { code: EchelonCompetence; libelle: string }[];
}

/** Les champs de convention qu'un agent saisit. */
export interface SaisieConvention {
  convention_existe: boolean;
  convention_numero: string;
  convention_date_signature: string;
  convention_echeance: string;
}

/** Ce que rend `devoiler()` : la donnée d'une personne, après une consultation tracée. */
export interface CoordonneesDevoilees {
  adresse: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface ResultatImport {
  resultats: Record<string, { crees?: number; mis_a_jour?: number; inchanges?: number;
                              total?: number; asynchrone?: boolean }>;
}
