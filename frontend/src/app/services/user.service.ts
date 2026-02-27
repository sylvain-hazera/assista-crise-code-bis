import { Injectable } from '@angular/core';
import { Utilisateur } from '../shared/models/user.model';
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

  getAll(params?: any): Observable<Utilisateur[]> {
    return this.http.get<Utilisateur[]>(`${this.apiUrl}/users/`, { params });
  }
  
  getById(id: string): Observable<Utilisateur> {
    return this.http.get<Utilisateur>(`${this.apiUrl}/users/${id}/`);
  }
  
  create(data: Partial<Utilisateur> | FormData): Observable<Utilisateur> {
    return this.http.post<Utilisateur>(`${this.apiUrl}/users/`, data);
  }
  
  update(id: string, data: Partial<Utilisateur> | FormData): Observable<Utilisateur> {
    return this.http.put<Utilisateur>(`${this.apiUrl}/users/${id}/`, data);
  }
  
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/users/${id}/`);
  }
}
