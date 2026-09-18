export type StatutConflitSynchronisation = 'EN_ATTENTE' | 'RESOLU_GARDE_CENTRAL' | 'RESOLU_GARDE_LOCAL';

export type ModeleSynchronisable =
  | 'Dossier' | 'DossierCommentaire' | 'DossierHistorique' | 'DeclarationSecurite'
  | 'Mission' | 'MessageMeshLog';

/** Levé par SatelliteViewSet.synchroniser quand un événement mutable (Dossier/Mission) arrive
 * avec une version_de_base périmée — voir ConflitSynchronisationViewSet côté backend. Jamais
 * résolu automatiquement : `payload_local` (ce que le satellite proposait) et
 * `etat_central_au_conflit` (l'état central au moment du conflit) sont comparés à l'écran pour
 * que quelqu'un tranche explicitement. */
export interface ConflitSynchronisation {
  id: string;
  satellite: string;
  satellite_nom: string;
  modele: ModeleSynchronisable;
  modele_libelle: string;
  objet_id: string;
  payload_local: Record<string, unknown>;
  etat_central_au_conflit: Record<string, unknown>;
  statut: StatutConflitSynchronisation;
  cree_le: string;
  resolu_le: string | null;
  resolu_par: string | null;
}
