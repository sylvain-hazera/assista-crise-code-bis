export type ProfilSatellite = 'GW' | 'FULL';
export type StatutEnrolementSatellite = 'EN_ATTENTE' | 'APPROUVE' | 'REVOQUE';
export type EtatSatellite = 'ACTIF' | 'INACTIF' | 'PERDU' | null;

export interface Satellite {
  /** Les ordres que l'agent de ce satellite dit connaître ; vide pour un agent ancien. */
  actions_agent?: ActionSatellite[];
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
  /** Mise à jour, ou l'un des deux ordres sans version : diagnostic, redémarrage. */
  action?: 'MISE_A_JOUR' | ActionSatellite;
  action_libelle?: string;
  statut: StatutMiseAJour;
  statut_libelle: string;
  /** Absents pour un diagnostic ou un redémarrage. */
  commit: string | null;
  version_libelle: string | null;
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
  institution_nom?: string;
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

/** Réponse de `versions-satellite/a-signer/` : de quoi signer la dernière version poussée
 * depuis la page, sans que la phrase de passe quitte le navigateur. */
export interface VersionASigner {
  /** Dernier commit poussé sur le dépôt public, ou null s'il n'a pas répondu. */
  version: { commit: string; titre: string; date: string } | null;
  erreur_depot: string | null;
  deja_publiee: boolean;
  /** Clé de signature chiffrée par la phrase de passe, ou null si elle n'a pas été préparée. */
  cle: import('../../services/signature-satellite').CleEmballee | null;
}

/** Ce que le central peut demander à l'agent d'un satellite, hors mise à jour : une liste
 * fermée, sans paramètre, que l'agent connaît d'avance (satellite/agent_mise_a_jour.py). */
export type ActionSatellite =
  | 'BILAN' | 'DIAGNOSTIC' | 'JOURNAUX' | 'MIGRATIONS' | 'SYSTEME' | 'RESEAU' | 'DEPOT'
  | 'REDEMARRAGE' | 'MIGRER' | 'RECONSTRUCTION' | 'NETTOYAGE' | 'SAUVEGARDE' | 'RESTAURATION';

export interface DescriptionActionSatellite {
  code: ActionSatellite;
  libelle: string;
  /** Ce que l'ordre fait sur le satellite, dit avant de le donner. */
  aide: string;
  /** Présent pour un ordre qui change quelque chose : le texte de la confirmation. */
  confirmer?: string;
}

/** Regarder : rien de cela ne change la machine. */
export const ACTIONS_REGARDER: DescriptionActionSatellite[] = [
  { code: 'BILAN', libelle: 'Bilan complet (tout en une fois)', aide: "Les six relevés ci-dessous dans un seul journal, à copier d'un clic." },
  { code: 'DIAGNOSTIC', libelle: 'Diagnostic', aide: "État de chaque service et derniers messages de ceux qui sont en panne." },
  { code: 'JOURNAUX', libelle: 'Journaux de tous les services', aide: "Les derniers messages de chaque service, en panne ou non." },
  { code: 'MIGRATIONS', libelle: 'État des migrations', aide: "Ce qui est appliqué à la base, ce qui attend, et si le code démarre." },
  { code: 'SYSTEME', libelle: 'État de la machine', aide: "Place, mémoire, charge, température, ce que Docker occupe." },
  { code: 'RESEAU', libelle: 'État du réseau', aide: "Heure, adresses, et si le satellite joint le central." },
  { code: 'DEPOT', libelle: 'État du code installé', aide: "Version sur place et fichiers modifiés à la main." },
];

/** Agir : ce que ferait quelqu'un sur place, et rien d'autre. */
export const ACTIONS_AGIR: DescriptionActionSatellite[] = [
  { code: 'REDEMARRAGE', libelle: 'Redémarrer les services', aide: "Relance les services. Rien n'est reconstruit.",
    confirmer: "S'il sert un site local, celui-ci est coupé quelques instants. Rien n'est reconstruit." },
  { code: 'MIGRER', libelle: 'Appliquer les migrations', aide: "Sauvegarde la base, puis applique les migrations une par une.",
    confirmer: "La base est sauvegardée d'abord, puis modifiée. Le journal dira laquelle a échoué, s'il y en a une." },
  { code: 'RECONSTRUCTION', libelle: 'Reconstruire et redémarrer', aide: "Reconstruit les images depuis le code installé, puis redémarre.",
    confirmer: "La construction peut durer longtemps sur un Raspberry Pi ; le site local est coupé au redémarrage." },
  { code: 'NETTOYAGE', libelle: 'Libérer de la place', aide: "Retire le cache de construction ancien et les images orphelines. Ni conteneur, ni volume, ni sauvegarde." },
  { code: 'SAUVEGARDE', libelle: 'Sauvegarder la base', aide: "Une sauvegarde de la base, gardée sur le satellite." },
  { code: 'RESTAURATION', libelle: 'Revenir à la version précédente',
    aide: "Ramène le code et la base à ce qu'ils étaient avant la dernière mise à jour.",
    confirmer: "Le code et la base reviennent à l'état d'avant la dernière mise à jour. La base actuelle n'est pas "
      + "détruite : elle est gardée sur le satellite sous un autre nom. Ce qui a été saisi depuis n'apparaîtra plus." },
];
