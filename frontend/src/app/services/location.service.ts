import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';

export interface Department {
  code: string;
  nom: string;
}

export interface Commune {
  code: string;
  nom: string;
  codesPostaux: string[];
  codeDepartement: string;
}

@Injectable({
  providedIn: 'root'
})
export class LocationService {
  private readonly API_GEO = 'https://geo.api.gouv.fr';

  constructor(private http: HttpClient) {}

  /**
   * Récupérer la liste de tous les départements
   */
  getDepartments(): Observable<Department[]> {
    return this.http.get<Department[]>(`${this.API_GEO}/departements`)
      .pipe(
        map(deps => deps.sort((a, b) => a.nom.localeCompare(b.nom)))
      );
  }

  /**
   * Récupérer les communes d'un département
   */
  getCommunesByDepartment(departmentCode: string): Observable<Commune[]> {
    return this.http.get<Commune[]>(
      `${this.API_GEO}/departements/${departmentCode}/communes?fields=nom,code,codesPostaux,codeDepartement`
    ).pipe(
      map(communes => communes.sort((a, b) => a.nom.localeCompare(b.nom)))
    );
  }

  /**
   * Rechercher des départements par nom
   */
  searchDepartments(query: string, departments: Department[]): Department[] {
    if (!query) return departments;
    const searchTerm = query.toLowerCase();
    return departments.filter(dep => 
      dep.nom.toLowerCase().includes(searchTerm) || 
      dep.code.includes(searchTerm)
    );
  }

  /**
   * Rechercher des communes par nom
   */
  searchCommunes(query: string, communes: Commune[]): Commune[] {
    if (!query) return communes;
    const searchTerm = query.toLowerCase();
    return communes.filter(commune => 
      commune.nom.toLowerCase().includes(searchTerm) ||
      commune.codesPostaux.some(cp => cp.includes(searchTerm))
    );
  }
}
