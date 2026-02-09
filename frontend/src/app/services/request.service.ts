import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Request, RequestType } from '../shared/models/request.model';



// interface Request {
//   id?: number;
//   eventType: string;
//   needType: string[];
//   description: string[];
//   streetNumber: string;
//   postalCode: string;
//   addressVisible: boolean;
//   image?: File;
//   createdAt?: Date;
// }

@Injectable({
  providedIn: 'root'
})
export class RequestService {
  private apiUrl = `${environment.apiUrl}/demandes`;

  constructor(private http: HttpClient) {}

  createRequest(formData: FormData): Observable<Request> {
    return this.http.post<Request>(`${this.apiUrl}/`, formData);
  }

  getAllRequests(): Observable<Request[]> {
    return this.http.get<Request[]>(this.apiUrl);
  }

  getRequests(params?: any): Observable<Request[]> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach(key => {
        httpParams = httpParams.set(key, params[key]);
      });
    }
    return this.http.get<Request[]>(this.apiUrl, { params: httpParams });
  }

  getMyRequests(): Observable<Request[]> {
    return this.http.get<Request[]>(`${this.apiUrl}/my_requests/`);
  }
  
  getRequest(id: string): Observable<Request> {
    return this.http.get<Request>(`${this.apiUrl}/${id}/`);
  }

  updateRequest(id: string, formData: FormData): Observable<Request> {
    return this.http.put<Request>(`${this.apiUrl}/${id}/`, formData);
  }

  deleteRequest(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  getRequestStats(filter?: any): Observable<any> {
    let httpParams = new HttpParams();
    if (filter) {
      Object.keys(filter).forEach(key => {
        httpParams = httpParams.set(key, filter[key]);
      });
    }
    return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  }

  getTypesDemande(): Observable<RequestType[]> {
    return this.http.get<RequestType[]>(`${environment.apiUrl}/types-demande`);
  }
}