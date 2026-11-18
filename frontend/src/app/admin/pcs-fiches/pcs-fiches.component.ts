import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface FicheConseil {
  code: string;
  titre: string;
  categorie: string;
  categorie_libelle: string;
  /** La fonction du poste de commandement à laquelle la fiche se rattache d'office. */
  fonction?: string;
  moyen?: string;
  sections: { titre: string; lignes: string[] }[];
  source: { titre: string; editeur: string; url: string; consulte_le: string };
  /** false pour les astuces de terrain, qui ne viennent d'aucun document officiel. */
  officielle: boolean;
}

/**
 * Fiches réflexes et conseils (18/11/2026) : les rôles, les postes du poste de commandement,
 * la tenue d'un centre d'accueil, les situations — repris de documents publics de l'État, la
 * source sur chaque fiche. On lit, on imprime, et on reprend une fiche dans son plan pour en
 * faire la sienne (voir core/fiches_conseil.py côté serveur).
 */
@Component({
  selector: 'app-pcs-fiches',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './pcs-fiches.component.html',
  styleUrl: './pcs-fiches.component.scss',
})
export class PcsFichesComponent implements OnInit {
  categories: Record<string, string> = {};
  fiches: FicheConseil[] = [];
  ouverte: string | null = null;
  chargement = true;
  erreur = '';
  message = '';
  /** Pour une fiche sans fonction d'office : celle qui la reprend. */
  fonctionChoisie: Record<string, string> = {};
  enCours = '';

  readonly FONCTIONS: { code: string; libelle: string }[] = [
    { code: 'DOS', libelle: 'Maire — directeur des opérations' },
    { code: 'COORDINATION', libelle: 'Coordinateur des moyens et des actions' },
    { code: 'ALERTE', libelle: "Responsable de l'alerte" },
    { code: 'SOUTIEN', libelle: 'Responsable du soutien des populations' },
    { code: 'LOGISTIQUE', libelle: 'Responsable logistique' },
    { code: 'SECRETARIAT', libelle: 'Secrétariat' },
  ];

  private readonly url = `${environment.apiUrl}/pcs-fiches-conseil/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.http.get<{ categories: Record<string, string>; fiches: FicheConseil[] }>(this.url).subscribe({
      next: (d) => { this.categories = d.categories; this.fiches = d.fiches; this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = 'Impossible de lire les fiches.'; },
    });
  }

  get codesCategories(): string[] { return Object.keys(this.categories); }

  dansLaCategorie(categorie: string): FicheConseil[] { return this.fiches.filter(f => f.categorie === categorie); }

  basculer(code: string): void { this.ouverte = this.ouverte === code ? null : code; }

  libelleFonction(code?: string): string { return this.FONCTIONS.find(f => f.code === code)?.libelle ?? ''; }

  /** Imprime la fiche ouverte seule : la feuille de style d'impression masque le reste. */
  imprimer(code: string): void {
    this.ouverte = code;
    setTimeout(() => window.print(), 50);
  }

  reprendre(fiche: FicheConseil, remplacer = false): void {
    const fonction = fiche.fonction || this.fonctionChoisie[fiche.code];
    if (!fonction) { this.message = 'Choisissez la fonction qui reprend cette fiche.'; return; }
    this.enCours = fiche.code;
    this.message = '';
    this.http.post<{ fonction: string }>(this.url, { fiche: fiche.code, fonction, remplacer }).subscribe({
      next: () => {
        this.enCours = '';
        this.message = `« ${fiche.titre} » est maintenant la fiche réflexe de « ${this.libelleFonction(fonction)} » dans votre plan. `
          + 'Vous pouvez la réécrire dans Poste de commandement.';
      },
      error: (e) => {
        this.enCours = '';
        if (e?.status === 409 && confirm(`« ${this.libelleFonction(fonction)} » a déjà une fiche écrite par la commune. La remplacer par celle-ci ?`)) {
          this.reprendre(fiche, true);
          return;
        }
        this.message = e?.error?.fonction || e?.error?.detail || "La fiche n'a pas pu être reprise.";
      },
    });
  }
}
