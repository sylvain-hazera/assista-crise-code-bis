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
}

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
  sites: { source: string; statut: string; date_fin: string | null }[];
}

/** Une institution dans l'arborescence du département. */
export interface FicheArbre {
  id: string; nom: string; email: string | null; telephone: string | null; adresse: string | null;
  membres: number; delegation: boolean;
  /** Dernière invitation envoyée à la collectivité (« Rejoindre votre collectivité »). */
  invitee_le?: string | null;
}

/** Le département, ses intercommunalités et leurs communes. */
export interface Arborescence {
  departement: { code: string; nom: string; institution: FicheArbre | null };
  epcis: {
    code: string; nom: string; institution: FicheArbre | null;
    communes: { code: string; nom: string; population: number | null; mairie: FicheArbre | null }[];
  }[];
  totaux: { communes: number; mairies_sur_la_plateforme: number; epcis: number };
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
