export type TypeDeclarant = 'PERSONNE_SEULE' | 'FAMILLE' | 'GROUPE';
export type SituationDeclarant = 'RELOGE' | 'EN_CENTRE' | 'BESOIN_CENTRE' | 'HORS_ZONE';

export interface DeclarationSecurite {
  id?: string;
  crise?: string | null;
  crise_nom?: string | null;
  type_declarant: TypeDeclarant;
  type_declarant_libelle?: string;
  situation?: SituationDeclarant;
  situation_libelle?: string;
  nom_referent: string;
  prenom_referent: string;
  contact_referent: string;
  nombre_adultes: number;
  nombre_enfants: number;
  centre_accueil?: string | null;
  centre_accueil_nom?: string | null;
  regime_alimentaire_specifique?: boolean;
  commentaire?: string | null;
  declare_par?: string | null;
  declare_par_nom?: string | null;
  registre_presence?: string | null;
  date_declaration?: string;
}
