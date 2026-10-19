import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

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

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  // Crises

}
