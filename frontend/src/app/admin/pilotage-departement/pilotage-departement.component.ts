import { Component, Input, OnChanges } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  Arborescence, DelegationGestion, DelegationGestionService, EtatAmorcage, EvenementDelegation, RepertoireEpci,
} from '../../services/delegation-gestion.service';

export type VuePilotage = 'invitations' | 'amorcage' | 'repertoires' | 'historique';

function sansAccent(v: string): string {
  return (v ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

/**
 * Pilotage d'une délégation départementale, affiché dans « Suivi du département » (22/11/2026 :
 * « je m'attendais à avoir le reste dans ce joli menu, avec l'historique ») : inviter les
 * collectivités et exporter leurs coordonnées, suivre l'amorçage, lire les répertoires des
 * intercommunalités et l'historique. La page « Délégations de gestion » ne garde que la
 * délégation elle-même : convention, qui agit, fin.
 */
@Component({
  selector: 'app-pilotage-departement',
  standalone: true,
  imports: [FormsModule, DatePipe],
  templateUrl: './pilotage-departement.component.html',
  styleUrl: '../delegations-gestion/delegations-gestion.component.scss',
})
export class PilotageDepartementComponent implements OnChanges {
  @Input() delegation: DelegationGestion | null = null;
  @Input() vue: VuePilotage = 'invitations';

  message = '';
  erreur = '';
  repertoires: Record<string, RepertoireEpci[]> = {};
  amorcages: Record<string, EtatAmorcage | null> = {};
  arbres: Record<string, Arborescence | null> = {};
  filtreArbre: Record<string, string> = {};
  /** Collectivités cochées dans l'arborescence. */
  selection: Record<string, Set<string>> = {};
  historique: EvenementDelegation[] | null = null;

  /** Libellés des étapes de l'amorçage, dans leur ordre. */
  readonly etapesAmorcage: { code: string; libelle: string }[] = [
    { code: 'referentiel', libelle: 'Référentiel des communes du département' },
    { code: 'annuaire', libelle: 'Répertoires officiels (mairies, EPCI, services de crise), rattachés aux communes qu\'ils servent' },
    { code: 'repertoires', libelle: 'Répertoires des communes et intercommunalités (EPCI, mairies membres, communes voisines)' },
    { code: 'adresses', libelle: 'Adresses de toutes les communes' },
    { code: 'risques', libelle: 'Risques de chaque commune (Géorisques, zonages, plans de prévention, servitudes, zones du PLU)' },
    { code: 'sites', libelle: 'Sites sensibles du département (écoles, santé, ICPE, DAE, équipements sportifs)' },
    { code: 'entreprises', libelle: 'Entreprises (élevages, hébergements, transport, commerces), commune par commune, au long cours' },
    { code: 'simulations', libelle: 'Pré-calcul des simulations d\'inondation et de ruissellement (une commune par minute)' },
  ];

  constructor(private service: DelegationGestionService) {}

  /** Charge ce que la vue demandée affiche, une fois. */
  ngOnChanges(): void {
    const d = this.delegation;
    if (!d) return;
    if (this.vue === 'invitations' && this.arbres[d.id] === undefined) this.voirArborescence(d);
    if (this.vue === 'amorcage' && this.amorcages[d.id] === undefined) this.voirAmorcage(d);
    if (this.vue === 'repertoires' && this.repertoires[d.id] === undefined) this.voirRepertoires(d);
    if (this.vue === 'historique') this.voirHistorique(d);
  }

  voirHistorique(d: DelegationGestion): void {
    this.historique = null;
    this.service.historique(d.id).subscribe({ next: h => this.historique = h, error: e => this.erreur = this.texteErreur(e) });
  }

  voirArborescence(d: DelegationGestion): void {
    this.service.arborescence(d.id).subscribe({ next: a => this.arbres[d.id] = a, error: e => this.erreur = this.texteErreur(e) });
  }

  /** Communes d'une branche qui correspondent au filtre (nom ou code), sans accents ni casse. */
  communesFiltrees(d: DelegationGestion, communes: Arborescence['epcis'][number]['communes']) {
    const f = sansAccent(this.filtreArbre[d.id] ?? '');
    return f ? communes.filter(c => sansAccent(c.nom).includes(f) || c.code.startsWith(f)) : communes;
  }

  estCochee(d: DelegationGestion, id: string): boolean { return !!this.selection[d.id]?.has(id); }

  cocher(d: DelegationGestion, id: string, coche: boolean): void {
    const s = this.selection[d.id] ?? (this.selection[d.id] = new Set());
    coche ? s.add(id) : s.delete(id);
  }

  /** Coche toutes les mairies d'une intercommunalité (et l'EPCI lui-même) qui n'ont encore aucun compte. */
  cocherBranche(d: DelegationGestion, branche: Arborescence['epcis'][number]): void {
    if (branche.institution && !branche.institution.membres) this.cocher(d, branche.institution.id, true);
    for (const c of branche.communes) if (c.mairie && !c.mairie.membres) this.cocher(d, c.mairie.id, true);
  }

  /** Toutes les collectivités du département qui n'ont encore aucun compte. */
  cocherToutesSansCompte(d: DelegationGestion): void {
    for (const b of this.arbres[d.id]?.epcis ?? []) this.cocherBranche(d, b);
  }

  /** Les coordonnées de la sélection en tableur, pour un publipostage ou des appels. */
  exporterSelection(d: DelegationGestion): void {
    const ids = [...(this.selection[d.id] ?? [])];
    if (!ids.length) return;
    this.service.exporterCoordonnees(d.id, ids).subscribe({
      next: blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `coordonnees-collectivites-${this.arbres[d.id]?.departement?.code ?? 'territoire'}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
        this.message = `Coordonnées de ${ids.length} collectivité(s) exportées.`;
      },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  inviterSelection(d: DelegationGestion): void {
    const ids = [...(this.selection[d.id] ?? [])];
    if (!ids.length) return;
    // 22/11/2026 : 556 courriels partis d'un clic, sans le vouloir. Un envoi groupé se confirme.
    if (!window.confirm(`Envoyer maintenant le courriel « Rejoindre votre collectivité » à ${ids.length} collectivité(s) ? `
      + 'Un courriel envoyé ne peut pas être rappelé.')) return;
    this.service.inviterCollectivites(d.id, ids).subscribe({
      next: r => {
        this.message = `${r.envoyees} invitation(s) envoyée(s)`
          + (r.deja_membres ? `, ${r.deja_membres} collectivité(s) déjà présente(s)` : '')
          + (r.sans_email.length ? `. Sans adresse officielle : ${r.sans_email.join(', ')}` : '.');
        this.selection[d.id] = new Set();
        this.voirArborescence(d);
      },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  voirAmorcage(d: DelegationGestion): void {
    this.service.amorcage(d.id).subscribe({ next: a => this.amorcages[d.id] = a, error: e => this.erreur = this.texteErreur(e) });
  }

  amorcer(d: DelegationGestion, etape?: string): void {
    this.service.amorcer(d.id, etape ? [etape] : undefined).subscribe({
      next: a => { this.amorcages[d.id] = a; this.message = 'Amorçage lancé : il se poursuit en tâche de fond, revenez voir son avancement.'; },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  comptesLisibles(comptes?: Record<string, number>): string {
    return comptes ? Object.entries(comptes).map(([k, v]) => `${k.replace(/_/g, ' ')} : ${v}`).join(' · ') : '';
  }

  voirRepertoires(d: DelegationGestion): void {
    this.service.repertoires(d.id).subscribe({ next: r => this.repertoires[d.id] = r, error: e => this.erreur = this.texteErreur(e) });
  }

  private texteErreur(e: any): string {
    const corps = e?.error;
    if (!corps) return 'Action impossible.';
    if (typeof corps === 'string') return corps;
    if (corps.error) return corps.error;
    if (corps.detail) return corps.detail;
    return Object.values(corps).flat().join(' ');
  }
}
