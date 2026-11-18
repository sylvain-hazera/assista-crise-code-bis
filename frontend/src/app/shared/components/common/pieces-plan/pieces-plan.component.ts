import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../../../environments/environment';

export interface PiecePlan {
  id: string;
  titre: string;
  fonction: string | null;
  moyen_alerte: string | null;
  nom_fichier: string;
  type_mime: string;
  taille: number;
  depose_par_nom: string;
  date_depot: string;
}

/**
 * Les fichiers que la commune joint à son plan (18/11/2026) : la procédure de déclenchement
 * de la sirène, le plan du gymnase, une fiche réflexe maison en PDF.
 *
 * Rattachés au plan entier, à UNE fiche réflexe (`fonction`) ou à UN moyen d'alerte
 * (`moyenAlerte`). Le fichier ne se lit jamais par une adresse directe : il est demandé au
 * serveur avec le jeton de la personne, qui vérifie ses droits, le déchiffre et trace la lecture.
 */
@Component({
  selector: 'app-pieces-plan',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './pieces-plan.component.html',
  styleUrl: './pieces-plan.component.scss',
})
export class PiecesPlanComponent implements OnInit {
  @Input() fonction: string | null = null;
  @Input() moyenAlerte: string | null = null;
  /** Faux : on lit et on télécharge, sans pouvoir déposer ni retirer (page « Alerter »). */
  @Input() modifiable = true;
  @Input() intitule = 'Fichiers joints';

  pieces: PiecePlan[] = [];
  titre = '';
  fichier: File | null = null;
  envoi = false;
  erreur = '';
  private readonly url = `${environment.apiUrl}/pcs-pieces/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    let params = new HttpParams();
    if (this.fonction) params = params.set('fonction', this.fonction);
    if (this.moyenAlerte) params = params.set('moyen_alerte', this.moyenAlerte);
    this.http.get<PiecePlan[]>(this.url, { params }).subscribe({
      next: (pieces) => {
        // Sans fiche ni moyen désignés : les fichiers du plan lui-même, pas ceux des fiches.
        this.pieces = this.fonction || this.moyenAlerte ? pieces : pieces.filter(p => !p.fonction && !p.moyen_alerte);
      },
      error: () => { this.pieces = []; },
    });
  }

  choisir(evenement: Event): void {
    this.fichier = (evenement.target as HTMLInputElement).files?.[0] ?? null;
    this.erreur = '';
  }

  deposer(): void {
    if (!this.fichier || this.envoi) return;
    const corps = new FormData();
    corps.append('fichier', this.fichier);
    if (this.titre.trim()) corps.append('titre', this.titre.trim());
    if (this.fonction) corps.append('fonction', this.fonction);
    if (this.moyenAlerte) corps.append('moyen_alerte', this.moyenAlerte);
    this.envoi = true;
    this.http.post<PiecePlan>(this.url, corps).subscribe({
      next: () => { this.envoi = false; this.fichier = null; this.titre = ''; this.charger(); },
      error: (e) => {
        this.envoi = false;
        const detail = e?.error?.fichier ?? e?.error?.detail;
        this.erreur = (Array.isArray(detail) ? detail.join(' ') : detail) || "Le fichier n'a pas pu être déposé.";
      },
    });
  }

  /** Demande le fichier au serveur (droits vérifiés, lecture tracée) et l'ouvre. */
  ouvrir(piece: PiecePlan): void {
    this.http.get(`${this.url}${piece.id}/fichier/`, { responseType: 'blob' }).subscribe({
      next: (contenu) => {
        const adresse = URL.createObjectURL(contenu);
        const lien = document.createElement('a');
        lien.href = adresse;
        lien.download = piece.nom_fichier || piece.titre;
        lien.click();
        setTimeout(() => URL.revokeObjectURL(adresse), 30_000);
      },
      error: () => { this.erreur = "Ce fichier n'a pas pu être lu."; },
    });
  }

  retirer(piece: PiecePlan): void {
    if (!confirm(`Retirer « ${piece.titre} » ? Le fichier est supprimé.`)) return;
    this.http.delete(`${this.url}${piece.id}/`).subscribe({ next: () => this.charger(), error: () => { this.erreur = 'Retrait impossible.'; } });
  }

  poids(octets: number): string {
    return octets >= 1_048_576 ? `${(octets / 1_048_576).toFixed(1)} Mo` : `${Math.max(1, Math.round(octets / 1024))} ko`;
  }
}
