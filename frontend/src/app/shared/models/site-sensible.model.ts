/** Enjeu du territoire pour le plan de sauvegarde communal : école, EHPAD, site industriel,
 * gymnase… Pré-alimenté depuis les bases publiques nationales (voir backend core/opendata/) et
 * toujours déposé en `PROPOSE` : une base ouverte se trompe et vieillit, la commune décide. */
export type SourceSiteSensible =
  'ANNUAIRE_EDUCATION' | 'FINESS' | 'ICPE' | 'EQUIPEMENTS_SPORTIFS' | 'SAISIE';

export type CategorieSiteSensible =
  'ENSEIGNEMENT' | 'SOINS' | 'INDUSTRIE' | 'RASSEMBLEMENT' | 'AUTRE';

export type StatutSiteSensible = 'PROPOSE' | 'RETENU' | 'ECARTE';

export interface SiteSensible {
  id: string;
  institution: string;
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
  /** Brut utile de la source : statut Seveso, régime ICPE, internat, cantine, accessibilité… */
  attributs: Record<string, unknown>;
  commentaire: string | null;
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

export interface SyntheseSitesSensibles {
  institution: string;
  institution_nom: string;
  commune_code: string | null;
  commune_nom: string | null;
  par_categorie: LigneSynthese[];
  /** Sites encore en PROPOSE : ce qui reste à relire. */
  a_relire: number;
  imports: ImportOpenData[];
  sources: { code: SourceSiteSensible; libelle: string }[];
}

export interface ResultatImport {
  resultats: Record<string, { crees?: number; mis_a_jour?: number; inchanges?: number;
                              total?: number; asynchrone?: boolean }>;
}
