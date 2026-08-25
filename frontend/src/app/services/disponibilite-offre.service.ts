import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DisponibiliteOffre, DisponibiliteOffrePayload } from '../shared/models/disponibilite-offre.model';

@Injectable({ providedIn: 'root' })
export class DisponibiliteOffreService {
  private apiUrl = `${environment.apiUrl}/disponibilites-offres`;

  constructor(private http: HttpClient) {}

  getByOffer(offerId: string): Observable<DisponibiliteOffre[]> {
    return this.http.get<DisponibiliteOffre[]>(`${this.apiUrl}/`, { params: { offer: offerId } });
  }

  create(payload: DisponibiliteOffrePayload): Observable<DisponibiliteOffre> {
    return this.http.post<DisponibiliteOffre>(`${this.apiUrl}/`, payload);
  }
}
