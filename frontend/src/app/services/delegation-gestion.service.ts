import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Une délégation de gestion mairie → AASC (voir backend core/delegation_gestion.py). */
export interface DelegationGestion {
  id: string;
  collectivite: string;
  collectivite_nom: string;
  aasc: string;
  aasc_nom: string;
  communes: string[];
  statut: 'ACTIVE' | 'RETIREE';
  en_vigueur: boolean;
  convention_reference: string;
  convention_signee_le: string | null;
  convention_signataire: string;
  convention_signataire_qualite: string;
  date_fin: string | null;
  a_un_document: boolean;
  date_creation: string;
  date_retrait: string | null;
  motif_retrait: string;
  /** Convention départementale : suivie depuis « Suivi du département ». */
  departementale?: boolean;
}

/** Un connecteur d'envoi proposé : Brevo, SMTP d'une institution, SMTP de la plateforme. */
export interface ConnecteurEnvoi {
  cle: string; type: 'brevo' | 'smtp' | 'plateforme'; libelle: string; adresse: string; institution: string;
  dernier_succes: string | null; dernier_echec: string | null; dernier_echec_motif: string;
}

/** Ce que la fenêtre « Préparer l'invitation » affiche avant tout envoi. */
export interface PreparationInvitation {
  resume: { vers_referent: number; vers_officielle: number; sans_adresse: string[]; deja_membres: number };
  pretes: { id: string; nom: string }[];
  sujet: string; corps: string; champs: string[];
  connecteurs: ConnecteurEnvoi[];
}

export interface ApercuInvitation { etat: string; destinataire?: string; vers_referent?: boolean; sujet?: string; corps?: string; }

export interface CampagneInvitation {
  id: string; date: string; date_fin: string | null; statut: 'EN_COURS' | 'TERMINEE'; connecteur: string;
  prevues: number; envoyees: number; echecs: number; sans_adresse: number; deja_membres: number;
  erreurs: { collectivite: string; motif: string }[];
}

/** Un évènement de l'historique d'une délégation. */
export interface EvenementDelegation { date: string; type: 'journal' | 'amorcage' | 'invitation' | 'campagne'; action: string; par: string; texte: string; }

export interface PersonneQuiAgit { id: string; nom: string; titre: string; }

/** Répertoire d'une intercommunalité du département (délégation départementale). */
export interface RepertoireEpci {
  id: string;
  nom: string;
  contacts: { nom: string; fonction: string; email: string; telephone: string }[];
  annuaire: { nom: string; organisme: string; categorie: string; email: string; telephone: string }[];
}

/** Amorçage d'un département : où en est chaque étape. */
export interface EtatAmorcage {
  id: string;
  debut: string;
  fin: string | null;
  etapes: Record<string, { statut: string; comptes?: Record<string, number>; erreur?: string; erreurs?: string[] }>;
  sites: { source: string; statut: string; date_fin: string | null; crees?: number | null; total?: number | null;
           incomplet?: string[]; erreur?: string | null }[];
  /** La tâche a été interrompue (relance possible). */
  interrompu?: boolean;
  /** Communes du département dont les risques sont relevés depuis le lancement. */
  risques?: { faites: number; total: number;
             geoportail?: { servitudes: number; communes_avec_servitudes: number; zones_plu: number; communes_avec_plu: number } };
}

/** Une institution dans l'arborescence du département. */
export interface FicheArbre {
  id: string; nom: string; email: string | null; telephone: string | null; adresse: string | null;
  membres: number; delegation: boolean;
  /** Dernière invitation envoyée à la collectivité (« Rejoindre votre collectivité »). */
  invitee_le?: string | null;
  /** La personne à joindre, quand ce n'est pas l'adresse officielle. */
  referent?: Referent | null;
}

export interface Referent { nom: string; fonction: string; email: string | null; telephone: string | null; }

/** Le département, ses intercommunalités et leurs communes. */
export interface Arborescence {
  departement: { code: string; nom: string; institution: FicheArbre | null };
  epcis: {
    code: string; nom: string; institution: FicheArbre | null;
    communes: { code: string; nom: string; population: number | null; mairie: FicheArbre | null }[];
  }[];
  totaux: { communes: number; mairies_sur_la_plateforme: number; epcis: number };
}

/** Avancement d'un plan (PCS d'une commune, PICS d'une intercommunalité). */
export interface Avancement {
  parties_faites: number; parties_total: number; pourcentage: number; restantes: string[];
  arrete_date: string | null; date_maj: string | null;
}

export type Enrolement = 'non_creee' | 'pas_d_adresse' | 'non_invitee' | 'invitee' | 'a_rejoint';

/** Suivi départemental : vue d'ensemble. */
export interface SuiviDepartement {
  departement: { code: string; nom: string };
  totaux: { communes: number; epcis: number; mairies_sur_la_plateforme: number; ont_rejoint: number; invitees: number; sans_adresse: number };
  epcis: { code: string; nom: string; enrolement: Enrolement | null; communes: number; ont_rejoint: number; invitees: number; sans_adresse: number }[];
}

/** Suivi départemental : une intercommunalité dépliée. */
export interface SuiviBranche {
  code: string; nom: string; enrolement: Enrolement | null; pics: Avancement | null; institution: FicheArbre | null;
  communes: { code: string; nom: string; population: number | null; enrolement: Enrolement; pcs: Avancement | null; mairie: FicheArbre | null }[];
}

