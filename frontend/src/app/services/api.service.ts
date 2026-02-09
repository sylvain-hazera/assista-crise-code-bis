import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

// Interfaces basées sur vos modèles Django

export interface Crise {
  id?: string;
  nom: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  date_debut?: string;
  date_fin?: string;
}

export interface TypeDemande {
  id?: string;
  type: string;
  description: string;
}

export interface Demande {
  id?: string;
  titre: string;
  photo?: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  prenom: string;
  nom: string;
  email: string;
  date_creation?: string;
  date_expiration?: string;
  statut: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
  type_demande: string; // UUID
  crise?: string; // UUID
  auteur?: string; // UUID
}

// export interface TypeInformation {
//   id?: string;
//   type: string;
//   description: string;
// }

// export interface Information {
//   id?: string;
//   titre: string;
//   photo?: string;
//   prenom: string;
//   nom: string;
//   email: string;
//   localisation: { type: 'Point'; coordinates: [number, number] };
//   date_creation?: string;
//   date_expiration?: string;
//   statut: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
//   type_information: string; // UUID
//   crise?: string; // UUID
//   auteur?: string; // UUID
// }

// export interface TypeOffre {
//   id?: string;
//   type: string;
//   description: string;
// }

// export interface Materiel {
//   id?: string;
//   photo?: string;
//   localisation: { type: 'Point'; coordinates: [number, number] };
//   emprunte: boolean;
//   date_emprunt?: string;
//   date_rendu?: string;
//   crise?: string; // UUID
//   emprunteur?: string; // UUID
// }

// export interface Offre {
//   id?: string;
//   date_creation?: string;
//   localisation: { type: 'Point'; coordinates: [number, number] };
//   prenom: string;
//   nom: string;
//   email: string;
//   titre: string;
//   photo?: string;
//   date_expiration?: string;
//   statut: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
//   type_offre: string; // UUID
//   crise?: string; // UUID
//   materiel?: string; // UUID
//   auteur?: string; // UUID
// }

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}


  // Crises

  // Types Demande
  // getTypesDemande(params?: any): Observable<TypeDemande[]> {
  //   return this.http.get<TypeDemande[]>(`${this.apiUrl}/types-demande/`, { params });
  // }

  // Demandes
  // getDemandes(params?: any): Observable<Demande[]> {
  //   return this.http.get<Demande[]>(`${this.apiUrl}/demandes/`, { params });
  // }

  // getDemande(id: string): Observable<Demande> {
  //   return this.http.get<Demande>(`${this.apiUrl}/demandes/${id}/`);
  // }

  // createDemande(data: Partial<Demande> | FormData): Observable<Demande> {
  //   return this.http.post<Demande>(`${this.apiUrl}/demandes/`, data);
  // }

  // updateDemande(id: string, data: Partial<Demande> | FormData): Observable<Demande> {
  //   return this.http.put<Demande>(`${this.apiUrl}/demandes/${id}/`, data);
  // }

  // deleteDemande(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/demandes/${id}/`);
  // }

  // Types Information
  // getTypesInformation(params?: any): Observable<TypeInformation[]> {
  //   return this.http.get<TypeInformation[]>(`${this.apiUrl}/types-information/`, { params });
  // }

  // Informations
  // getInformations(params?: any): Observable<Information[]> {
  //   return this.http.get<Information[]>(`${this.apiUrl}/informations/`, { params });
  // }

  // getInformation(id: string): Observable<Information> {
  //   return this.http.get<Information>(`${this.apiUrl}/informations/${id}/`);
  // }

  // createInformation(data: Partial<Information> | FormData): Observable<Information> {
  //   return this.http.post<Information>(`${this.apiUrl}/informations/`, data);
  // }

  // updateInformation(id: string, data: Partial<Information> | FormData): Observable<Information> {
  //   return this.http.put<Information>(`${this.apiUrl}/informations/${id}/`, data);
  // }

  // deleteInformation(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/informations/${id}/`);
  // }

  // Types Offre
  // getTypesOffre(params?: any): Observable<TypeOffre[]> {
  //   return this.http.get<TypeOffre[]>(`${this.apiUrl}/types-offre/`, { params });
  // }

  // Offres
  // getOffres(params?: any): Observable<Offre[]> {
  //   return this.http.get<Offre[]>(`${this.apiUrl}/offres/`, { params });
  // }

  // getOffre(id: string): Observable<Offre> {
  //   return this.http.get<Offre>(`${this.apiUrl}/offres/${id}/`);
  // }

  // createOffre(data: Partial<Offre> | FormData): Observable<Offre> {
  //   return this.http.post<Offre>(`${this.apiUrl}/offres/`, data);
  // }

  // updateOffre(id: string, data: Partial<Offre> | FormData): Observable<Offre> {
  //   return this.http.put<Offre>(`${this.apiUrl}/offres/${id}/`, data);
  // }

  // deleteOffre(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/offres/${id}/`);
  // }

  // Matériels
  // getMateriels(params?: any): Observable<Materiel[]> {
  //   return this.http.get<Materiel[]>(`${this.apiUrl}/materiels/`, { params });
  // }

  // getMateriel(id: string): Observable<Materiel> {
  //   return this.http.get<Materiel>(`${this.apiUrl}/materiels/${id}/`);
  // }

  // createMateriel(data: Partial<Materiel> | FormData): Observable<Materiel> {
  //   return this.http.post<Materiel>(`${this.apiUrl}/materiels/`, data);
  // }

  // updateMateriel(id: string, data: Partial<Materiel> | FormData): Observable<Materiel> {
  //   return this.http.put<Materiel>(`${this.apiUrl}/materiels/${id}/`, data);
  // }

  // deleteMateriel(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/materiels/${id}/`);
  // }
}
