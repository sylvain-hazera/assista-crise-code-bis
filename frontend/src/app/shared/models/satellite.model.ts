export type ProfilSatellite = 'GW' | 'FULL';
export type StatutEnrolementSatellite = 'EN_ATTENTE' | 'APPROUVE' | 'REVOQUE';
export type EtatSatellite = 'ACTIF' | 'INACTIF' | 'PERDU' | null;

export interface Satellite {
  id: string;
  institution: string;
  institution_nom: string;
  nom: string;
  profil: ProfilSatellite;
  profil_libelle: string;
  statut_enrolement: StatutEnrolementSatellite;
  statut_enrolement_libelle: string;
  compte_service: string | null;
  dernier_contact: string | null;
  version_logicielle: string;
  date_creation: string;
  etat: EtatSatellite;
}

export interface JetonEnrolementSatellite {
  id: string;
  institution: string;
  jeton: string;
  expiration: string;
  utilise: boolean;
  date_creation: string;
}

export interface IdentifiantsCompteServiceSatellite {
  email: string;
  password: string;
}

export interface ContactSecours {
  nom: string;
  fonction: string;
  telephone: string | null;
  email: string;
}

/** Une ligne = une crise active + une institution mairie/EPCI actrice (PC Crise) dans le
 * périmètre de supervision du viewer (communes voisines -> préfecture) — voir
 * SatelliteViewSet.supervision. */
export interface LigneSupervision {
  crise_id: string;
  crise_nom: string;
  institution_id: string;
  institution_nom: string;
  satellite_id: string | null;
  satellite_etat: EtatSatellite;
  /** Dernière synchronisation MACHINE (heartbeat du satellite) — voir derniere_activite_humaine
   * pour l'activité humaine, une notion distincte. */
  satellite_dernier_contact: string | null;
  /** Dernière ligne de main courante (AuditLog) posée par n'importe quel membre de cette
   * institution, tous objets confondus — pas restreint à CETTE crise précise (voir
   * SatelliteViewSet.supervision) : un indicateur de "quelqu'un de cette collectivité utilise
   * la plateforme", pas un traçage exact par crise. */
  derniere_activite_humaine: string | null;
  contacts_secours: ContactSecours[];
}
