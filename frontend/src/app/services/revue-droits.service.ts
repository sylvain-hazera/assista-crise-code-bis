import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface AnomalieDroits { code: string; libelle: string; }

/** Une fiche de contact et tous ses droits (backend/core/revue_droits.py). */
export interface LigneRevueDroits {
  contact: string;
  utilisateur: string;
  nom: string;
  email: string;
  institution: string;
  institution_nom: string;
  fonction: string;
  actif: boolean;
  contact_principal: boolean;
  membre_bureau: boolean;
  type_compte: string;
  type_compte_libelle: string;
  institution_travail: string;
  roles: { id: string; code: string; libelle: string }[];
  equipes: string[];
  encadre: string[];
  habilite_registre: boolean;
  engagement_signe: boolean;
  acces_formation: boolean;
  compte_actif: boolean;
  derniere_connexion: string | null;
  derniere_revue: { le: string; par: string; decision: string } | null;
  anomalies: AnomalieDroits[];
}

export interface MatriceRevueDroits {
  institution: { id: string; nom: string };
  institutions: { id: string; nom: string; type_libelle: string }[];
  choix: { id: string; nom: string }[];
  lignes: LigneRevueDroits[];
  resume: {
    fiches: number; actives: number; a_revoir: number; anomalies: number;
    prochaine_echeance: string | null; sans_responsable: string[];
    periode_jours: number; seuil_inactivite_jours: number;
  };
}

export type DecisionRevue = 'CONFIRME' | 'BUREAU_RETIRE' | 'ROLE_RETIRE' | 'CONTACT_DESACTIVE';

@Injectable({ providedIn: 'root' })
export class RevueDroitsService {
  private readonly url = `${environment.apiUrl}/revue-droits/`;

  constructor(private http: HttpClient) {}

  matrice(institution?: string | null): Observable<MatriceRevueDroits> {
    const params = institution ? new HttpParams().set('institution', institution) : undefined;
    return this.http.get<MatriceRevueDroits>(this.url, { params });
  }

  decider(contact: string, decision: DecisionRevue, commentaire = '', affectation?: string): Observable<{ id: string; decision: string }> {
    return this.http.post<{ id: string; decision: string }>(`${this.url}decision/`, { contact, decision, commentaire, affectation });
  }

  exporter(institution: string): Observable<Blob> {
    return this.http.get(`${this.url}export/`, { params: new HttpParams().set('institution', institution), responseType: 'blob' });
  }
}
