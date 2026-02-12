import { Injectable } from '@angular/core';
import { Utilisateur } from '../shared/models/user.model';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class UserService {
  private apiUrl = environment.apiUrl;
  

  constructor(private http: HttpClient) { }

  getUsers(params?: any): Observable<Utilisateur[]> {
    return this.http.get<Utilisateur[]>(`${this.apiUrl}/users/`, { params });
  }
  
  getUser(id: string): Observable<Utilisateur> {
    return this.http.get<Utilisateur>(`${this.apiUrl}/users/${id}/`);
  }
  
  createUser(data: Partial<Utilisateur>): Observable<Utilisateur> {
    return this.http.post<Utilisateur>(`${this.apiUrl}/users/`, data);
  }
  
  updateUser(id: string, data: Partial<Utilisateur>): Observable<Utilisateur> {
    return this.http.put<Utilisateur>(`${this.apiUrl}/users/${id}/`, data);
  }
  
  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/users/${id}/`);
  }
}
