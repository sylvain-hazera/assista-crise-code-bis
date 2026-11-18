import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, EventEmitter, OnDestroy, OnInit, Output } from '@angular/core';

import { environment } from '../../../../../environments/environment';

export interface EtatGeorisques {
  commune_code: string;
  releve: boolean;
  releve_le: string | null;
  complet: boolean;
  rubriques: { code: string; libelle: string; relevee: boolean; nombre: number | null }[];
  sismicite: string;
  radon: string;
  catnat: { nombre: number; derniers: { risque: string; debut: string; fin: string; arrete: string }[] };
  azi: string[];
  tri: { nom: string; risques: string[] }[];
  mouvements: { type: string; date: string; lieu: string }[];
  cavites: number;
}

/**
 * Ce que Géorisques publie pour la commune — UN relevé, montré tel quel sur chaque page qui en
 * a besoin (18/11/2026). Avant, « Risques de la commune » et « Enjeux exposés » interrogeaient
 * le service chacune de son côté, sous deux boutons.
 *
 * Le bouton demande le relevé complet au serveur : risques recensés, arrêtés de catastrophe
 * naturelle, atlas des zones inondables, mouvements de terrain, radon, sismicité, zones
 * inondables officielles et plans de prévention. Le navigateur n'interroge jamais Géorisques.
 */
@Component({
  selector: 'app-releve-georisques',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './releve-georisques.component.html',
  styleUrl: './releve-georisques.component.scss',
})
export class ReleveGeorisquesComponent implements OnInit, OnDestroy {
  /** Le relevé vient d'être refait : la page qui l'affiche relit ce qui en dépend. */
  @Output() misAJour = new EventEmitter<void>();

  etat: EtatGeorisques | null = null;
  enCours = false;
  rapportEnCours = false;
  message = '';
  private relectures: ReturnType<typeof setTimeout>[] = [];
  private readonly url = `${environment.apiUrl}/dossier-pcs/georisques/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.lire(); }

  ngOnDestroy(): void { this.relectures.forEach(clearTimeout); }

  private lire(): void {
    this.http.get<EtatGeorisques>(this.url).subscribe({ next: (etat) => { this.etat = etat; }, error: () => {} });
  }

  /** Demande le relevé, puis relit la copie à mesure que les rubriques arrivent (requêtes
   * espacées côté serveur : il faut une à deux minutes pour tout avoir). */
  relever(forcer = false): void {
    if (this.enCours) return;
    this.enCours = true;
    this.message = 'Relevé demandé : les rubriques arrivent une à une, sur une à deux minutes.';
    this.http.post<EtatGeorisques>(this.url, { forcer }).subscribe({
      next: (etat) => {
        this.etat = etat;
        [15, 35, 60, 90, 130].forEach((secondes, rang, toutes) => this.relectures.push(setTimeout(() => {
          this.lire();
          this.misAJour.emit();
          if (rang === toutes.length - 1) { this.enCours = false; this.message = ''; }
        }, secondes * 1000)));
      },
      error: (e) => { this.enCours = false; this.message = e?.error?.commune || 'Le relevé n\'a pas pu être demandé.'; },
    });
  }

  rapport(): void {
    if (this.rapportEnCours) return;
    this.rapportEnCours = true;
    this.http.get(`${this.url}rapport/`, { responseType: 'blob' }).subscribe({
      next: (pdf) => {
        this.rapportEnCours = false;
        const adresse = URL.createObjectURL(pdf);
        const lien = document.createElement('a');
        lien.href = adresse;
        lien.download = `georisques-${this.etat?.commune_code || 'commune'}.pdf`;
        lien.click();
        setTimeout(() => URL.revokeObjectURL(adresse), 30_000);
      },
      error: () => { this.rapportEnCours = false; this.message = 'Géorisques ne rend pas ce rapport pour le moment.'; },
    });
  }
}
