import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, forkJoin, map, of } from 'rxjs';
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

  /** Recherche de communes sur toute la France (autocomplétion) par nom, code postal ou code
   * INSEE — pas besoin de connaître le département au préalable. Un code à 5 chiffres est
   * ambigu (ex: "33503" est un code INSEE, "33680" un code postal, tous deux plausibles) : on
   * interroge les deux en parallèle plutôt que de deviner lequel l'utilisateur a saisi. Code
   * INSEE de Corse (2A/2B + 3 chiffres) détecté séparément, non numérique. */
  searchCommunesByName(query: string): Observable<Commune[]> {
    const q = query.trim();
    if (!q) return of([]);

    const fields = 'nom,code,codesPostaux,codeDepartement';
    const toCommunes = (list: any[]) => (list || []).map(c => ({ ...c, name: c.nom }));

    if (/^\d{5}$/.test(q)) {
      return forkJoin({
        parCode: this.http.get<any[]>(`${this.API_GEO}/communes?code=${q}&fields=${fields}`),
        parCodePostal: this.http.get<any[]>(`${this.API_GEO}/communes?codePostal=${q}&fields=${fields}&boost=population&limit=10`),
      }).pipe(
        map(({ parCode, parCodePostal }) => {
          const merged = [...toCommunes(parCode), ...toCommunes(parCodePostal)];
          const seen = new Set<string>();
          return merged.filter(c => (seen.has(c.code) ? false : (seen.add(c.code), true)));
        })
      );
    }

    if (/^2[ab][0-9]{3}$/i.test(q)) {
      return this.http.get<any[]>(`${this.API_GEO}/communes?code=${q.toUpperCase()}&fields=${fields}`)
        .pipe(map(toCommunes));
    }

    return this.http.get<any[]>(
      `${this.API_GEO}/communes?nom=${encodeURIComponent(q)}&fields=${fields}&boost=population&limit=10`
    ).pipe(map(toCommunes));
  }

  /** Nom d'une commune depuis son seul code INSEE — plus léger que getCommuneContour quand on
   * n'a pas besoin du contour (ex: affichage d'un code déjà enregistré, voir TeamsComponent). */
  getCommuneName(code: string): Observable<{ code: string; name: string }> {
    return this.http.get<any>(`${this.API_GEO}/communes/${code}?fields=nom,code`)
      .pipe(map(c => ({ code: c.code, name: c.nom })));
  }

  /** Nom d'un département depuis son seul code, même usage que getCommuneName. */
  getDepartementName(code: string): Observable<{ code: string; name: string }> {
    return this.http.get<any>(`${this.API_GEO}/departements/${code}?fields=nom,code`)
      .pipe(map(d => ({ code: d.code, name: d.nom })));
  }

  /** Centre géographique (point) d'une commune depuis son code INSEE — pour un filtre par
   * rayon (ex: zone de recherche hébergement), plus léger qu'un contour à bufferiser. */
  getCommuneCentre(code: string): Observable<{ latitude: number; longitude: number }> {
    return this.http.get<any>(`${this.API_GEO}/communes/${code}?fields=centre`)
      .pipe(map(c => ({ latitude: c.centre.coordinates[1], longitude: c.centre.coordinates[0] })));
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
