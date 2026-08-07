import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { InstitutionType } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class InstitutionTypeService {

  private url = `${environment.apiUrl}/institution-types`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<InstitutionType[]> {
    return this.http.get<InstitutionType[]>(`${this.url}/`);
  }

  create(data: Partial<InstitutionType>): Observable<InstitutionType> {
    return this.http.post<InstitutionType>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<InstitutionType>): Observable<InstitutionType> {
    return this.http.put<InstitutionType>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
