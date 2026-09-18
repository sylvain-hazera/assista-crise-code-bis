import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AppNotification, ResumeNotifications } from '../shared/models/notification.model';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private apiUrl = `${environment.apiUrl}/notifications`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<AppNotification[]> {
    return this.http.get<AppNotification[]>(`${this.apiUrl}/`);
  }

  /** Appel léger destiné à un polling fréquent (voir pollWhileVisible) — ne rapatrie que
   * compteur + date, jamais la liste complète. */
  resume(): Observable<ResumeNotifications> {
    return this.http.get<ResumeNotifications>(`${this.apiUrl}/resume/`);
  }

  markAsRead(id: string): Observable<AppNotification> {
    return this.http.patch<AppNotification>(`${this.apiUrl}/${id}/`, { lu: true });
  }
}
