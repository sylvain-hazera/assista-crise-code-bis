import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AlerteHabitants, AlerteHabitantsService, CanalAlerte } from '../../services/alerte-habitants.service';
import { CrisisService } from '../../services/crisis.service';
import { Crisis } from '../../shared/models/crisis.model';

/**
 * Alerter les habitants : le message de la commune à ceux qui ont demandé à le recevoir, et aux
 * personnes déjà touchées par la crise.
 *
 * L'écran dit, AVANT l'envoi, combien de personnes chaque canal peut joindre, et APRÈS, ce qui
 * est réellement parti : une alerte « envoyée » qui n'a touché personne est la pire des fausses
 * assurances. Ce n'est pas FR-Alert, qui relève du préfet.
 */
@Component({
  selector: 'app-alerte-habitants',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './alerte-habitants.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class AlerteHabitantsComponent implements OnInit {
  crises: Crisis[] = [];
  criseId = '';
  canaux: CanalAlerte[] = [];
  destinataires = 0;
  alertes: AlerteHabitants[] = [];
  /** Canaux cochés, par code. */
  choisis: Record<string, boolean> = {};

  titre = '';
  message = '';
  urgent = true;

  chargement = true;
  sansCollectivite = false;
  envoi = false;
  erreur = '';
  derniere: AlerteHabitants | null = null;

  constructor(private service: AlerteHabitantsService, private crisisService: CrisisService) {}

  ngOnInit(): void {
    this.crisisService.getAll().subscribe({
      next: (crises) => { this.crises = crises.filter(c => c.is_open !== false); }, error: () => {},
    });
    this.charger(true);
  }

  /** `premier` : au premier chargement seulement, on coche les canaux par défaut. Changer de
   * crise ne doit pas défaire ce que la personne a coché. */
  charger(premier = false): void {
    this.service.etat(this.criseId || undefined).subscribe({
      next: (etat) => {
        this.canaux = etat.apercu.canaux;
        this.destinataires = etat.apercu.destinataires;
        this.alertes = etat.alertes;
        if (premier) for (const canal of this.canaux) this.choisis[canal.code] = etat.par_defaut.includes(canal.code) && canal.disponible;
        this.chargement = false;
      },
      error: (e) => {
        this.chargement = false;
        this.sansCollectivite = e?.status === 403;
        if (!this.sansCollectivite) this.erreur = "Impossible de préparer l'alerte.";
      },
    });
  }

  get canauxChoisis(): string[] {
    return this.canaux.filter(c => c.disponible && this.choisis[c.code]).map(c => c.code);
  }

  get pret(): boolean {
    return !!this.titre.trim() && !!this.message.trim() && this.canauxChoisis.length > 0 && !this.envoi;
  }

  libelle(code: string): string {
    return this.canaux.find(c => c.code === code)?.libelle ?? code;
  }

  envoyer(): void {
    if (!this.pret) return;
    const combien = this.destinataires;
    if (!confirm(`Envoyer cette alerte à ${combien} personne${combien > 1 ? 's' : ''} par : `
      + this.canauxChoisis.map(c => this.libelle(c)).join(', ') + ' ?\n\nUne alerte partie ne se rattrape pas.')) return;
    this.envoi = true;
    this.erreur = '';
    this.service.envoyer({
      titre: this.titre.trim(), message: this.message.trim(), canaux: this.canauxChoisis, urgent: this.urgent,
      ...(this.criseId ? { crise: this.criseId } : {}),
    }).subscribe({
      next: (alerte) => {
        this.envoi = false;
        this.derniere = alerte;
        this.titre = this.message = '';
        this.charger();
      },
      error: (e) => {
        this.envoi = false;
        const detail = e?.error && typeof e.error === 'object' ? Object.values(e.error).flat().join(' ') : '';
        this.erreur = detail || "L'alerte n'est pas partie.";
      },
    });
  }
}
