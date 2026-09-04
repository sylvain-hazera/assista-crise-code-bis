import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class RecherchePersonneHistoriqueService {

  private apiUrl =
    '/api/recherches-personnes-historique/';

  constructor(
    private http: HttpClient
  ) {}

  getAll() {
    return this.http.get<any[]>(
      this.apiUrl
    );
  }

}

