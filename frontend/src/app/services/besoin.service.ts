import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Besoin } from '../shared/models/besoin.model';

@Injectable({
  providedIn: 'root'
})
export class BesoinService {

  private url = `${environment.apiUrl}/besoins`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Besoin[]> {
    return this.http.get<Besoin[]>(`${this.url}/`);
  }
}
