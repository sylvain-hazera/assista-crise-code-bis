import { Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { RelaisLocalService, RelaisVisible } from '../../../../services/relais-local.service';
import {
  ActionEmplacement, ChoixEmplacement, EntreePlan, OperationsChoix, choixParDefaut, operationsChoix,
} from '../../../mesh/plan-canaux';

/**
 * Plan de canaux d'une radio Meshtastic branchée, emplacement par emplacement.
 *
 * Règle du 14/11/2026 (backend/core/canaux_locaux.py) : Fr_Balise et Fr_EMCOM, puis le canal de
 * chaque crise de la commune et celui de la commune. Le 19/11/2026, Sylvain demande deux gestes en
 * plus des ajouts : **relier** un canal déjà présent à un canal d'Assista-Crise (une
 * correspondance, la radio n'est pas réécrite), et **remplacer** tel canal par tel autre dans le
 * même emplacement. **Rien n'est écrit sur la radio sans le clic de la personne**, et les canaux
 * en clé publique s'affichent avec leur avertissement.
 */
@Component({
  selector: 'app-canaux-radio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './canaux-radio.component.html',
  styleUrl: './canaux-radio.component.scss',
})
export class CanauxRadioComponent implements OnChanges {
  @Input({ required: true }) relais!: RelaisVisible;

  choix: ChoixEmplacement[] = [];
  enCours = false;
  resultat = '';
  erreur = '';
  private signature = '';

  constructor(private moteur: RelaisLocalService) {}

  ngOnChanges(): void {
    // Choix par défaut seulement quand la radio ou le plan changent : sinon chaque
    // rafraîchissement du moteur effacerait ce que la personne a choisi.
    const p = this.plan;
    const signature = JSON.stringify([
      p?.emplacements.map(e => [e.index, e.nom, e.role]) ?? [],
      p?.entrees.map(e => e.nom) ?? [], p?.correspondances ?? {},
    ]);
    if (p && signature !== this.signature) {
      this.signature = signature;
      this.choix = choixParDefaut(p.emplacements, p.proposition, p.entrees, p.correspondances);
    }
  }

  get plan() { return this.relais.plan; }

  get titreIsolement(): string {
    return this.plan?.isolee
      ? "Passerelle isolée : elle ne réémet que sa crise et sa commune, et ce qu'elle entend "
        + "n'est réémis par aucune autre passerelle."
      : 'Passerelle ouverte au réseau : elle réémet aussi ce qui ne concerne pas sa commune.';
  }

  get nomsIndisponibles(): string {
    return (this.plan?.proposition.indisponibles ?? []).map(e => e.nom).join(', ');
  }

  /** Ce que les choix actuels demandent, recalculé à chaque changement. */
  get operations(): OperationsChoix {
    const p = this.plan;
    return p ? operationsChoix(p.emplacements, this.choix, p.entrees)
      : { supprimer: [], ecrire: [], correspondances: {}, erreurs: [] };
  }

  /** Quelque chose à faire : une écriture, une suppression, ou des correspondances changées. */
  get aFaire(): boolean {
    const ops = this.operations;
    const avant = JSON.stringify(this.plan?.correspondances ?? {});
    return ops.ecrire.length > 0 || ops.supprimer.length > 0 || JSON.stringify(ops.correspondances) !== avant;
  }

  /** Un canal en clé publique va être écrit : l'avertissement doit être lu avant. */
  get publicsEcrits(): boolean {
    return this.operations.ecrire.some(o => o.entree.public && o.entree.role !== 'communautaire');
  }

  get resume(): string {
    const ops = this.operations;
    const morceaux = [];
    if (ops.ecrire.length) { morceaux.push(`${ops.ecrire.length} canal(aux) écrit(s) sur la radio`); }
    if (ops.supprimer.length) { morceaux.push(`${ops.supprimer.length} supprimé(s)`); }
    const n = Object.keys(ops.correspondances).length;
    if (n) { morceaux.push(`${n} correspondance(s)`); }
    return morceaux.join(', ');
  }

  emplacement(index: number) {
    return this.plan?.emplacements.find(x => x.index === index);
  }

  estOccupe(index: number): boolean {
    const e = this.emplacement(index);
    return !!e && e.role !== 0;
  }

  nomDe(index: number): string {
    const e = this.emplacement(index);
    if (!e || e.role === 0) { return '— libre —'; }
    return e.nom || (index === 0 ? 'primaire (préréglage)' : 'sans nom');
  }

  /** Le canal d'Assista-Crise que ce canal de la radio est déjà, par son nom. */
  reconnu(index: number): EntreePlan | undefined {
    const nom = this.emplacement(index)?.nom?.trim().toLowerCase();
    return nom ? this.plan?.entrees.find(p => p.nom.toLowerCase() === nom) : undefined;
  }

  actionsPossibles(index: number): { valeur: ActionEmplacement; libelle: string }[] {
    if (!this.estOccupe(index)) {
      return index === 0 ? [{ valeur: 'garder', libelle: 'Laisser tel quel' }]
        : [{ valeur: 'garder', libelle: 'Laisser libre' }, { valeur: 'ajouter', libelle: 'Ajouter…' }];
    }
    const actions: { valeur: ActionEmplacement; libelle: string }[] = [{ valeur: 'garder', libelle: 'Garder' }];
    if (this.emplacement(index)?.nom && !this.reconnu(index)) {
      actions.push({ valeur: 'relier', libelle: 'Garder et relier à…' });
    }
    if (index !== 0) {
      actions.push({ valeur: 'remplacer', libelle: 'Remplacer par…' });
      actions.push({ valeur: 'vider', libelle: 'Supprimer' });
    }
    return actions;
  }

  /** Les canaux qu'on peut viser : pour relier, ceux qui ont un identifiant ; pour écrire, ceux
   * dont on connaît la clé. */
  cibles(action: ActionEmplacement): EntreePlan[] {
    const entrees = this.plan?.entrees ?? [];
    return action === 'relier' ? entrees.filter(e => !!e.canal) : entrees.filter(e => e.disponible);
  }

  changerAction(c: ChoixEmplacement, action: ActionEmplacement): void {
    c.action = action;
    if (action === 'garder' || action === 'vider') { c.cible = null; }
    else if (c.cible && !this.cibles(action).some(e => e.nom === c.cible)) { c.cible = null; }
  }

  libelleRole(e: EntreePlan): string {
    return e.role === 'crise' ? 'crise' : e.role === 'commune' ? 'commune' : 'communautaire';
  }

  async appliquer(): Promise<void> {
    if (!this.plan) { return; }
    const ops = this.operations;
    if (ops.erreurs.length) { this.erreur = ops.erreurs[0]; return; }
    this.enCours = true;
    this.erreur = '';
    this.resultat = '';
    const resume = this.resume;
    try {
      await this.moteur.appliquerChoix(this.relais.compagnonId, ops);
      this.resultat = `Appliqué : ${resume || 'rien à changer'}.`;
    } catch (e) {
      this.erreur = this.moteur.lisible(e);
    } finally {
      this.enCours = false;
    }
  }
}
