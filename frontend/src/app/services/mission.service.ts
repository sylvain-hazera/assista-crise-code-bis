import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Mission, OuvertureDossierGenerique } from '../shared/models/mission.model';
import { Dossier } from '../shared/models/dossier.model';

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

  /** Ouvre un dossier générique (sans demandeur) pour une mission d'intérêt général : c'est lui
   * qui porte le chat, les photos et la traçabilité de l'intervention. */
  ouvrirDossier(id: string, data: OuvertureDossierGenerique): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/ouvrir-dossier/`, data);
  }
}
