import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { FormulaireTerrain, ReponseAEnvoyer, ReponseTerrain } from '../shared/models/formulaire-terrain.model';
import { deposer, relever, retirer } from './file-attente-chiffree';

/** Formulaires de terrain (voir core/formulaires_terrain.py côté serveur). */
@Injectable({ providedIn: 'root' })
export class FormulaireTerrainService {
  private readonly url = `${environment.apiUrl}/formulaires-terrain`;

  constructor(private http: HttpClient) {}

  types(): Observable<{ types: { code: string; libelle: string }[]; peut_composer: boolean; peut_repondre: boolean }> {
    return this.http.get<{ types: { code: string; libelle: string }[]; peut_composer: boolean; peut_repondre: boolean }>(
      `${environment.apiUrl}/formulaires-terrain-types/`);
  }

  liste(): Observable<FormulaireTerrain[]> { return this.http.get<FormulaireTerrain[]>(`${this.url}/`); }

  enregistrer(formulaire: Partial<FormulaireTerrain>): Observable<FormulaireTerrain> {
    return formulaire.id
      ? this.http.patch<FormulaireTerrain>(`${this.url}/${formulaire.id}/`, formulaire)
      : this.http.post<FormulaireTerrain>(`${this.url}/`, formulaire);
  }

  supprimer(id: string): Observable<void> { return this.http.delete<void>(`${this.url}/${id}/`); }

  reponses(id: string): Observable<ReponseTerrain[]> { return this.http.get<ReponseTerrain[]>(`${this.url}/${id}/reponses/`); }

  exporter(id: string, type: 'csv' | 'geojson'): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/export/`, { params: { type }, responseType: 'blob' });
  }

  private envoyer(reponse: ReponseAEnvoyer): Observable<{ id: string; deja_recue: boolean }> {
    return this.http.post<{ id: string; deja_recue: boolean }>(`${this.url}/${reponse.formulaire}/repondre/`, reponse);
  }

  /**
   * Envoie une réponse ; sans réseau, la garde (chiffrée) pour plus tard.
   *
   * Rend « envoyee » ou « en_attente ». Un REFUS du serveur (réponse incomplète, questionnaire
   * fermé) est levé tel quel : le garder en file ne servirait à rien, il serait refusé encore.
   * L'identifiant tiré ici accompagne la réponse jusqu'au bout : la renvoyer ne la double pas.
   */
  repondre(reponse: ReponseAEnvoyer): Promise<'envoyee' | 'en_attente'> {
    return new Promise((resolve, reject) => {
      this.envoyer(reponse).subscribe({
        next: () => resolve('envoyee'),
        error: (err) => {
          if (err?.status === 0 || err?.status >= 502) {
            deposer(reponse.identifiant_client, reponse).then(() => resolve('en_attente'), reject);
          } else {
            reject(err);
          }
        },
      });
    });
  }

  async enAttente(): Promise<number> {
    try { return (await relever<ReponseAEnvoyer>()).length; } catch { return 0; }
  }

  /** Tente d'envoyer tout ce qui attend. Rend le nombre de réponses parties. */
  async viderLaFile(): Promise<number> {
    let parties = 0;
    let attente: { identifiant: string; valeur: ReponseAEnvoyer }[] = [];
    try { attente = await relever<ReponseAEnvoyer>(); } catch { return 0; }
    for (const { identifiant, valeur } of attente) {
      const issue = await new Promise<'ok' | 'refus' | 'reseau'>(resolve => {
        this.envoyer(valeur).subscribe({
          next: () => resolve('ok'),
          error: (err) => resolve(err?.status === 0 || err?.status >= 502 ? 'reseau' : 'refus'),
        });
      });
      if (issue === 'reseau') break;          // toujours pas de réseau : inutile d'insister
      // Partie, ou refusée pour de bon (questionnaire fermé entre-temps) : dans les deux cas
      // elle n'a plus rien à faire dans la file.
      await retirer(identifiant);
      if (issue === 'ok') parties++;
    }
    return parties;
  }
}
