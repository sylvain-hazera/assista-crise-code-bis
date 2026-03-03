import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ValidationRequest {
  id?: string;
  userId: string;
  userEmail: string;
  userName: string;
  userType: string;
  postalCode: string;
  requestDate: Date;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  validatedBy?: string;
  validationDate?: Date;
}

@Injectable({
  providedIn: 'root'
})
export class ValidationService {
  private apiUrl = `${environment.apiUrl}/validations`;

  constructor(private http: HttpClient) {}

  /**
   * Créer une demande de validation de compte
   */
  createValidationRequest(data: Partial<ValidationRequest>): Observable<ValidationRequest> {
    return this.http.post<ValidationRequest>(`${this.apiUrl}/`, data);
  }

  /**
   * Récupérer toutes les demandes de validation en attente (pour admins)
   */
  getPendingValidations(): Observable<ValidationRequest[]> {
    return this.http.get<ValidationRequest[]>(`${this.apiUrl}/?status=PENDING`);
  }

  /**
   * Récupérer les demandes de validation pour un code postal (pour institutions locales)
   */
  getValidationsByPostalCode(postalCode: string): Observable<ValidationRequest[]> {
    return this.http.get<ValidationRequest[]>(`${this.apiUrl}/?postalCode=${postalCode}&status=PENDING`);
  }

  /**
   * Approuver une demande de validation
   */
  approveValidation(requestId: string): Observable<ValidationRequest> {
    return this.http.post<ValidationRequest>(`${this.apiUrl}/${requestId}/approve/`, {});
  }

  /**
   * Rejeter une demande de validation
   */
  rejectValidation(requestId: string, reason?: string): Observable<ValidationRequest> {
    return this.http.post<ValidationRequest>(`${this.apiUrl}/${requestId}/reject/`, { reason });
  }

  /**
   * Envoyer une notification email aux admins (simulation)
   */
  notifyAdmins(validationRequest: ValidationRequest): Observable<any> {
    return this.http.post(`${this.apiUrl}/notify-admins/`, validationRequest);
  }

  /**
   * Envoyer une notification email à l'utilisateur
   */
  notifyUser(userId: string, status: 'approved' | 'rejected'): Observable<any> {
    return this.http.post(`${this.apiUrl}/notify-user/`, { userId, status });
  }
}
