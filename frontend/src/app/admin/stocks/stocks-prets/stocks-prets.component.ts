import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { StockService } from '../../../services/stock.service';
import {
  EtatMaterielPrete, EtatStock, LABELS_ETAT_PRETE, LABELS_TYPE_TIERS, PretMateriel, SensPret, TiersStock, TypeTiersStock,
} from '../../../shared/models/stock.model';

interface NouveauPret {
  sens: SensPret; tiers: string; article: string; depot: string; designation: string; identification: string; quantite: number;
  date_debut: string; retour_prevu: string; etat_depart: EtatMaterielPrete; constat_depart: string; conditions: string;
}

/**
 * Prêts de matériel, dans les deux sens : l'institution prête à un particulier ou à un
 * professionnel, ou ceux-ci lui prêtent. Chaque prêt a une fiche d'état au départ et une au
 * retour, avec photos : c'est ce qui évite de discuter, au retour, de ce qui était déjà abîmé.
 */
@Component({
  selector: 'app-stocks-prets',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './stocks-prets.component.html',
  styleUrl: '../stocks.component.scss',
})
export class StocksPretsComponent implements OnInit {
  /** Le stock de l'institution : ses articles et ses dépôts, pour un prêt qui porte sur le stock. */
  @Input() etat: EtatStock | null = null;
  /** Un prêt a fait bouger le stock : la page doit relire son état. */
  @Output() stockChange = new EventEmitter<void>();

  readonly etats = LABELS_ETAT_PRETE;
  readonly typesTiers = LABELS_TYPE_TIERS;

  prets: PretMateriel[] = [];
  tiers: TiersStock[] = [];
  filtre: 'EN_COURS' | 'TOUS' = 'EN_COURS';
  erreur = '';
  message = '';
  envoi = false;

  nouveau: NouveauPret | null = null;
  nouveauTiers: { nom: string; type: TypeTiersStock; telephone: string; email: string } | null = null;
  /** Le prêt dont on remplit la fiche de retour. */
  retour: { pret: PretMateriel; etat_retour: EtatMaterielPrete; constat_retour: string; quantite_rendue: number } | null = null;
  depotPhoto = '';

  constructor(private stocks: StockService) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.stocks.prets().subscribe({ next: (p) => this.prets = p, error: (e) => this.erreur = this.lire(e, 'Les prêts n’ont pas pu être lus.') });
    this.stocks.tiers().subscribe({ next: (t) => this.tiers = t, error: () => {} });
  }

  get affiches(): PretMateriel[] { return this.filtre === 'TOUS' ? this.prets : this.prets.filter(p => p.statut === 'EN_COURS'); }
  get enRetard(): number { return this.prets.filter(p => p.en_retard).length; }
  get depots() { return (this.etat?.depots ?? []).filter(d => d.actif && !d.point); }
  get articles() { return (this.etat?.articles ?? []).filter(a => a.actif); }

  ouvrir(sens: SensPret): void {
    this.erreur = this.message = '';
    this.retour = null;
    this.nouveau = { sens, tiers: '', article: '', depot: this.depots.length === 1 ? this.depots[0].id : '', designation: '', identification: '',
      quantite: 1, date_debut: new Date().toISOString().slice(0, 10), retour_prevu: '', etat_depart: 'BON', constat_depart: '', conditions: '' };
  }

  get complet(): boolean {
    const n = this.nouveau;
    return !!n && !!n.tiers && n.quantite > 0 && !!n.date_debut && (!!n.article ? !!n.depot : !!n.designation.trim());
  }

  creerTiers(): void {
    const t = this.nouveauTiers;
    if (!t || !t.nom.trim()) return;
    this.stocks.enregistrerTiers(t).subscribe({
      next: (cree) => { this.tiers = [cree, ...this.tiers]; if (this.nouveau) this.nouveau.tiers = cree.id; this.nouveauTiers = null; },
      error: (e) => this.erreur = this.lire(e, 'Cette personne n’a pas pu être enregistrée.'),
    });
  }

  enregistrer(): void {
    const n = this.nouveau;
    if (!n || !this.complet) return;
    const corps: Record<string, unknown> = { sens: n.sens, tiers: n.tiers, quantite: n.quantite, date_debut: n.date_debut, etat_depart: n.etat_depart };
    (['article', 'depot', 'designation', 'identification', 'retour_prevu', 'constat_depart', 'conditions'] as const)
      .forEach(c => { if (n[c]) corps[c] = n[c]; });
    this.envoi = true;
    this.erreur = '';
    this.stocks.ouvrirPret(corps).subscribe({
      next: (pret) => {
        this.envoi = false;
        this.nouveau = null;
        this.prets = [pret, ...this.prets];
        this.message = `Prêt enregistré : ${pret.designation}. Ajoutez les photos de son état au départ.`;
        if (pret.article) this.stockChange.emit();
      },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce prêt n’a pas pu être enregistré.'); },
    });
  }

  ouvrirRetour(pret: PretMateriel): void {
    this.erreur = this.message = '';
    this.nouveau = null;
    this.retour = { pret, etat_retour: pret.etat_depart, constat_retour: '', quantite_rendue: +pret.quantite };
  }

  rendre(): void {
    const r = this.retour;
    if (!r) return;
    this.envoi = true;
    this.erreur = '';
    this.stocks.rendrePret(r.pret.id, { etat_retour: r.etat_retour, constat_retour: r.constat_retour, quantite_rendue: r.quantite_rendue }).subscribe({
      next: (pret) => {
        this.envoi = false;
        this.retour = null;
        this.remplacer(pret);
        this.message = pret.statut === 'LITIGE' ? 'Retour enregistré avec réserve : la fiche garde le constat.' : 'Retour enregistré.';
        if (pret.article) this.stockChange.emit();
      },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce retour n’a pas pu être enregistré.'); },
    });
  }

  /** Photo d'état : au départ tant que le prêt court, au retour ensuite. */
  ajouterPhoto(pret: PretMateriel, evenement: Event): void {
    const champ = evenement.target as HTMLInputElement;
    const photo = champ.files?.[0];
    if (!photo) return;
    const moment = pret.statut === 'EN_COURS' ? 'DEPART' : 'RETOUR';
    this.depotPhoto = pret.id;
    this.stocks.photoPret(pret.id, moment, photo).subscribe({
      next: () => {
        this.depotPhoto = '';
        champ.value = '';
        this.remplacer({ ...pret, photos: { ...pret.photos, [moment === 'DEPART' ? 'depart' : 'retour']: pret.photos[moment === 'DEPART' ? 'depart' : 'retour'] + 1 } });
      },
      error: (e) => { this.depotPhoto = ''; this.erreur = this.lire(e, 'Cette photo n’a pas pu être déposée.'); },
    });
  }

  fiche(pret: PretMateriel): void {
    this.stocks.fichePret(pret.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = 'fiche-de-pret.pdf';
        lien.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      },
      error: (e) => this.erreur = this.lire(e, 'La fiche n’a pas pu être éditée.'),
    });
  }

  nombre(valeur: string | number | null): string { return valeur === null || valeur === '' ? '' : (+valeur).toLocaleString('fr-FR', { maximumFractionDigits: 3 }); }

  private remplacer(pret: PretMateriel): void { this.prets = this.prets.map(p => p.id === pret.id ? pret : p); }

  private lire(e: any, defaut: string): string {
    const corps = e?.error;
    if (!corps || typeof corps !== 'object') return defaut;
    if (typeof corps.detail === 'string') return corps.detail;
    const premier = Object.values(corps)[0];
    return (Array.isArray(premier) ? premier[0] : premier) as string || defaut;
  }
}
