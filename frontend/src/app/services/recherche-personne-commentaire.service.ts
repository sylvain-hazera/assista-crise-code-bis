import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class RecherchePersonneCommentaireService {

  private apiUrl =
    '/api/recherches-personnes-commentaires/';

  constructor(
    private http: HttpClient
  ) {}

  getAll() {
    return this.http.get<any[]>(
      this.apiUrl
    );
  }

  create(data: any) {
    return this.http.post(
      this.apiUrl,
      data
    );
  }
}
