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

@Injectable({ providedIn: 'root' })
export class AuditLogService {
  private url = `${environment.apiUrl}/audit-logs`;

  constructor(private http: HttpClient) {}

  forObject(objetType: string, objetId: string): Observable<AuditLogEntry[]> {
    return this.http.get<AuditLogEntry[]>(`${this.url}/`, { params: { objet_type: objetType, objet_id: objetId } });
  }
}
