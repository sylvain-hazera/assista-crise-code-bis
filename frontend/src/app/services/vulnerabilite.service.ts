import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { TypeVulnerabilite, PersonneVulnerable, AdresseDeLaCommune, EtatRattachement, ExpositionRegistre } from '../shared/models/vulnerabilite.model';
import {
  EtatRegistreVulnerables,
  HabilitationRegistre,
  QualiteDesignataire,
} from '../shared/models/habilitation-registre.model';

@Injectable({ providedIn: 'root' })
export class TypeVulnerabiliteService {
  private url = `${environment.apiUrl}/types-vulnerabilite`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<TypeVulnerabilite[]> {
    return this.http.get<TypeVulnerabilite[]>(`${this.url}/`);
  }

  search(query: string): Observable<TypeVulnerabilite[]> {
    return this.http.get<TypeVulnerabilite[]>(`${this.url}/`, { params: { q: query } });
  }

  create(data: Partial<TypeVulnerabilite>): Observable<TypeVulnerabilite> {
    return this.http.post<TypeVulnerabilite>(`${this.url}/`, data);
  }
}

@Injectable({ providedIn: 'root' })
export class PersonneVulnerableService {
  private url = `${environment.apiUrl}/personnes-vulnerables`;

  constructor(private http: HttpClient) {}

  getAll(params?: Record<string, string>): Observable<PersonneVulnerable[]> {
    return this.http.get<PersonneVulnerable[]>(`${this.url}/`, { params });
  }

  get(id: string): Observable<PersonneVulnerable> {
    return this.http.get<PersonneVulnerable>(`${this.url}/${id}/`);
  }

  create(data: Partial<PersonneVulnerable>): Observable<PersonneVulnerable> {
    return this.http.post<PersonneVulnerable>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<PersonneVulnerable>): Observable<PersonneVulnerable> {
    return this.http.patch<PersonneVulnerable>(`${this.url}/${id}/`, data);
  }

  radier(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** Les adresses de la commune qui correspondent à ce qu'on tape. La recherche se fait dans
   * le relevé gardé sur notre serveur : l'adresse d'une personne vulnérable ne part nulle part. */
  chercherAdresses(q: string, communeCode?: string): Observable<{ releve_disponible: boolean; adresses: AdresseDeLaCommune[] }> {
    const params: Record<string, string> = communeCode ? { q, commune_code: communeCode } : { q };
    return this.http.get<{ releve_disponible: boolean; adresses: AdresseDeLaCommune[] }>(`${this.url}/adresses/`, { params });
  }

  rattachement(communeCode?: string): Observable<EtatRattachement> {
    const params: Record<string, string> = communeCode ? { commune_code: communeCode } : {};
    return this.http.get<EtatRattachement>(`${this.url}/rattachement/`, { params });
  }

  /** Rattache la fiche à une adresse de la commune ; `banId` vide la détache. */
  rattacher(id: string, banId: string): Observable<PersonneVulnerable> {
    return this.http.post<PersonneVulnerable>(`${this.url}/${id}/rattacher/`, { ban_id: banId });
  }

  /** Rattache d'un coup les fiches dont l'adresse est mot pour mot une adresse du relevé. */
  rattacherExactes(communeCode?: string): Observable<EtatRattachement> {
    return this.http.post<EtatRattachement>(`${this.url}/rattacher-exactes/`, communeCode ? { commune_code: communeCode } : {});
  }

  exposition(communeCode?: string): Observable<ExpositionRegistre> {
    const params: Record<string, string> = communeCode ? { commune_code: communeCode } : {};
    return this.http.get<ExpositionRegistre>(`${this.url}/exposition/`, { params });
  }

  /** Pour la carte : un cercle par personne du registre, jamais un point. Réservé aux personnes
   * habilitées. Les cercles ne portent aucune propriété ; `libelle` est le seul texte à montrer. */
  secteurs(communeCode?: string): Observable<SecteursVulnerables> {
    const params: Record<string, string> = communeCode ? { commune_code: communeCode } : {};
    return this.http.get<SecteursVulnerables>(`${this.url}/secteurs/`, { params });
  }

  /** Le registre d'une commune, mis en page pour l'impression. Sans `communeCode`, le serveur
   * prend la commune de l'institution de la personne connectée. Construit à la demande, jamais
   * stocké, et réservé à qui tient le registre (désigné et engagé au secret). */
  pdf(communeCode?: string): Observable<Blob> {
    const params: Record<string, string> = communeCode ? { commune_code: communeCode } : {};
    return this.http.get(`${this.url}/pdf/`, { params, responseType: 'blob' });
  }
}

/**
 * Habilitations nominatives au registre des personnes vulnérables (art. R. 121-7 du CASF).
 *
 * `monEtat` est le seul point d'entrée de la page du registre : c'est lui qui dit s'il faut
 * présenter le disclaimer bloquant, et qui fournit les deux textes juridiques. Ils ne sont pas
 * recopiés côté front à dessein — un texte que l'on fait signer doit avoir une version et une
 * seule origine, sinon on ne sait plus ce qui a été signé.
 */
@Injectable({ providedIn: 'root' })
export class HabilitationRegistreService {
  private url = `${environment.apiUrl}/habilitations-registre-vulnerables`;

  constructor(private http: HttpClient) {}

  monEtat(): Observable<EtatRegistreVulnerables> {
    return this.http.get<EtatRegistreVulnerables>(`${this.url}/mon-etat/`);
  }

  signerEngagement(): Observable<{ engagement_signe: boolean; engagement_signe_le: string }> {
    return this.http.post<{ engagement_signe: boolean; engagement_signe_le: string }>(
      `${this.url}/signer-engagement/`, { accepte: true });
  }

  getAll(params?: Record<string, string>): Observable<HabilitationRegistre[]> {
    return this.http.get<HabilitationRegistre[]>(`${this.url}/`, { params });
  }

  /** `institution` n'est pas envoyée : le serveur impose celle du désignant, pour qu'on ne
   * puisse pas désigner quelqu'un sur le registre d'une autre commune. */
  designer(data: {
    utilisateur: string;
    qualite_accordant: QualiteDesignataire;
    attestation_accordant: true;
    fonction?: string;
    date_fin?: string | null;
  }): Observable<HabilitationRegistre> {
    return this.http.post<HabilitationRegistre>(`${this.url}/`, data);
  }

  /** Retrait et non suppression : la trace de qui était habilité, par qui et jusqu'à quand est
   * ce qui permet de répondre plus tard à « qui avait accès le jour de la canicule ? ». */
  retirer(id: string, motif: string): Observable<HabilitationRegistre> {
    return this.http.post<HabilitationRegistre>(`${this.url}/${id}/retirer/`, { motif });
  }

  candidats(): Observable<CandidatHabilitation[]> {
    return this.http.get<CandidatHabilitation[]>(`${this.url}/candidats/`);
  }
}

/** Une personne désignable. `rcsc` ne confère aucun droit : il ne sert qu'à faire remonter en
 * tête ceux qu'un maire cherche en premier (voir l'action `candidats` côté backend). */
export interface CandidatHabilitation {
  id: string;
  nom: string;
  email: string;
  deja_habilite: boolean;
  rcsc: boolean;
}

/** Les secteurs « personne sensible dans les environs » (core/secteurs_vulnerables.py). */
export interface SecteursVulnerables {
  type: 'FeatureCollection';
  features: { type: 'Feature'; properties: Record<string, never>; geometry: { type: 'Polygon'; coordinates: number[][][] } }[];
  libelle: string;
  situees: number;
  non_situees: number;
  releve_disponible: boolean;
}
