import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Signalement de point d'eau incendie fait sur le terrain (24/11/2026). */
export interface SignalementPEI {
  id: string;
  genre: 'INDISPONIBLE' | 'REMIS_EN_SERVICE' | 'DEFAUT' | 'NOUVEAU';
  genre_libelle: string;
  statut: 'A_VALIDER' | 'VALIDE' | 'REJETE' | 'TRANSMIS_SDIS';
  statut_libelle: string;
  pei: number | null;
  pei_source: string;
  pei_ref: string;
  latitude: number;
  longitude: number;
  precision_m: number | null;
  type_pei: string;
  source_eau: string;
  debit_estime: number | null;
  volume_estime: number | null;
  commentaire: string;
  commune_code: string;
  auteur: string | null;
  observe_le: string;
  traite_le: string | null;
  traite_par: string | null;
  motif_decision: string;
  numero_sdis: string;
  transmis_le: string | null;
  photos: { id: string; commentaire: string }[];
}

export interface CouverturePEI {
  attribution_osm: string;
  releves: number;
  a_valider_ma_commune: number;
  departements: {
    departement: string; osm_releve_le: string | null; osm_nombre: number; osm_erreur: string | null;
    sdis_importe_le: string | null; sdis_nombre: number; terrain_nombre: number;
  }[];
}

export interface RapportImportPEI {
  departement: string; importes: number; nouveaux: number; supprimes: number; refuses: number;
  refus: { ligne: number; raison: string }[];
}

@Injectable({ providedIn: 'root' })
export class PointsEauService {
  private api = `${environment.apiUrl}/points-eau`;

  constructor(private http: HttpClient) {}

  signalements(statut?: string): Observable<SignalementPEI[]> {
    return this.http.get<SignalementPEI[]>(`${this.api}/signalements/`, { params: statut ? { statut } : {} });
  }

  decider(id: string, geste: 'valider' | 'rejeter', motif: string): Observable<SignalementPEI> {
    return this.http.post<SignalementPEI>(`${this.api}/signalements/${id}/decider/`, { geste, motif });
  }

  transmis(id: string, numeroSdis: string): Observable<SignalementPEI> {
    return this.http.post<SignalementPEI>(`${this.api}/signalements/${id}/transmis/`, { numero_sdis: numeroSdis });
  }

  couverture(): Observable<CouverturePEI> {
    return this.http.get<CouverturePEI>(`${this.api}/couverture/`);
  }

  exporter(commune?: string): Observable<Blob> {
    return this.http.get(`${this.api}/export/`, { params: commune ? { commune } : {}, responseType: 'blob' });
  }

  importer(departement: string, fichier: File): Observable<RapportImportPEI> {
    const corps = new FormData();
    corps.append('departement', departement);
    corps.append('fichier', fichier);
    return this.http.post<RapportImportPEI>(`${this.api}/import/`, corps);
  }
}
