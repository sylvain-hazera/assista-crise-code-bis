import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class RecherchePersonneService {

  private apiUrl = '/api/recherches-personnes/';

  constructor(
    private http: HttpClient
  ) {}

  getAll(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl);
  }

  getById(id: string): Observable<any> {
    return this.http.get<any>(
      `${this.apiUrl}${id}/`
    );
  }

  create(data: FormData): Observable<any> {
    return this.http.post(
      this.apiUrl,
      data
    );
  }

  update(
    id: string,
    data: any
  ): Observable<any> {
    return this.http.patch(
      `${this.apiUrl}${id}/`,
      data
    );

  }

  archiver(
    id: string
  ): Observable<any> {
 
    return this.http.post(
      `${this.apiUrl}${id}/archiver/`,
      {}
     );
  }

  retrouver(
    id: string
  ): Observable<any> {
  
    return this.http.post(
      `${this.apiUrl}${id}/retrouver/`,
      {}
    );

  }

  lecture(id: string) {
    return this.http.post(
      `${this.apiUrl}${id}/lecture/`,
      {}
    );
  }

  acquitter(id: string) {
    return this.http.post(
      `${this.apiUrl}${id}/acquitter/`,
      {}
    );
  }

  /** GET /api/recherches-personnes/<id>/preview/ — 403 si pas créateur/institutionnel. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}${id}/preview/`, { responseType: 'blob' });
  }

}




