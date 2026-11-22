import { Component, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, switchMap, of } from 'rxjs';

import {
  Arborescence, DelegationGestion, DelegationGestionService, EtatAmorcage, PersonneQuiAgit, RepertoireEpci,
} from '../../services/delegation-gestion.service';
import { Commune, LocationService } from '../../services/location.service';

/**
 * Délégations de gestion (21/11/2026) : une AASC exploite la plateforme pour une collectivité.
 *
 * Côté association : engager une commune (la mairie est créée si elle n'existe pas), enregistrer
 * la convention signée à l'avance, inviter la mairie, voir qui agit. Côté collectivité : voir la
 * délégation et la convention, exporter ses données, y mettre fin. La présence des personnes
 * vulnérables est donnée sans aucun détail (cercles anonymisés, nombre seulement) : le registre
 * lui-même n'est pas compris dans la délégation.
 */

function sansAccent(v: string): string {
  return (v ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}
@Component({
  selector: 'app-delegations-gestion',
  standalone: true,
  imports: [FormsModule, DatePipe],
  templateUrl: './delegations-gestion.component.html',
  styleUrl: './delegations-gestion.component.scss',
})
export class DelegationsGestionComponent implements OnInit {
  delegations: DelegationGestion[] = [];
  chargement = true;
  message = '';
  erreur = '';

  // Engager un département (le cas par défaut) ou une commune
  portee: 'departement' | 'commune' = 'departement';
  departementCode = '';
  recherche = '';
  propositions: Commune[] = [];
  commune: Commune | null = null;
  saisie = { reference: '', signeeLe: '', signataire: '', qualite: 'Président(e) du conseil départemental', dateFin: '' };
  document: File | null = null;
  envoi = false;
  private frappe = new Subject<string>();

  // Par délégation ouverte
  personnes: Record<string, PersonneQuiAgit[]> = {};
  presence: Record<string, { situees: number; non_situees: number } | null> = {};
  invitation: Record<string, { emails: string; fonction: string }> = {};
  retrait: Record<string, string> = {};
  retraitForce: Record<string, boolean> = {};
  crisesOuvertes: Record<string, string[]> = {};
  repertoires: Record<string, RepertoireEpci[]> = {};
  amorcages: Record<string, EtatAmorcage | null> = {};
  arbres: Record<string, Arborescence | null> = {};
  filtreArbre: Record<string, string> = {};
  /** Collectivités cochées dans l'arborescence, par délégation. */
  selection: Record<string, Set<string>> = {};

  /** Libellés des étapes de l'amorçage, dans leur ordre. */
  readonly etapesAmorcage: { code: string; libelle: string }[] = [
    { code: 'referentiel', libelle: 'Référentiel des communes du département' },
    { code: 'annuaire', libelle: 'Répertoires officiels (mairies, EPCI, services de crise)' },
    { code: 'adresses', libelle: 'Adresses de toutes les communes' },
    { code: 'risques', libelle: 'Risques de chaque commune (Géorisques, zonages, plans de prévention, Géoportail de l\'urbanisme)' },
    { code: 'sites', libelle: 'Sites sensibles du département (écoles, santé, ICPE, DAE, équipements sportifs)' },
    { code: 'entreprises', libelle: 'Entreprises (élevages, hébergements, transport, commerces), commune par commune, au long cours' },
    { code: 'simulations', libelle: 'Pré-calcul des simulations d\'inondation et de ruissellement (une commune par minute)' },
  ];

  constructor(private service: DelegationGestionService, private lieux: LocationService) {}

  ngOnInit(): void {
    this.charger();
    this.frappe.pipe(
      debounceTime(250), distinctUntilChanged(),
      switchMap(q => q.trim().length >= 2 ? this.lieux.searchCommunesByName(q) : of([] as Commune[])),
    ).subscribe(c => this.propositions = c.slice(0, 8));
  }

  charger(): void {
    this.chargement = true;
    this.service.lister().subscribe({
      next: d => { this.delegations = (d as any).results ?? d; this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = 'Impossible de charger les délégations.'; },
    });
  }

  /** La qualité proposée suit le choix : président(e) du conseil départemental, ou maire. */
  changerPortee(portee: 'departement' | 'commune'): void {
    this.portee = portee;
    const defauts = ['Maire', 'Président(e) du conseil départemental'];
    if (!this.saisie.qualite || defauts.includes(this.saisie.qualite)) {
      this.saisie.qualite = portee === 'departement' ? 'Président(e) du conseil départemental' : 'Maire';
    }
  }

  chercher(q: string): void { this.recherche = q; this.commune = null; this.frappe.next(q); }

  choisir(c: Commune): void { this.commune = c; this.recherche = c.name; this.propositions = []; }

  choisirDocument(evt: Event): void {
    this.document = (evt.target as HTMLInputElement).files?.[0] ?? null;
  }

  get peutEngager(): boolean {
    const territoire = this.portee === 'departement' ? /^(\d{2}|2[AB]|97\d)$/i.test(this.departementCode.trim()) : !!this.commune;
    return territoire && !!this.saisie.signeeLe && !this.envoi;
  }

  engager(): void {
    const f = new FormData();
    if (this.portee === 'departement') {
      f.append('departement_code', this.departementCode.trim().toUpperCase());
    } else if (this.commune) {
      f.append('commune_code', this.commune.code);
    } else {
      return;
    }
    f.append('convention_reference', this.saisie.reference);
    f.append('convention_signee_le', this.saisie.signeeLe);
    f.append('convention_signataire', this.saisie.signataire);
    f.append('convention_signataire_qualite', this.saisie.qualite);
    if (this.saisie.dateFin) f.append('date_fin', this.saisie.dateFin);
    if (this.document) f.append('convention_document', this.document);
    this.envoi = true; this.erreur = ''; this.message = '';
    this.service.creer(f).subscribe({
      next: d => {
        this.envoi = false;
        this.message = `${d.collectivite_nom} : délégation enregistrée. Vous pouvez maintenant inviter la mairie.`;
        this.commune = null; this.recherche = ''; this.document = null; this.departementCode = '';
        this.saisie = { reference: '', signeeLe: '', signataire: '', qualite: this.portee === 'departement' ? 'Président(e) du conseil départemental' : 'Maire', dateFin: '' };
        this.charger();
      },
      error: e => { this.envoi = false; this.erreur = this.texteErreur(e); },
    });
  }

  voirPersonnes(d: DelegationGestion): void {
    this.service.personnes(d.id).subscribe(p => this.personnes[d.id] = p);
  }

  voirPresence(d: DelegationGestion): void {
    const code = d.communes[0];
    if (!code) { this.presence[d.id] = null; return; }
    this.service.presence(code).subscribe({ next: p => this.presence[d.id] = p, error: () => this.presence[d.id] = null });
  }

  ouvrirInvitation(d: DelegationGestion): void {
    this.invitation[d.id] = this.invitation[d.id] ?? { emails: '', fonction: 'Mairie' };
  }

  inviter(d: DelegationGestion): void {
    const saisie = this.invitation[d.id];
    const emails = saisie.emails.split(/[\s,;]+/).filter(e => e.includes('@'));
    this.service.inviter(d.id, emails, saisie.fonction).subscribe({
      next: r => { this.message = `${r.invites} invitation(s) envoyée(s) à ${d.collectivite_nom}.`; delete this.invitation[d.id]; },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  exporter(d: DelegationGestion): void {
    this.service.exporter(d.collectivite).subscribe({
      next: blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `donnees-${d.collectivite_nom}.zip`;
        a.click();
        URL.revokeObjectURL(a.href);
      },
      error: e => this.erreur = this.texteErreur(e),
    });
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

  inviterSelection(d: DelegationGestion): void {
    const ids = [...(this.selection[d.id] ?? [])];
    if (!ids.length) return;
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

  /** Pendant une crise ouverte, le serveur demande une confirmation et un motif : on les affiche. */
  retirer(d: DelegationGestion): void {
    this.service.retirer(d.id, this.retrait[d.id] ?? '', !!this.retraitForce[d.id]).subscribe({
      next: () => { this.message = `Délégation de ${d.collectivite_nom} retirée.`; delete this.crisesOuvertes[d.id]; this.charger(); },
      error: e => {
        if (e?.error?.confirmation_requise) this.crisesOuvertes[d.id] = e.error.crises_ouvertes ?? [];
        this.erreur = this.texteErreur(e);
      },
    });
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
