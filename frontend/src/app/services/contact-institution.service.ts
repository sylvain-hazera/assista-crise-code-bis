import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ContactInstitution } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class ContactInstitutionService {

  private url = `${environment.apiUrl}/contacts-institutions`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<ContactInstitution[]> {
    return this.http.get<ContactInstitution[]>(`${this.url}/`);
  }

  create(data: Partial<ContactInstitution>): Observable<ContactInstitution> {
    return this.http.post<ContactInstitution>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<ContactInstitution>): Observable<ContactInstitution> {
    return this.http.put<ContactInstitution>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
