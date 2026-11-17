import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { FormulaireTerrain, PhotoAEnvoyer, ReponseAEnvoyer, ReponseTerrain } from '../shared/models/formulaire-terrain.model';
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

  /** L'image d'une photo jointe (déchiffrée par le serveur, selon les droits de l'appelant). */
  photo(formulaire: string, photo: string): Observable<Blob> {
    return this.http.get(`${this.url}/${formulaire}/photos/${photo}/`, { responseType: 'blob' });
  }

  private envoyerPhoto(photo: PhotoAEnvoyer): Observable<unknown> {
    const octets = Uint8Array.from(atob(photo.image), c => c.charCodeAt(0));
    const corps = new FormData();
    corps.append('identifiant_client', photo.identifiant_client);
    corps.append('identifiant_photo', photo.identifiant_photo);
    corps.append('cle', photo.cle);
    corps.append('fichier', new Blob([octets], { type: 'image/jpeg' }), 'photo.jpg');
    return this.http.post(`${this.url}/${photo.formulaire}/photo/`, corps);
  }

  /** Envoie une photo ; sans réseau — ou si sa réponse attend encore — la garde pour plus
   * tard. Une photo refusée pour de bon est abandonnée : la réponse, elle, est déjà sauvée. */
  joindrePhoto(photo: PhotoAEnvoyer, reponseEnAttente: boolean): Promise<'envoyee' | 'en_attente' | 'refusee'> {
    const garder = () => deposer('photo:' + photo.identifiant_photo, photo).then(() => 'en_attente' as const);
    if (reponseEnAttente) return garder();
    return new Promise((resolve, reject) => {
      this.envoyerPhoto(photo).subscribe({
        next: () => resolve('envoyee'),
        error: (err) => (err?.status === 0 || err?.status >= 502 ? garder().then(resolve, reject) : resolve('refusee')),
      });
    });
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
    let attente: { identifiant: string; valeur: ReponseAEnvoyer | PhotoAEnvoyer }[] = [];
    try { attente = await relever<ReponseAEnvoyer | PhotoAEnvoyer>(); } catch { return 0; }
    // Les réponses d'abord : une photo ne se range que sur une réponse déjà arrivée.
    const estPhoto = (i: string) => i.startsWith('photo:');
    attente.sort((a, b) => Number(estPhoto(a.identifiant)) - Number(estPhoto(b.identifiant)));
    for (const { identifiant, valeur } of attente) {
      const envoi: Observable<unknown> = estPhoto(identifiant)
        ? this.envoyerPhoto(valeur as PhotoAEnvoyer) : this.envoyer(valeur as ReponseAEnvoyer);
      const issue = await new Promise<'ok' | 'refus' | 'reseau'>(resolve => {
        envoi.subscribe({
          next: () => resolve('ok'),
          error: (err) => resolve(err?.status === 0 || err?.status >= 502 ? 'reseau' : 'refus'),
        });
      });
      if (issue === 'reseau') break;          // toujours pas de réseau : inutile d'insister
      // Partie, ou refusée pour de bon (questionnaire fermé entre-temps) : dans les deux cas
      // elle n'a plus rien à faire dans la file.
      await retirer(identifiant);
      if (issue === 'ok' && !estPhoto(identifiant)) parties++;
    }
    return parties;
  }
}

/**
 * Réduit une photo avant l'envoi : 1 600 px de grand côté, JPEG.
 *
 * Un téléphone sort des images de 4 à 12 Mo ; sur le réseau d'une zone sinistrée, c'est une
 * réponse qui ne part pas. 1 600 px suffisent à lire une fissure ou une laisse de crue, pour
 * 200 à 400 ko. Le passage par le canevas retire aussi les métadonnées de l'appareil — dont la
 * position, qui ne doit partir que si l'agent choisit de la joindre.
 */
export async function reduirePhoto(fichier: Blob, grandCote = 1600, qualite = 0.8): Promise<string> {
  const image = await createImageBitmap(fichier);
  const echelle = Math.min(1, grandCote / Math.max(image.width, image.height));
  const canevas = document.createElement('canvas');
  canevas.width = Math.round(image.width * echelle);
  canevas.height = Math.round(image.height * echelle);
  canevas.getContext('2d')!.drawImage(image, 0, 0, canevas.width, canevas.height);
  image.close();
  return canevas.toDataURL('image/jpeg', qualite).split(',')[1];
}
