// src/app/shared/services/help-request.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface HelpRequest {
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
export class HelpRequestService {
  private apiUrl = 'http://localhost:8000/api/help-requests';

  constructor(private http: HttpClient) {}

  createRequest(formData: FormData): Observable<HelpRequest> {
    return this.http.post<HelpRequest>(this.apiUrl, formData);
  }

  getRequests(): Observable<HelpRequest[]> {
    return this.http.get<HelpRequest[]>(this.apiUrl);
  }

  getRequest(id: number): Observable<HelpRequest> {
    return this.http.get<HelpRequest>(`${this.apiUrl}/${id}`);
  }

  updateRequest(id: number, formData: FormData): Observable<HelpRequest> {
    return this.http.put<HelpRequest>(`${this.apiUrl}/${id}`, formData);
  }

  deleteRequest(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }
}