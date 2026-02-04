import { Injectable } from '@angular/core';
import { User } from '../shared/models/user.model';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class UserService {
  private apiUrl = environment.apiUrl;
  

  constructor(private http: HttpClient) { }

  getUsers(params?: any): Observable<User[]> {
    return this.http.get<User[]>(`${this.apiUrl}/users/`, { params });
  }
  
  getUser(id: string): Observable<User> {
    return this.http.get<User>(`${this.apiUrl}/users/${id}/`);
  }
  
  createUser(data: Partial<User>): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/users/`, data);
  }
  
  updateUser(id: string, data: Partial<User>): Observable<User> {
    return this.http.put<User>(`${this.apiUrl}/users/${id}/`, data);
  }
  
  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/users/${id}/`);
  }
}
