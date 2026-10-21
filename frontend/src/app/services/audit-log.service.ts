import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface AuditLogEntry {
  id: string;
  date_action: string;
  utilisateur_nom: string;
  action_libelle: string | null;
  objet_type: string;
  objet_id: string | null;
  commentaire: string | null;
}

export type Exposition = 'FICHE' | 'LISTE' | 'LISTE_SANS_COORDONNEES' | 'EXPORT';
export type Perimetre = 'CRISE' | 'MULTI' | 'GENERAL';

export interface AuditLogAdminEntry {
  id: string;
  date_action: string;
  utilisateur_id: string | null;
  utilisateur_email: string | null;
  utilisateur_nom: string;
  institution_id: string | null;
  institution_nom: string | null;
  adresse_ip: string | null;
  user_agent: string | null;
  action_code: string | null;
  action_libelle: string | null;
  objet_type: string;
  /** « Offre », « Compte »... pour les types de fiches connus (voir backend main_courante.TYPES_FICHES). */
  objet_type_libelle: string | null;
  objet_id: string | null;
  /** Libellé lu au moment de l'affichage, jamais recopié dans le journal ; « fiche supprimée » sinon. */
  objet_libelle: string | null;
  /** Liste ou export : nombre de fiches exposées par la requête. */
  nb_objets: number;
  exposition: Exposition | null;
  /** null : non déterminable (historique antérieur au 21/10/2026, lectures de listes surtout). */
  perimetre: Perimetre | null;
  crise_id: string | null;
  crise_nom: string | null;
  compte_systeme: boolean;
  /** Termes et filtres de recherche de la requête. */
  recherche: Record<string, string | string[]> | null;
  commentaire: string | null;
  succes: boolean;
  environment: string;
}

/** Critères acceptant plusieurs valeurs, chacune incluse ou exclue (voir backend main_courante.py :
 *  valeurs incluses = l'une OU l'autre, exclues = toutes écartées, critères entre eux = ET). */
export type CritereCle = 'utilisateur' | 'ip' | 'action' | 'objet_type' | 'objet' | 'institution' | 'crise' | 'recherche';

export interface Critere {
  cle: CritereCle;
  /** Ce qui part au serveur (email, IP ou plage, code d'action, identifiant...). */
  valeur: string;
  /** Ce qui s'affiche sur la pastille (libellé d'une fiche, nom d'une crise...). */
  libelle: string;
  exclu: boolean;
}

export interface AuditLogFilters {
  date_debut?: string;
  date_fin?: string;
  succes?: string;
  /** CRISE | MULTI | GENERAL | INCONNU */
  perimetre?: string;
  exposition?: string;
  masquer_systeme?: boolean;
  criteres: Critere[];
}

export interface AuditLogPage {
  count: number;
  /** true : il y a PLUS de `count` entrées -- le comptage s'arrête à 10 000, au-delà le
   *  compter exactement obligerait à relire tout le registre à chaque affichage (voir
   *  MainCourantePagination côté backend). La navigation s'appuie sur `next`, jamais sur `count`. */
  count_plafonne: boolean;
  next: string | null;
  previous: string | null;
  results: AuditLogAdminEntry[];
}

export interface FicheTrouvee {
  type: string;
  type_libelle: string;
  id: string;
  libelle: string;
}

export interface RechercheFiches {
  types: { type: string; libelle: string }[];
  resultats: FicheTrouvee[];
}

/** Paramètres d'URL/API d'un jeu de filtres -- les mêmes servent à l'API et à l'adresse de la
 *  page (un lien partagé rouvre exactement la même recherche). */
export function filtresVersParams(filtres: AuditLogFilters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  const ajouter = (cle: string, valeur: string) => {
    const existant = params[cle];
    params[cle] = existant === undefined ? valeur : [...(Array.isArray(existant) ? existant : [existant]), valeur];
  };
  if (filtres.date_debut) ajouter('date_debut', filtres.date_debut);
  if (filtres.date_fin) ajouter('date_fin', filtres.date_fin);
  if (filtres.succes) ajouter('succes', filtres.succes);
  if (filtres.perimetre) ajouter('perimetre', filtres.perimetre);
  if (filtres.exposition) ajouter('exposition', filtres.exposition);
  if (filtres.masquer_systeme) ajouter('masquer_systeme', '1');
  for (const c of filtres.criteres) ajouter(c.exclu ? `${c.cle}_exclu` : c.cle, c.valeur);
  return params;
}

export const CRITERES_CLES: CritereCle[] = ['utilisateur', 'ip', 'action', 'objet_type', 'objet', 'institution', 'crise', 'recherche'];

@Injectable({ providedIn: 'root' })
export class AuditLogService {
  private url = `${environment.apiUrl}/audit-logs`;

  constructor(private http: HttpClient) {}

  forObject(objetType: string, objetId: string): Observable<AuditLogEntry[]> {
    return this.http.get<AuditLogEntry[]>(`${this.url}/`, { params: { objet_type: objetType, objet_id: objetId } });
  }

  /** Consultation de la main courante -- générale pour le super-admin, celle de son institution sinon. */
  browse(filters: AuditLogFilters, page: number, pageSize = 50): Observable<AuditLogPage> {
    const params = new HttpParams({ fromObject: { ...filtresVersParams(filters), page: String(page), page_size: String(pageSize) } });
    return this.http.get<AuditLogPage>(`${this.url}/`, { params });
  }

  /** GET /api/audit-logs/export/ — CSV, mêmes filtres que browse(). */
  exportCsv(filters: AuditLogFilters): Observable<Blob> {
    const params = new HttpParams({ fromObject: filtresVersParams(filters) });
    return this.http.get(`${this.url}/export/`, { params, responseType: 'blob' });
  }

  /** GET /api/audit-logs/fiches/ — retrouver une fiche (annonce, personne, crise...) par son
   *  libellé, ses coordonnées ou son identifiant. Réservé au super-admin. */
  rechercherFiches(q: string, types: string[] = []): Observable<RechercheFiches> {
    let params = new HttpParams().set('q', q);
    types.forEach(t => params = params.append('type', t));
    return this.http.get<RechercheFiches>(`${this.url}/fiches/`, { params });
  }

  /** POST /api/audit-logs/tracer-export/ — un fichier fabriqué dans le navigateur à partir de
   *  données déjà chargées : le signaler pour qu'il figure dans la main courante, fiche par fiche. */
  tracerExport(objetType: string, ids: string[], fichier: string): Observable<void> {
    return this.http.post<void>(`${this.url}/tracer-export/`, { objet_type: objetType, ids, fichier });
  }
}
