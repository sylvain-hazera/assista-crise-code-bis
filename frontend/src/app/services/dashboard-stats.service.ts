import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface DashboardDayPoint {
  date: string;
  crises: number;
  offres: number;
  demandes: number;
}

export interface DashboardPieSlice {
  type: string;
  type_display: string;
  count: number;
}

export interface DashboardRecentItem {
  id: string;
  title: string;
  type: 'Crise' | 'Ressource' | 'Besoin';
  date: string;
  status: string;
}

export interface DashboardCounts {
  crises: number;
  offres: number;
  demandes: number;
  signalements: number;
  benevoles: number;
}

export interface DashboardNational {
  stats: DashboardCounts;
  previous: DashboardCounts;
}

export interface DashboardStats {
  stats: DashboardCounts;
  previous: DashboardCounts;
  totals: Pick<DashboardCounts, 'crises' | 'offres' | 'demandes'>;
  day_points: DashboardDayPoint[];
  pie: DashboardPieSlice[];
  recent_items: DashboardRecentItem[];
  total_items: number;
  /** Mêmes 5 métriques que "stats"/"previous", jamais scopées à une zone — alimente la 6ᵉ
   * fenêtre miniature. Identique à stats/previous quand is_zone_scoped est false. */
  national: DashboardNational;
  /** false pour un administrateur ou un utilisateur sans zone résolvable (pas
   * d'institution/commune) — "stats" est alors déjà national, la 6ᵉ fenêtre est redondante. */
  is_zone_scoped: boolean;
}

export type DashboardFilter = 'all' | 'week' | 'month' | 'quarter' | 'half_year' | 'year';

@Injectable({
  providedIn: 'root'
})
export class DashboardStatsService {
  private readonly url = `${environment.apiUrl}/stats/dashboard`;

  constructor(private http: HttpClient) {}

  getStats(filter: DashboardFilter = 'all'): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${this.url}/`, { params: { filter } });
  }
}
