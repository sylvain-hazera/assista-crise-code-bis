import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface AuditLogEntry {
  id: string;
  date_action: string;
  utilisateur_nom: string;
  action_libelle: string | null;
  objet_type: string;
  objet_id: string | null;
  commentaire: string | null;
}

export interface AuditLogAdminEntry {
  id: string;
  date_action: string;
  utilisateur_email: string | null;
  utilisateur_nom: string;
  institution_nom: string | null;
  adresse_ip: string | null;
  user_agent: string | null;
  action_code: string | null;
  action_libelle: string | null;
  objet_type: string;
  objet_id: string | null;
  commentaire: string | null;
  succes: boolean;
  environment: string;
}

export interface AuditLogFilters {
  date_debut?: string;
  date_fin?: string;
  action?: string;
  objet_type?: string;
  utilisateur?: string;
  succes?: string;
}

export interface AuditLogPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: AuditLogAdminEntry[];
}

@Injectable({ providedIn: 'root' })
export class AuditLogService {
  private url = `${environment.apiUrl}/audit-logs`;

  constructor(private http: HttpClient) {}

  forObject(objetType: string, objetId: string): Observable<AuditLogEntry[]> {
    return this.http.get<AuditLogEntry[]>(`${this.url}/`, { params: { objet_type: objetType, objet_id: objetId } });
  }

  /** Consultation globale de la main courante — réservée à un administrateur. */
  browse(filters: AuditLogFilters, page: number, pageSize = 50): Observable<AuditLogPage> {
    const params: Record<string, string> = { page: String(page), page_size: String(pageSize) };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    return this.http.get<AuditLogPage>(`${this.url}/`, { params });
  }

  /** GET /api/audit-logs/export/ — CSV, mêmes filtres que browse(). */
  exportCsv(filters: AuditLogFilters): Observable<Blob> {
    const params: Record<string, string> = {};
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    return this.http.get(`${this.url}/export/`, { params, responseType: 'blob' });
  }
}
