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

  /** POST /api/users/<id>/reactiver/ — réactive un compte désactivé (voir delete). */
  reactiver(id: string): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/${id}/reactiver/`, {});
  }

  sendPasswordReset(id: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/users/${id}/send_password_reset/`, {});
  }

  /** Comptes créés mais désactivés en attente d'une décision (aujourd'hui : uniquement les
   * inscriptions Secours organisés — une mairie s'active elle-même par simple confirmation
   * d'email, voir AccountActivationView). Un admin voit tout ; une mairie ne voit que les
   * comptes de son propre code postal (filtrage fait côté backend). */
  getPendingValidations(): Observable<User[]> {
    return this.http.get<User[]>(`${this.apiUrl}/users/pending_validations/`);
  }

  approveAccount(id: string): Observable<{ message: string; user: User }> {
    return this.http.post<{ message: string; user: User }>(`${this.apiUrl}/users/${id}/approve_account/`, {});
  }

  rejectAccount(id: string, reason?: string): Observable<{ message: string; user: User }> {
    return this.http.post<{ message: string; user: User }>(`${this.apiUrl}/users/${id}/reject_account/`, { reason });
  }

  /** GET /api/users/institution_suggestion/ — institution retrouvée pour le compte connecté
   * (voir UserViewSet.institution_suggestion), sans rien rattacher. `null` si rien trouvé (à
   * créer soi-même, voir creerMonInstitution). */
  institutionSuggestion(): Observable<{
    institution: { id: string; nom: string; type_libelle?: string | null } | null;
    pending_institution_name: string | null;
    pending_commune_name: string | null;
    pending_commune_code: string | null;
  }> {
    return this.http.get<any>(`${this.apiUrl}/users/institution_suggestion/`);
  }

  /** POST /api/users/confirmer-institution/ — rattache le compte connecté à l'institution
   * retrouvée par institutionSuggestion, avec le rôle choisi. */
  confirmerInstitution(roleCode: string): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/confirmer-institution/`, { role_code: roleCode });
  }

  /** POST /api/users/creer-mon-institution/ — quand institutionSuggestion ne renvoie rien :
   * crée l'institution (mêmes champs que le formulaire admin) et y rattache le compte connecté
   * comme créateur, avec le rôle choisi. */
  creerMonInstitution(data: {
    nom: string; type: string; description?: string; telephone?: string;
    email?: string; adresse?: string; commune_code?: string; commune_nom?: string;
    role_code: string;
  }): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/creer-mon-institution/`, data);
  }

  /** POST /api/users/actualiser-risques/ — force le rafraîchissement des risques du territoire
   * de l'institution du compte connecté (ignore le cache, voir UserViewSet.actualiser_risques),
   * pour le bouton "Actualiser" de la Vue Ma Collectivité. */
  actualiserRisques(): Observable<{
    risques: { num_risque: string; libelle_risque_long: string }[];
    risques_date_maj: string | null;
  }> {
    return this.http.post<any>(`${this.apiUrl}/users/actualiser-risques/`, {});
  }
}
