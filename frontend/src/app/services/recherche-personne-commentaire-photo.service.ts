import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class RecherchePersonneCommentairePhotoService {

  private apiUrl =
    '/api/recherches-personnes-commentaires-photos/';

  constructor(
    private http: HttpClient
  ) {}

  getAll(): Observable<any[]> {

    return this.http.get<any[]>(
      this.apiUrl
    );

  }

  create(
    data: FormData
  ): Observable<any> {

    return this.http.post(
      this.apiUrl,
      data
    );

  }

  delete(
    id: string
  ): Observable<any> {

    return this.http.delete(
      `${this.apiUrl}${id}/`
    );

  }

  /** GET .../<id>/preview/ — nécessite un JWT, donc un blob-fetch (pas un <img src> direct). */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}${id}/preview/`, { responseType: 'blob' });
  }

}

