import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface RemiseRapport {
  rapport: string;
  crise: string;
  /** L'adresse où part le rapport, masquée : assez pour reconnaître la sienne. */
  adresse: string;
  disponible_jusqu_au: string | null;
  deja_envoye: boolean;
  envoye?: boolean;
}

/**
 * La page du lien « Recevoir mon rapport », reçu par courriel quand la clôture d'une crise est
 * proposée. Sans compte : le lien est personnel. Le rapport part à l'adresse à laquelle le lien
 * a été envoyé, jamais à une autre ; il n'est pas affiché ici.
 */
@Component({
  selector: 'app-recevoir-rapport',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './recevoir-rapport.component.html',
  styleUrl: './recevoir-rapport.component.scss',
})
export class RecevoirRapportComponent implements OnInit {
  remise: RemiseRapport | null = null;
  chargement = true;
  envoi = false;
  erreur = '';
  private adresse = '';

  constructor(private http: HttpClient, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.adresse = `${environment.apiUrl}/rapports/recevoir/${encodeURIComponent(this.route.snapshot.paramMap.get('jeton') || '')}/`;
    this.http.get<RemiseRapport>(this.adresse).subscribe({
      next: (remise) => { this.remise = remise; this.chargement = false; },
      error: (e) => { this.chargement = false; this.erreur = e?.error?.error || 'Ce lien n’est plus valable.'; },
    });
  }

  envoyer(): void {
    this.envoi = true;
    this.erreur = '';
    this.http.post<RemiseRapport>(this.adresse, {}).subscribe({
      next: (remise) => { this.remise = remise; this.envoi = false; },
      error: (e) => { this.envoi = false; this.erreur = e?.error?.error || 'Le rapport n’a pas pu être envoyé. Réessayez dans un moment.'; },
    });
  }
}
