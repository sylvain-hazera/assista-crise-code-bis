import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Team } from '../shared/models/team.model';  // ← import unique

@Injectable({ providedIn: 'root' })
export class TeamService {
  private url = `${environment.apiUrl}/teams`;
  constructor(private http: HttpClient) {}

  getAll():                                Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/`); }
  mesEquipes():                            Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/mes-equipes/`); }
  getById(id: string):                     Observable<Team>    { return this.http.get<Team>(`${this.url}/${id}/`); }
  create(data: Partial<Team>):             Observable<Team>    { return this.http.post<Team>(`${this.url}/`, data); }
  update(id: string, data: Partial<Team>): Observable<Team>    { return this.http.put<Team>(`${this.url}/${id}/`, data); }
  patch(id: string, data: Partial<Team>):  Observable<Team>    { return this.http.patch<Team>(`${this.url}/${id}/`, data); }
  delete(id: string):                      Observable<void>    { return this.http.delete<void>(`${this.url}/${id}/`); }
}