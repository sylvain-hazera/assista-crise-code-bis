// src/app/shared/services/help-request.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface HelpRequestForm {
  id?: number;
  eventType: string;
  needType: string;
  description: string;
  streetNumber: string;
  postalCode: string;
  addressVisible: boolean;
  image?: File;
  createdAt?: Date;
}

@Injectable({
  providedIn: 'root'
})
export class HelpRequestFormService {
  private apiUrl = 'http://localhost:8000/api/help-requests';

  constructor(private http: HttpClient) {}

  createRequest(formData: FormData): Observable<HelpRequestForm> {
    return this.http.post<HelpRequestForm>(this.apiUrl, formData);
  }

  getRequests(): Observable<HelpRequestForm[]> {
    return this.http.get<HelpRequestForm[]>(this.apiUrl);
  }

  getRequest(id: number): Observable<HelpRequestForm> {
    return this.http.get<HelpRequestForm>(`${this.apiUrl}/${id}`);
  }

  updateRequest(id: number, formData: FormData): Observable<HelpRequestForm> {
    return this.http.put<HelpRequestForm>(`${this.apiUrl}/${id}`, formData);
  }

  deleteRequest(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }
}