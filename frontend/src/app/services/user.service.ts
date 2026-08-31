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
}
