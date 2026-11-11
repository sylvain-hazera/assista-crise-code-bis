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

  /** L'attestation PDF pour la VOIR, sans l'envoyer à personne.
   *
   * En blob et non par un lien direct : la route exige l'en-tête d'authentification posé par
   * l'intercepteur, qu'un `<a href>` n'enverrait pas. Avant cet ajout, la seule façon de voir
   * le document était de se l'envoyer par mail — ou de l'envoyer au destinataire pour
   * s'apercevoir après coup qu'une ligne était fausse. */
  previsualiserAttestation(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/${id}/attestation/`, { responseType: 'blob' });
  }

  /** Toutes les mobilisations d'une crise pour une institution, en CSV.
   *
   * `institution` est facultative : sans elle, l'extraction couvre toutes les institutions
   * dont l'appelant est membre. Le serveur applique son cloisonnement par-dessus, donc
   * passer l'identifiant d'une institution étrangère ne sort rien. */
  extraire(criseId: string, institutionId?: string): Observable<Blob> {
    const params: Record<string, string> = { crise: criseId };
    if (institutionId) { params['institution'] = institutionId; }
    return this.http.get(`${this.apiUrl}/extraction/`, { params, responseType: 'blob' });
  }
}
