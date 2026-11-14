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
  /** À jour ou en retard sur la dernière version SIGNÉE publiée. `null` tant qu'aucune version
   * n'est publiée : il n'y a alors pas de référence. */
  etat_version: 'A_JOUR' | 'EN_RETARD' | 'INCONNUE' | null;
  /** Faux = pas d'agent de mise à jour en service (satellite pas repassé par
   * `./installer.sh mettre-a-jour`, ou passerelle Windows) : rien à ordonner d'ici. */
  agent_present: boolean;
  /** Le dernier ordre de mise à jour, ouvert ou terminé. */
  mise_a_jour: MiseAJourSatellite | null;
}

export type StatutMiseAJour = 'DEMANDEE' | 'EN_COURS' | 'REUSSIE' | 'ECHOUEE' | 'ANNULEE' | 'EXPIREE';

export interface MiseAJourSatellite {
  id: string;
  statut: StatutMiseAJour;
  statut_libelle: string;
  commit: string;
  version_libelle: string;
  /** Où en est le satellite, ou pourquoi il s'est arrêté. */
  etape: string;
  date_demande: string;
  date_debut: string | null;
  date_fin: string | null;
  version_avant: string;
  malgre_crise: boolean;
  demandee_par_nom: string | null;
  /** Sorties des commandes sur le satellite. Absent de la liste, joint dans l'historique. */
  journal: string | null;
}

/** Une version que les satellites acceptent d'installer : un commit et sa signature. */
export interface VersionSatellite {
  id: string;
  commit: string;
  libelle: string;
  signature: string;
  date_publication: string;
  retiree: boolean;
  publiee_par_nom: string | null;
}

export interface VersionsSatellite {
  /** Faux = aucune clé publique sur le serveur : rien ne peut être publié. */
  cle_configuree: boolean;
  versions: VersionSatellite[];
}

export interface JetonEnrolementSatellite {
  id: string;
  institution: string;
  jeton: string;
  profil: 'GW' | 'FULL';
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
