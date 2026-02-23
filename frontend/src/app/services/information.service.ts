import { Injectable } from '@angular/core';
import { environment } from '../../environments/environment';
import { HttpClient } from '@angular/common/http';
import { Information } from '../shared/models/information.model';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class InformationService {
  private apiUrl = `${environment.apiUrl}/informations`;
  constructor(private http: HttpClient) { }

  getInformations(params?: any): Observable<Information[]> {
    return this.http.get<Information[]>(`${this.apiUrl}/`, { params });
  }

  getInformation(id: string): Observable<Information> {
    return this.http.get<Information>(`${this.apiUrl}/${id}/`);
  }

  createInformation(data: Partial<Information> | FormData): Observable<Information> {
    return this.http.post<Information>(`${this.apiUrl}/`, data);
  }

  updateInformation(id: string, data: Partial<Information> | FormData): Observable<Information> {
    return this.http.put<Information>(`${this.apiUrl}/${id}/`, data);
  }

  deleteInformation(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
