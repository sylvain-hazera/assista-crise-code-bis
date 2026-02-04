import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offer } from '../shared/models/offer.model';

@Injectable({
  providedIn: 'root'
})
export class OfferService {
  private apiUrl = `${environment.apiUrl}/offres`;

  constructor(private http: HttpClient) {}

  getAllOffers(): Observable<Offer[]> {
    return this.http.get<Offer[]>(this.apiUrl);
  }

  getOffers(params?: any): Observable<Offer[]> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach(key => {
        httpParams = httpParams.set(key, params[key]);
      });
    }
    return this.http.get<Offer[]>(this.apiUrl, { params: httpParams });
  }

  getOfferStats(filter?: any): Observable<any> {
    let httpParams = new HttpParams();
    if (filter) {
      Object.keys(filter).forEach(key => {
        httpParams = httpParams.set(key, filter[key]);
      });
    }
    return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  }

  // getOffers(params?: any): Observable<Offer[]> {
  //   return this.http.get<Offer[]>(`${this.apiUrl}/offres/`, { params });
  // }

  getOffer(id: string): Observable<Offer> {
    return this.http.get<Offer>(`${this.apiUrl}/offres/${id}/`);
  }

  createOffer(data: Partial<Offer> | FormData): Observable<Offer> {
    return this.http.post<Offer>(`${this.apiUrl}/offres/`, data);
  }

  updateOffer(id: string, data: Partial<Offer> | FormData): Observable<Offer> {
    return this.http.put<Offer>(`${this.apiUrl}/offres/${id}/`, data);
  }

  deleteOffer(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/offres/${id}/`);
  }
}