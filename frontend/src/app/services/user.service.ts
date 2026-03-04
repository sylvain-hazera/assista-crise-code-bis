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
}
