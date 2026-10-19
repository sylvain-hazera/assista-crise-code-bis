import { Injectable } from '@angular/core';
import { User } from '../shared/models/user.model';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Form } from '@angular/forms';

@Injectable({
  providedIn: 'root'
})
export class UserService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) { }

  getAll(params?: any): Observable<User[]> {
    return this.http.get<User[]>(`${this.apiUrl}/users/`, { params });
  }
  
  getById(id: string): Observable<User> {
    return this.http.get<User>(`${this.apiUrl}/users/${id}/`);
  }
  
  create(data: Partial<User> | FormData): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/`, data);
  }
  
  update(id: string, data: Partial<User> | FormData): Observable<User> {
    return this.http.patch<User>(`${this.apiUrl}/users/${id}/`, data);
  }
  
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/users/${id}/`);
  }

  /** GET /api/users/<id>/preview/ — soi-même ou acteur institutionnel ; renvoie un blob. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/users/${id}/preview/`, { responseType: 'blob' });
  }

  /** POST /api/users/<id>/reactiver/ — réactive un compte désactivé (voir delete). */
  reactiver(id: string): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/${id}/reactiver/`, {});
  }

  sendPasswordReset(id: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/users/${id}/send_password_reset/`, {});
  }

  /** Comptes désactivés en attente de décision (inscriptions Secours). Un admin voit tout, une
   * mairie son code postal (filtré côté backend). */
  getPendingValidations(): Observable<User[]> {
    return this.http.get<User[]>(`${this.apiUrl}/users/pending_validations/`);
  }

  approveAccount(id: string): Observable<{ message: string; user: User }> {
    return this.http.post<{ message: string; user: User }>(`${this.apiUrl}/users/${id}/approve_account/`, {});
  }

  rejectAccount(id: string, reason?: string): Observable<{ message: string; user: User }> {
    return this.http.post<{ message: string; user: User }>(`${this.apiUrl}/users/${id}/reject_account/`, { reason });
  }

  /** GET /api/users/institution_suggestion/ — institution retrouvée pour le compte, sans
   * rattacher. `null` si rien. */
  institutionSuggestion(): Observable<{
    institution: { id: string; nom: string; type_libelle?: string | null } | null;
    // True si l'institution (mairie/EPCI/SDIS) doit encore accepter la convention de
    // sous-traitance RGPD.
    convention_requise: boolean;
    pending_institution_name: string | null;
    pending_commune_name: string | null;
    pending_commune_code: string | null;
  }> {
    return this.http.get<any>(`${this.apiUrl}/users/institution_suggestion/`);
  }

  /** POST /api/users/confirmer-institution/ — rattache le compte avec le rôle choisi.
   * `conventionAcceptee` exigé si `convention_requise: true`. */
  confirmerInstitution(roleCode: string, conventionAcceptee = false): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/confirmer-institution/`, {
      role_code: roleCode,
      convention_acceptee: conventionAcceptee,
    });
  }

  /** POST /api/users/creer-mon-institution/ — crée l'institution et y rattache le compte.
   * `convention_acceptee` exigé pour mairie/EPCI/SDIS. */
  creerMonInstitution(data: {
    nom: string; type: string; description?: string; telephone?: string;
    email?: string; adresse?: string; commune_code?: string; commune_nom?: string;
    role_code: string; convention_acceptee?: boolean;
  }): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/creer-mon-institution/`, data);
  }

  /** POST /api/users/actualiser-risques/ — rafraîchit les risques du territoire (sans cache). */
  actualiserRisques(): Observable<{
    risques: { num_risque: string; libelle_risque_long: string }[];
    risques_date_maj: string | null;
  }> {
    return this.http.post<any>(`${this.apiUrl}/users/actualiser-risques/`, {});
  }
}
