import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { MaterielPoint, MaterielPointPayload } from '../shared/models/materiel-point.model';

@Injectable({ providedIn: 'root' })
export class MaterielPointService {
  private apiUrl = `${environment.apiUrl}/materiels-points`;

  constructor(private http: HttpClient) {}

  getByPoint(pointId: string): Observable<MaterielPoint[]> {
    return this.http.get<MaterielPoint[]>(`${this.apiUrl}/`, { params: { point: pointId } });
  }

  create(payload: MaterielPointPayload): Observable<MaterielPoint> {
    return this.http.post<MaterielPoint>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<MaterielPointPayload>): Observable<MaterielPoint> {
    return this.http.patch<MaterielPoint>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
