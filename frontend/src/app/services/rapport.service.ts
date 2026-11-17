import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../environments/environment';

export type NatureRapport = 'dossier' | 'mission' | 'crise' | 'bien';

/**
 * Rapports en PDF d'un dossier, d'une mission ou d'une crise (core/rapports_pdf.py) : ce qui
 * s'est passé, ce qui a été constaté, ce qui a été fait, photos en annexe. Faits pour être
 * joints à une déclaration de sinistre ou à un dossier de catastrophe naturelle.
 *
 * Le serveur les construit à la demande et n'en garde aucune copie.
 */
@Injectable({ providedIn: 'root' })
export class RapportService {
  private readonly chemins: Record<NatureRapport, string> = { dossier: 'dossiers', mission: 'missions', crise: 'crises', bien: 'biens-sinistres' };

  constructor(private http: HttpClient) {}

  /** Demande le rapport et le fait enregistrer par le navigateur. Rend `true` une fois remis. */
  telecharger(nature: NatureRapport, id: string, nomDuFichier: string, toutesLesPhotos = false): Observable<boolean> {
    // `photos=toutes` : sans le plafond par défaut. Le fichier peut être lourd.
    const params: Record<string, string> = toutesLesPhotos ? { photos: 'toutes' } : {};
    return this.http.get(`${environment.apiUrl}/${this.chemins[nature]}/${id}/rapport/`, { responseType: 'blob', params }).pipe(
      map((contenu) => {
        const adresse = URL.createObjectURL(contenu);
        const lien = document.createElement('a');
        lien.href = adresse;
        lien.download = `${nomDuFichier}.pdf`;
        lien.click();
        URL.revokeObjectURL(adresse);
        return true;
      }),
    );
  }
}
