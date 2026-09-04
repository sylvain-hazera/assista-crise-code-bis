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
}

export interface DashboardStats {
  stats: DashboardCounts;
  previous: DashboardCounts;
  totals: DashboardCounts;
  day_points: DashboardDayPoint[];
  pie: DashboardPieSlice[];
  recent_items: DashboardRecentItem[];
  total_items: number;
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