@Injectable({ providedIn: 'root' })
export class DelegationGestionService {
  private url = `${environment.apiUrl}/delegations-gestion`;

  constructor(private http: HttpClient) {}

  lister(): Observable<DelegationGestion[]> {
    return this.http.get<DelegationGestion[]>(`${this.url}/`);
  }

  /** Multipart : la convention signée peut être jointe (PDF). */
  creer(donnees: FormData): Observable<DelegationGestion> {
    return this.http.post<DelegationGestion>(`${this.url}/`, donnees);
  }

  /** `forcer` : confirmer un retrait pendant une crise ouverte sur le territoire. */
  retirer(id: string, motif: string, forcer = false): Observable<DelegationGestion> {
    return this.http.post<DelegationGestion>(`${this.url}/${id}/retirer/`, { motif, forcer });
  }

  amorcer(id: string, etapes?: string[]): Observable<EtatAmorcage> {
    return this.http.post<EtatAmorcage>(`${this.url}/${id}/amorcer/`, etapes ? { etapes } : {});
  }

  amorcage(id: string): Observable<EtatAmorcage | null> {
    return this.http.get<EtatAmorcage | null>(`${this.url}/${id}/amorcage/`);
  }

  /** Invite les collectivités choisies (mairies, EPCI) à rejoindre la plateforme. */
  inviterCollectivites(id: string, institutions: string[]): Observable<{ envoyees: number; sans_email: string[]; deja_membres: number }> {
    return this.http.post<{ envoyees: number; sans_email: string[]; deja_membres: number }>(
      `${this.url}/${id}/inviter-collectivites/`, { institutions });
  }

  /** Corrige les coordonnées officielles d'une collectivité et/ou indique sa personne référente. */
  coordonnees(id: string, institution: string, officiel: { email?: string; telephone?: string } | null,
              referent: Referent | null): Observable<{ ok: boolean }> {
    const corps: any = { institution };
    if (officiel) corps.officiel = officiel;
    if (referent) corps.referent = referent;
    return this.http.post<{ ok: boolean }>(`${this.url}/${id}/coordonnees/`, corps);
  }

  /** Coordonnées des collectivités cochées, en tableur CSV (journalisé côté serveur). */
  exporterCoordonnees(id: string, institutions: string[]): Observable<Blob> {
    return this.http.post(`${this.url}/${id}/export-coordonnees/`, { institutions }, { responseType: 'blob' });
  }

  preparerInvitation(id: string, institutions: string[]): Observable<PreparationInvitation> {
    return this.http.post<PreparationInvitation>(`${this.url}/${id}/preparer-invitation/`, { institutions });
  }

  apercuInvitation(id: string, institution: string, sujet: string, corps: string, connecteur: string): Observable<ApercuInvitation> {
    return this.http.post<ApercuInvitation>(`${this.url}/${id}/campagne-invitation/`, { apercu: institution, sujet, corps, connecteur });
  }

  lancerCampagne(id: string, institutions: string[], sujet: string, corps: string, connecteur: string): Observable<CampagneInvitation> {
    return this.http.post<CampagneInvitation>(`${this.url}/${id}/campagne-invitation/`, { institutions, sujet, corps, connecteur });
  }

  campagnes(id: string): Observable<CampagneInvitation[]> {
    return this.http.get<CampagneInvitation[]>(`${this.url}/${id}/campagnes/`);
  }

  historique(id: string): Observable<EvenementDelegation[]> {
    return this.http.get<EvenementDelegation[]>(`${this.url}/${id}/historique/`);
  }

  suivi(id: string): Observable<SuiviDepartement | null> {
    return this.http.get<SuiviDepartement | null>(`${this.url}/${id}/suivi/`);
  }

  suiviBranche(id: string, epci: string): Observable<SuiviBranche> {
    return this.http.get<SuiviBranche>(`${this.url}/${id}/suivi/`, { params: { epci } });
  }

  arborescence(id: string): Observable<Arborescence | null> {
    return this.http.get<Arborescence | null>(`${this.url}/${id}/arborescence/`);
  }

  repertoires(id: string): Observable<RepertoireEpci[]> {
    return this.http.get<RepertoireEpci[]>(`${this.url}/${id}/repertoires/`);
  }

  personnes(id: string): Observable<PersonneQuiAgit[]> {
    return this.http.get<PersonneQuiAgit[]>(`${this.url}/${id}/personnes/`);
  }

  inviter(id: string, emails: string[], fonction: string): Observable<{ invites: number }> {
    return this.http.post<{ invites: number }>(`${this.url}/${id}/inviter/`, { emails, fonction });
  }

  /** Archive ZIP de toutes les données de la collectivité (réversibilité). */
  exporter(institutionId: string): Observable<Blob> {
    return this.http.get(`${environment.apiUrl}/institutions/${institutionId}/export-donnees/`, { responseType: 'blob' });
  }

  /** Présence non détaillée des personnes vulnérables : cercles anonymisés et leur nombre. */
  presence(communeCode: string): Observable<{ situees: number; non_situees: number }> {
    return this.http.get<{ situees: number; non_situees: number }>(
      `${environment.apiUrl}/personnes-vulnerables/secteurs/`, { params: { commune_code: communeCode } });
  }
}
