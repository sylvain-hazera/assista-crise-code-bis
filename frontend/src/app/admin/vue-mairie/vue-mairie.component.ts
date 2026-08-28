import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { forkJoin } from 'rxjs';

import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Request } from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { Status } from '../../shared/models/status.model';

@Component({
  selector: 'app-vue-mairie',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './vue-mairie.component.html',
  styleUrls: ['./vue-mairie.component.scss'],
})
export class VueMairieComponent implements OnInit {

  demandes: Request[] = [];
  informations: Information[] = [];

  isLoading = true;
  errorMessage = '';

  readonly Status = Status;

  constructor(
    private requestService: RequestService,
    private informationService: InformationService,
  ) {}

  ngOnInit(): void {
    this.loadAll();
  }

  loadAll(): void {
    this.isLoading = true;
    this.errorMessage = '';
    forkJoin({
      demandes: this.requestService.vueMairie(),
      informations: this.informationService.vueMairie(),
    }).subscribe({
      next: ({ demandes, informations }) => {
        this.demandes = demandes;
        this.informations = informations;
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Impossible de charger la vue mairie.";
        this.isLoading = false;
      },
    });
  }

  // Heuristique temporaire : le formulaire public "Je suis en sécurité" pose toujours ce
  // titre exact (other-declaration-form.component.ts, submitDeclareSafeForm) — pas encore de
  // champ/type dédié. À remplacer quand le flux "je suis ok" (phase 4) posera une vraie
  // distinction (ex: un InformationType ou un booléen dédié) au lieu de ce matching sur titre.
  get signalementsJeSuisOk(): Information[] {
    return this.informations.filter(i => i.title === 'Je suis en sécurité');
  }

  get autresSignalements(): Information[] {
    return this.informations.filter(i => i.title !== 'Je suis en sécurité');
  }

  statusLabel(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'Non traitée',
      [Status.IN_PROGRESS]:  'En cours',
      [Status.PROCESSED]:    'Traitée',
      [Status.AVAILABLE]:    'Disponible',
      [Status.UNAVAILABLE]:  'Indisponible',
    } as Record<string, string>)[s] ?? s;
  }

  statusClass(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'stat-urgent',
      [Status.IN_PROGRESS]:  'stat-encours',
      [Status.PROCESSED]:    'stat-traitee',
      [Status.AVAILABLE]:    'stat-dispo',
      [Status.UNAVAILABLE]:  'stat-indispo',
    } as Record<string, string>)[s] ?? '';
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
