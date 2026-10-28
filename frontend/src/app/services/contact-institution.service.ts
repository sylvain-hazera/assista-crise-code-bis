import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ContactInstitution } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class ContactInstitutionService {

  private url = `${environment.apiUrl}/contacts-institutions`;

  constructor(private http: HttpClient) {}

  /** Mes rattachements et ceux des institutions dont je suis membre.
   *
   * Depuis le 28/10/2026, cet endpoint ne renvoie PLUS la table entière : il n'était protégé
   * que par « être authentifié », si bien qu'un citoyen pouvait lister les noms, emails et
   * fonctions des contacts de toutes les institutions de la plateforme. Une page qui a besoin
   * des contacts d'une AUTRE institution doit maintenant les demander nommément — voir
   * getForInstitution. */
  getAll(): Observable<ContactInstitution[]> {
    return this.http.get<ContactInstitution[]>(`${this.url}/`);
  }

  /** Les contacts d'UNE institution. Permis à un rôle institutionnel même sans en être
   * membre : désigner le responsable d'une institution qu'on déclare actrice sur une crise
   * suppose de voir ses contacts. C'est la question ciblée qui reste ouverte, pas la liste. */
  getForInstitution(institutionId: string): Observable<ContactInstitution[]> {
    return this.http.get<ContactInstitution[]>(`${this.url}/`, {
      params: { institution: institutionId },
    });
  }

  create(data: Partial<ContactInstitution>): Observable<ContactInstitution> {
    return this.http.post<ContactInstitution>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<ContactInstitution>): Observable<ContactInstitution> {
    return this.http.put<ContactInstitution>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
