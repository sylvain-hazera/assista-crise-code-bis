import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Mission } from '../shared/models/mission.model';

@Injectable({ providedIn: 'root' })
export class MissionService {
  private url = `${environment.apiUrl}/missions`;
  constructor(private http: HttpClient) {}

  getAll():                                   Observable<Mission[]> { return this.http.get<Mission[]>(`${this.url}/`); }
  getById(id: string):                        Observable<Mission>   { return this.http.get<Mission>(`${this.url}/${id}/`); }
  create(data: Partial<Mission>):              Observable<Mission>   { return this.http.post<Mission>(`${this.url}/`, data); }
  update(id: string, data: Partial<Mission>):  Observable<Mission>   { return this.http.put<Mission>(`${this.url}/${id}/`, data); }
  patch(id: string, data: Partial<Mission>):   Observable<Mission>   { return this.http.patch<Mission>(`${this.url}/${id}/`, data); }
  delete(id: string):                         Observable<void>      { return this.http.delete<void>(`${this.url}/${id}/`); }
}
