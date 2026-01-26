import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

// Interfaces basées sur vos modèles Django
export interface Utilisateur {
  id?: string;
  username: string;
  email: string;
  type: 'ADMIN' | 'AUT_LOCALE' | 'SECOURS' | 'UTIL_SIMPLE';
  photo?: string;
  telephone_utilisateur?: string;
}

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

export interface TypeInformation {
  id?: string;
  type: string;
}

export interface Information {
  id?: string;
  titre: string;
  photo?: string;
  prenom: string;
  nom: string;
  email: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  date_creation?: string;
  date_expiration?: string;
  statut: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
  type_information: string; // UUID
  crise?: string; // UUID
  auteur?: string; // UUID
}

export interface TypeOffre {
  id?: string;
  type: string;
}

export interface Materiel {
  id?: string;
  photo?: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  emprunte: boolean;
  date_emprunt?: string;
  date_rendu?: string;
  crise?: string; // UUID
  emprunteur?: string; // UUID
}

export interface Offre {
  id?: string;
  date_creation?: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  prenom: string;
  nom: string;
  email: string;
  titre: string;
  photo?: string;
  date_expiration?: string;
  statut: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
  type_offre: string; // UUID
  crise?: string; // UUID
  materiel?: string; // UUID
  auteur?: string; // UUID
}

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private baseUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  // Utilisateurs
  getUtilisateurs(params?: any): Observable<Utilisateur[]> {
    return this.http.get<Utilisateur[]>(`${this.baseUrl}/users/`, { params });
  }

  getUtilisateur(id: string): Observable<Utilisateur> {
    return this.http.get<Utilisateur>(`${this.baseUrl}/users/${id}/`);
  }

  createUtilisateur(data: Partial<Utilisateur>): Observable<Utilisateur> {
    return this.http.post<Utilisateur>(`${this.baseUrl}/users/`, data);
  }

  updateUtilisateur(id: string, data: Partial<Utilisateur>): Observable<Utilisateur> {
    return this.http.put<Utilisateur>(`${this.baseUrl}/users/${id}/`, data);
  }

  deleteUtilisateur(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/users/${id}/`);
  }

  // Crises
  getCrises(params?: any): Observable<Crise[]> {
    return this.http.get<Crise[]>(`${this.baseUrl}/crises/`, { params });
  }

  getCrise(id: string): Observable<Crise> {
    return this.http.get<Crise>(`${this.baseUrl}/crises/${id}/`);
  }

  createCrise(data: Partial<Crise>): Observable<Crise> {
    return this.http.post<Crise>(`${this.baseUrl}/crises/`, data);
  }

  updateCrise(id: string, data: Partial<Crise>): Observable<Crise> {
    return this.http.put<Crise>(`${this.baseUrl}/crises/${id}/`, data);
  }

  deleteCrise(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/crises/${id}/`);
  }

  // Types Demande
  getTypesDemande(params?: any): Observable<TypeDemande[]> {
    return this.http.get<TypeDemande[]>(`${this.baseUrl}/types-demande/`, { params });
  }

  // Demandes
  getDemandes(params?: any): Observable<Demande[]> {
    return this.http.get<Demande[]>(`${this.baseUrl}/demandes/`, { params });
  }

  getDemande(id: string): Observable<Demande> {
    return this.http.get<Demande>(`${this.baseUrl}/demandes/${id}/`);
  }

  createDemande(data: Partial<Demande> | FormData): Observable<Demande> {
    return this.http.post<Demande>(`${this.baseUrl}/demandes/`, data);
  }

  updateDemande(id: string, data: Partial<Demande> | FormData): Observable<Demande> {
    return this.http.put<Demande>(`${this.baseUrl}/demandes/${id}/`, data);
  }

  deleteDemande(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/demandes/${id}/`);
  }

  // Types Information
  getTypesInformation(params?: any): Observable<TypeInformation[]> {
    return this.http.get<TypeInformation[]>(`${this.baseUrl}/types-information/`, { params });
  }

  // Informations
  getInformations(params?: any): Observable<Information[]> {
    return this.http.get<Information[]>(`${this.baseUrl}/informations/`, { params });
  }

  getInformation(id: string): Observable<Information> {
    return this.http.get<Information>(`${this.baseUrl}/informations/${id}/`);
  }

  createInformation(data: Partial<Information> | FormData): Observable<Information> {
    return this.http.post<Information>(`${this.baseUrl}/informations/`, data);
  }

  updateInformation(id: string, data: Partial<Information> | FormData): Observable<Information> {
    return this.http.put<Information>(`${this.baseUrl}/informations/${id}/`, data);
  }

  deleteInformation(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/informations/${id}/`);
  }

  // Types Offre
  getTypesOffre(params?: any): Observable<TypeOffre[]> {
    return this.http.get<TypeOffre[]>(`${this.baseUrl}/types-offre/`, { params });
  }

  // Offres
  getOffres(params?: any): Observable<Offre[]> {
    return this.http.get<Offre[]>(`${this.baseUrl}/offres/`, { params });
  }

  getOffre(id: string): Observable<Offre> {
    return this.http.get<Offre>(`${this.baseUrl}/offres/${id}/`);
  }

  createOffre(data: Partial<Offre> | FormData): Observable<Offre> {
    return this.http.post<Offre>(`${this.baseUrl}/offres/`, data);
  }

  updateOffre(id: string, data: Partial<Offre> | FormData): Observable<Offre> {
    return this.http.put<Offre>(`${this.baseUrl}/offres/${id}/`, data);
  }

  deleteOffre(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/offres/${id}/`);
  }

  // Matériels
  getMateriels(params?: any): Observable<Materiel[]> {
    return this.http.get<Materiel[]>(`${this.baseUrl}/materiels/`, { params });
  }

  getMateriel(id: string): Observable<Materiel> {
    return this.http.get<Materiel>(`${this.baseUrl}/materiels/${id}/`);
  }

  createMateriel(data: Partial<Materiel> | FormData): Observable<Materiel> {
    return this.http.post<Materiel>(`${this.baseUrl}/materiels/`, data);
  }

  updateMateriel(id: string, data: Partial<Materiel> | FormData): Observable<Materiel> {
    return this.http.put<Materiel>(`${this.baseUrl}/materiels/${id}/`, data);
  }

  deleteMateriel(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/materiels/${id}/`);
  }
}
