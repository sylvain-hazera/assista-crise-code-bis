import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { PointOperationnel } from '../shared/models/point-operationnel.model';
import {
  CoordonneesDevoilees, LectureTerritoire, NiveauSecteur, ResultatImport, SaisieConvention,
  SiteSensible, SourceSiteSensible, SyntheseSitesSensibles,
} from '../shared/models/site-sensible.model';

@Injectable({ providedIn: 'root' })
export class SiteSensibleService {
  private url = `${environment.apiUrl}/sites-sensibles`;

  constructor(private http: HttpClient) {}

  getAll(filtres: Record<string, string> = {}): Observable<SiteSensible[]> {
    return this.http.get<SiteSensible[]>(`${this.url}/`, { params: filtres });
  }

  synthese(): Observable<SyntheseSitesSensibles> {
    return this.http.get<SyntheseSitesSensibles>(`${this.url}/synthese/`);
  }

  /** Lance l'import des sources demandées. FINESS et SIRENE partent en tâche de fond
   * (`asynchrone: true`) : leur état se suit en rappelant `synthese`.
   *
   * `themes` ne concerne que SIRENE : ce sont les thèmes à recenser (élevages, autocars,
   * hébergement…). `perimetre` vaut « commune » par défaut et ne peut pas dépasser le niveau de
   * la collectivité — le serveur refuse, la page ne propose que le possible. */
  importer(sources: SourceSiteSensible[], themes?: string[],
           perimetre?: NiveauSecteur): Observable<ResultatImport> {
    const corps: { sources: SourceSiteSensible[]; themes?: string[]; perimetre?: NiveauSecteur } =
      { sources };
    if (themes?.length) corps.themes = themes;
    if (perimetre) corps.perimetre = perimetre;
    return this.http.post<ResultatImport>(`${this.url}/importer/`, corps);
  }

  /** Les sites RETENUS par les autres collectivités du secteur, en lecture seule. Un conseil
   * départemental les lit chez elles au lieu de recopier 5 000 lignes qui seraient figées au
   * jour de l'import. La consultation est inscrite à la main courante. */
  territoire(communeCode?: string): Observable<LectureTerritoire> {
    const params: Record<string, string> = {};
    if (communeCode) params['commune_code'] = communeCode;
    return this.http.get<LectureTerritoire>(`${this.url}/territoire/`, { params });
  }

  /** Dévoile l'adresse et les coordonnées d'une personne en nom propre. Appel serveur
   * délibéré : il écrit une ligne de main courante, ce qu'une bascule d'affichage ne ferait
   * pas. */
  devoiler(id: string): Observable<CoordonneesDevoilees> {
    return this.http.get<CoordonneesDevoilees>(`${this.url}/${id}/devoiler/`);
  }

  /** Enregistre la convention, en multipart dès qu'un document est joint. Les dates vides sont
   * omises : l'API attend une date ou rien, pas une chaîne vide. */
  enregistrerConvention(id: string, saisie: SaisieConvention,
                        fichier?: File | null): Observable<SiteSensible> {
    if (!fichier) {
      return this.update(id, {
        convention_existe: saisie.convention_existe,
        convention_numero: saisie.convention_numero || null,
        convention_date_signature: saisie.convention_date_signature || null,
        convention_echeance: saisie.convention_echeance || null,
      });
    }
    const corps = new FormData();
    corps.append('convention_existe', String(saisie.convention_existe));
    if (saisie.convention_numero) corps.append('convention_numero', saisie.convention_numero);
    if (saisie.convention_date_signature) {
      corps.append('convention_date_signature', saisie.convention_date_signature);
    }
    if (saisie.convention_echeance) {
      corps.append('convention_echeance', saisie.convention_echeance);
    }
    corps.append('convention_document', fichier, fichier.name);
    return this.http.patch<SiteSensible>(`${this.url}/${id}/`, corps);
  }

  /** Télécharge la convention signée. Passe par le jeton comme tout le reste : le fichier est
   * déchiffré par le serveur après contrôle d'accès, et la consultation est tracée. */
  telechargerConvention(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/telecharger-convention/`, { responseType: 'blob' });
  }

  update(id: string, data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.patch<SiteSensible>(`${this.url}/${id}/`, data);
  }

  create(data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.post<SiteSensible>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  creerPoint(id: string, data: { type: string; capacite_accueil?: number | null }): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.url}/${id}/creer-point/`, data);
  }
}
