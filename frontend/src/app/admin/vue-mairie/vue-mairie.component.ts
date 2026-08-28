import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { forkJoin } from 'rxjs';

import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { DeclarationSecuriteService } from '../../services/declaration-securite.service';

import { Request } from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';
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
  declarationsSecurite: DeclarationSecurite[] = [];

  isLoading = true;
  errorMessage = '';

  readonly Status = Status;

  constructor(
    private requestService: RequestService,
    private informationService: InformationService,
    private declarationSecuriteService: DeclarationSecuriteService,
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
      declarationsSecurite: this.declarationSecuriteService.vueMairie(),
    }).subscribe({
      next: ({ demandes, informations, declarationsSecurite }) => {
        this.demandes = demandes;
        this.informations = informations;
        this.declarationsSecurite = declarationsSecurite;
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Impossible de charger la vue mairie.";
        this.isLoading = false;
      },
    });
  }

  headcount(d: DeclarationSecurite): number {
    return d.nombre_adultes + d.nombre_enfants;
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
