import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DemandeMobilisation, DemandeMobilisationPayload } from '../shared/models/demande-mobilisation.model';

@Injectable({ providedIn: 'root' })
export class DemandeMobilisationService {
  private apiUrl = `${environment.apiUrl}/demandes-mobilisation`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<DemandeMobilisation[]> {
    return this.http.get<DemandeMobilisation[]>(`${this.apiUrl}/`);
  }

  create(data: DemandeMobilisationPayload): Observable<DemandeMobilisation> {
    return this.http.post<DemandeMobilisation>(`${this.apiUrl}/`, data);
  }

  revoquer(id: string): Observable<DemandeMobilisation> {
    return this.http.post<DemandeMobilisation>(`${this.apiUrl}/${id}/revoquer/`, {});
  }

  /** Génère l'attestation PDF (avec QR code de vérification) et l'envoie par email à l'adresse
   * connue du destinataire — voir DemandeMobilisationViewSet.envoyer_attestation. */
  envoyerAttestation(id: string): Observable<{ envoye_a: string }> {
    return this.http.post<{ envoye_a: string }>(`${this.apiUrl}/${id}/envoyer-attestation/`, {});
  }
}
