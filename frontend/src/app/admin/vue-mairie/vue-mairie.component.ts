import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { forkJoin } from 'rxjs';

import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { OfferService } from '../../services/offer.service';
import { TeamService } from '../../services/team.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { DossierService } from '../../services/dossier.service';

import { Request } from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';
import { Offer } from '../../shared/models/offer.model';
import { Team } from '../../shared/models/team.model';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';
import { Dossier } from '../../shared/models/dossier.model';
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
  offres: Offer[] = [];
  equipes: Team[] = [];
  points: PointOperationnel[] = [];
  dossiers: Dossier[] = [];

  isLoading = true;
  errorMessage = '';

  readonly Status = Status;

  constructor(
    private requestService: RequestService,
    private informationService: InformationService,
    private declarationSecuriteService: DeclarationSecuriteService,
    private offerService: OfferService,
    private teamService: TeamService,
    private pointOperationnelService: PointOperationnelService,
    private dossierService: DossierService,
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
      offres: this.offerService.vueMairie(),
      equipes: this.teamService.vueMairie(),
      points: this.pointOperationnelService.vueMairie(),
      dossiers: this.dossierService.vueMairie(),
    }).subscribe({
      next: ({ demandes, informations, declarationsSecurite, offres, equipes, points, dossiers }) => {
        this.demandes = demandes;
        this.informations = informations;
        this.declarationsSecurite = declarationsSecurite;
        this.offres = offres;
        this.equipes = equipes;
        this.points = points;
        this.dossiers = dossiers;
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
