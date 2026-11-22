import { Component, OnInit } from '@angular/core';
import { DatePipe, DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Observable, forkJoin, of, catchError } from 'rxjs';

import {
  DelegationGestion, DelegationGestionService, Enrolement, FicheArbre, SuiviBranche, SuiviDepartement,
} from '../../services/delegation-gestion.service';
import { PilotageDepartementComponent, VuePilotage } from '../pilotage-departement/pilotage-departement.component';

interface DepartementSuivi { delegation: DelegationGestion; suivi: SuiviDepartement; }

/**
 * Suivi du département (21/11/2026), pour un comité départemental : chaque intercommunalité en
 * carte, et dans chacune ses communes — où en est leur arrivée sur la plateforme, et où en est
 * leur plan (PCS pour une commune, PICS pour l'intercommunalité). Une branche se calcule quand
 * on la déplie : l'avancement d'un plan lit une dizaine de tables par commune.
 */
@Component({
  selector: 'app-suivi-departement',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, FormsModule, NgTemplateOutlet, PilotageDepartementComponent],
  templateUrl: './suivi-departement.component.html',
  styleUrl: './suivi-departement.component.scss',
})
export class SuiviDepartementComponent implements OnInit {
  departements: DepartementSuivi[] = [];
  choisi: DepartementSuivi | null = null;
  chargement = true;
  erreur = '';
  epciOuvert: string | null = null;
  branche: SuiviBranche | null = null;
  chargementBranche = false;
  communeOuverte: string | null = null;
  message = '';
  /** Saisie des coordonnées de la collectivité ouverte (commune ou intercommunalité). */
  saisie: { institution: string; email: string; telephone: string; refNom: string; refFonction: string; refEmail: string; refTelephone: string } | null = null;

  /** Le menu du département : l'avancement commune par commune, puis le pilotage de la délégation. */
  vue: 'communes' | VuePilotage = 'communes';
  readonly onglets: { code: 'communes' | VuePilotage; icone: string; libelle: string; aide: string }[] = [
    { code: 'communes', icone: 'location_city', libelle: 'Communes', aide: 'Arrivée et avancement des plans' },
    { code: 'invitations', icone: 'forward_to_inbox', libelle: 'Invitations', aide: 'Inviter, exporter les coordonnées' },
    { code: 'amorcage', icone: 'cloud_download', libelle: 'Amorçage', aide: 'Ce qui est récupéré à l\'avance' },
    { code: 'repertoires', icone: 'contact_phone', libelle: 'Répertoires', aide: 'Contacts des intercommunalités' },
    { code: 'historique', icone: 'history', libelle: 'Historique', aide: 'Ce qui a été fait, et par qui' },
  ];

  readonly libelles: Record<Enrolement, string> = {
    a_rejoint: 'A rejoint', invitee: 'Invitée', non_invitee: 'À inviter',
    pas_d_adresse: "Pas d'adresse officielle", non_creee: 'Mairie à récupérer',
  };

  constructor(private service: DelegationGestionService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.service.lister().subscribe({
      next: liste => {
        const toutes: DelegationGestion[] = (liste as any).results ?? liste;
        const actives = toutes.filter(d => d.en_vigueur);
        if (!actives.length) { this.chargement = false; return; }
        const appels: Observable<SuiviDepartement | null>[] =
          actives.map(d => this.service.suivi(d.id).pipe(catchError(() => of(null))));
        forkJoin(appels).subscribe((suivis: (SuiviDepartement | null)[]) => {
          this.departements = actives
            .map((delegation, i) => ({ delegation, suivi: suivis[i] }))
            .filter((x): x is DepartementSuivi => !!x.suivi);
          // Venu de « Délégations de gestion » : le département de cette délégation.
          const voulue = this.route.snapshot.queryParamMap.get('delegation');
          this.choisi = this.departements.find(x => x.delegation.id === voulue) ?? this.departements[0] ?? null;
          this.chargement = false;
        });
      },
      error: () => { this.chargement = false; this.erreur = 'Impossible de charger le suivi.'; },
    });
  }

  choisir(d: DepartementSuivi): void { this.choisi = d; this.epciOuvert = null; this.branche = null; this.vue = 'communes'; }

  part(n: number, total: number): number { return total ? Math.round(100 * n / total) : 0; }

  ouvrir(code: string): void {
    if (!this.choisi) return;
    if (this.epciOuvert === code) { this.epciOuvert = null; this.branche = null; return; }
    this.epciOuvert = code;
    this.branche = null;
    this.communeOuverte = null;
    this.chargementBranche = true;
    this.service.suiviBranche(this.choisi.delegation.id, code).subscribe({
      next: b => { this.branche = b; this.chargementBranche = false; },
      error: () => { this.chargementBranche = false; this.erreur = "Impossible de charger cette intercommunalité."; },
    });
  }

  basculerCommune(code: string): void {
    this.communeOuverte = this.communeOuverte === code ? null : code;
    this.saisie = null;
  }

  /** Ouvre la saisie des coordonnées d'une collectivité (mairie ou intercommunalité). */
  modifierCoordonnees(f: FicheArbre): void {
    this.saisie = {
      institution: f.id, email: f.email ?? '', telephone: f.telephone ?? '',
      refNom: f.referent?.nom ?? '', refFonction: f.referent?.fonction ?? '',
      refEmail: f.referent?.email ?? '', refTelephone: f.referent?.telephone ?? '',
    };
  }

  enregistrerCoordonnees(): void {
    const s = this.saisie;
    if (!s || !this.choisi) return;
    this.service.coordonnees(this.choisi.delegation.id, s.institution,
      { email: s.email.trim(), telephone: s.telephone.trim() },
      { nom: s.refNom.trim(), fonction: s.refFonction.trim(), email: s.refEmail.trim() || null, telephone: s.refTelephone.trim() || null },
    ).subscribe({
      next: () => { this.message = 'Coordonnées enregistrées.'; this.saisie = null; this.recharger(); },
      error: e => this.erreur = e?.error?.error ?? "Enregistrement impossible.",
    });
  }

  inviterMaintenant(f: FicheArbre): void {
    if (!this.choisi) return;
    this.service.inviterCollectivites(this.choisi.delegation.id, [f.id]).subscribe({
      next: r => {
        this.message = r.envoyees ? `Invitation envoyée à ${f.nom}.`
          : r.sans_email.length ? `${f.nom} : aucune adresse, indiquez une personne référente.` : `${f.nom} a déjà des comptes.`;
        this.recharger();
      },
      error: e => this.erreur = e?.error?.error ?? "Envoi impossible.",
    });
  }

  /** Recharge la branche ouverte sans la replier. */
  private recharger(): void {
    if (!this.choisi || !this.epciOuvert) return;
    const code = this.epciOuvert;
    this.service.suiviBranche(this.choisi.delegation.id, code).subscribe(b => this.branche = b);
  }

  /** Couleur de la jauge : rouge sous 40 %, orange sous 75 %, vert au-delà. */
  niveau(pourcentage: number): 'bas' | 'moyen' | 'haut' {
    return pourcentage < 40 ? 'bas' : pourcentage < 75 ? 'moyen' : 'haut';
  }
}
