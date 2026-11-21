import { Component, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, switchMap, of } from 'rxjs';

import {
  DelegationGestion, DelegationGestionService, PersonneQuiAgit, RepertoireEpci,
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
  saisie = { reference: '', signeeLe: '', signataire: '', qualite: 'Maire', dateFin: '' };
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
        this.saisie = { reference: '', signeeLe: '', signataire: '', qualite: 'Maire', dateFin: '' };
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
