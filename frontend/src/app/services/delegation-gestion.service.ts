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
