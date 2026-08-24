import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PointType } from '../shared/models/point-operationnel.model';

@Injectable({ providedIn: 'root' })
export class PointTypeService {
  private apiUrl = `${environment.apiUrl}/point-types`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<PointType[]> {
    return this.http.get<PointType[]>(`${this.apiUrl}/`);
  }
}
