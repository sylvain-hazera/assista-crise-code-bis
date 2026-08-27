import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, of } from 'rxjs';
import type { Polygon, MultiPolygon } from 'geojson';

export interface Department {
  code: string;
  name: string;
}

export interface Commune {
  code: string;
  name: string;
  codesPostaux: string[];
  codeDepartement: string;
}

export interface GeoContour {
  code: string;
  name: string;
  contour: Polygon | MultiPolygon;
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
    return this.http.get<any[]>(`${this.API_GEO}/departements`)
      .pipe(
        map(deps => deps.map(d => ({
          ...d,
          name: d.nom || d.name
        }))),
        map(deps => deps.sort((a, b) => a.name.localeCompare(b.name)))
      );
  }

  /**
   * Récupérer les communes d'un département
   */
  getCommunesByDepartment(departmentCode: string): Observable<Commune[]> {
    return this.http.get<any[]>(
      `${this.API_GEO}/departements/${departmentCode}/communes?fields=nom,code,codesPostaux,codeDepartement`
    ).pipe(
      map(communes => communes.map(c => ({
        ...c,
        name: c.nom || c.name
      }))),
      map(communes => communes.sort((a, b) => a.name.localeCompare(b.name)))
    );
  }

  /**
   * Rechercher des départements par nom
   */
  searchDepartments(query: string, departments: Department[]): Department[] {
    if (!query) return departments;
    const searchTerm = query.toLowerCase();
    return departments.filter(dep => 
      dep.name.toLowerCase().includes(searchTerm) || 
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
      commune.name.toLowerCase().includes(searchTerm) ||
      commune.codesPostaux.some(cp => cp.includes(searchTerm))
    );
  }

  /** Recherche de communes par nom sur toute la France (autocomplétion), pour la
   * composition de zone de crise — pas besoin de connaître le département au préalable. */
  searchCommunesByName(query: string): Observable<Commune[]> {
    if (!query.trim()) return of([]);
    return this.http.get<any[]>(
      `${this.API_GEO}/communes?nom=${encodeURIComponent(query)}&fields=nom,code,codesPostaux,codeDepartement&boost=population&limit=10`
    ).pipe(
      map(communes => communes.map(c => ({ ...c, name: c.nom })))
    );
  }

  /** Contour officiel (Polygon ou MultiPolygon) d'une commune, pour bufferiser/unioner
   * côté frontend (composition de la zone de crise). */
  getCommuneContour(code: string): Observable<GeoContour> {
    return this.http.get<any>(`${this.API_GEO}/communes/${code}?fields=nom,code,contour`)
      .pipe(map(c => ({ code: c.code, name: c.nom, contour: c.contour })));
  }

  /** Contour officiel d'un département, même usage que getCommuneContour. */
  getDepartementContour(code: string): Observable<GeoContour> {
    return this.http.get<any>(`${this.API_GEO}/departements/${code}?fields=nom,code,contour`)
      .pipe(map(d => ({ code: d.code, name: d.nom, contour: d.contour })));
  }
}
