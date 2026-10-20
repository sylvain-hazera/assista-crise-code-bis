import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  Habitation, HabitationCommentaire, HabitationHistorique, RattachementHabitation,
  StatutEvaluationHabitation, StatutChantierHabitation,
} from '../shared/models/habitation.model';

export interface HabitationFiltres {
  commune_code?: string;
  crise?: string;
  zone?: string;
  statut_evaluation?: string;
  statut_chantier?: string;
  recherche?: string;
}

@Injectable({ providedIn: 'root' })
export class HabitationService {

  private url = `${environment.apiUrl}/habitations`;

  constructor(private http: HttpClient) {}

  getAll(filtres: HabitationFiltres = {}): Observable<Habitation[]> {
    let params = new URLSearchParams();
    Object.entries(filtres).forEach(([k, v]) => { if (v) params.set(k, v); });
    const query = params.toString();
    return this.http.get<Habitation[]>(`${this.url}/${query ? '?' + query : ''}`);
  }

  getOne(id: string): Observable<Habitation> {
    return this.http.get<Habitation>(`${this.url}/${id}/`);
  }

  create(data: Partial<Habitation> & { latitude: number; longitude: number; adresse: string }): Observable<Habitation> {
    return this.http.post<Habitation>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Habitation>): Observable<Habitation> {
    return this.http.patch<Habitation>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  evaluer(id: string, statutEvaluation: StatutEvaluationHabitation, statutChantier: StatutChantierHabitation, commentaire?: string): Observable<Habitation> {
    return this.http.post<Habitation>(`${this.url}/${id}/evaluer/`, {
      statut_evaluation: statutEvaluation,
      statut_chantier: statutChantier,
      commentaire: commentaire || undefined,
    });
  }

  importerCsv(fichier: File, mapping: Record<string, string>, crise?: string, zone?: string): Observable<{ crees: number; erreurs: { ligne: number; message: string }[] }> {
    const form = new FormData();
    form.append('fichier', fichier);
    Object.entries(mapping).forEach(([champ, colonne]) => { if (colonne) form.append(`mapping_${champ}`, colonne); });
    if (crise) form.append('crise', crise);
    if (zone) form.append('zone', zone);
    return this.http.post<{ crees: number; erreurs: { ligne: number; message: string }[] }>(
      `${environment.apiUrl}/imports/habitations/`, form
    );
  }

  /** `georisques` (optionnel) : ne référencer que les adresses situées dans les zones de
   * débordement officielles Géorisques de ce scénario (ex: ALEA_SYNT_01_02MOY_FXX). */
  estimationBan(communeCode: string, criseId?: string, zoneId?: string, georisques?: string): Observable<{
    creees: number; adresses_trouvees: number; voies_totales: number; voies_en_echec: number; filtre_georisques?: string | null;
  }> {
    return this.http.post<{ creees: number; adresses_trouvees: number; voies_totales: number; voies_en_echec: number; filtre_georisques?: string | null }>(
      `${this.url}/estimation-ban/`,
      { commune_code: communeCode, crise: criseId || undefined, zone: zoneId || undefined, georisques: georisques || undefined },
    );
  }

  telechargerExempleCsv(): Observable<Blob> {
    return this.http.get(`${environment.apiUrl}/imports/habitations/exemple/`, { responseType: 'blob' });
  }

  getCommentaires(habitationId: string): Observable<HabitationCommentaire[]> {
    return this.http.get<HabitationCommentaire[]>(`${environment.apiUrl}/habitations-commentaires/?habitation=${habitationId}`);
  }

  ajouterCommentaire(habitationId: string, commentaire: string): Observable<HabitationCommentaire> {
    return this.http.post<HabitationCommentaire>(`${environment.apiUrl}/habitations-commentaires/`, {
      habitation: habitationId, commentaire,
    });
  }

  getHistorique(habitationId: string): Observable<HabitationHistorique[]> {
    return this.http.get<HabitationHistorique[]>(`${environment.apiUrl}/habitations-historique/?habitation=${habitationId}`);
  }
}

@Injectable({ providedIn: 'root' })
export class RattachementHabitationService {

  private url = `${environment.apiUrl}/rattachements-habitations`;

  constructor(private http: HttpClient) {}

  getAll(habitationId?: string): Observable<RattachementHabitation[]> {
    const query = habitationId ? `?habitation=${habitationId}` : '';
    return this.http.get<RattachementHabitation[]>(`${this.url}/${query}`);
  }

  demander(data: {
    habitation: string; nom_demandeur: string; email_demandeur: string;
    telephone_demandeur?: string; type_lien: 'PROPRIETAIRE' | 'LOCATAIRE'; message?: string;
  } | FormData): Observable<RattachementHabitation> {
    return this.http.post<RattachementHabitation>(`${this.url}/`, data);
  }

  accepter(id: string): Observable<RattachementHabitation> {
    return this.http.post<RattachementHabitation>(`${this.url}/${id}/accepter/`, {});
  }

  refuser(id: string, motif?: string): Observable<RattachementHabitation> {
    return this.http.post<RattachementHabitation>(`${this.url}/${id}/refuser/`, { motif_refus: motif || undefined });
  }

  previewJustificatif(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/preview/`, { responseType: 'blob' });
  }
}
