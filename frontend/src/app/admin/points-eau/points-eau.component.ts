import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AuthService } from '../../auth/services/auth.service';
import { CouverturePEI, PointsEauService, RapportImportPEI, SignalementPEI } from '../../services/points-eau.service';

type Onglet = 'signalements' | 'import' | 'couverture';

/** Points d'eau incendie (24/11/2026) : la commune valide les signalements de terrain et les
 * transmet au SDIS (export au schéma national) ; l'administrateur importe la base d'un SDIS ;
 * la couverture dit où en est le relevé OpenStreetMap, département par département. */
@Component({
  selector: 'app-points-eau',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './points-eau.component.html',
  styleUrl: './points-eau.component.scss',
})
export class PointsEauComponent implements OnInit {
  onglet: Onglet = 'signalements';
  filtre = 'A_VALIDER';
  signalements: SignalementPEI[] = [];
  chargement = false;
  erreur: string | null = null;
  enCours: string | null = null;
  motifs: Record<string, string> = {};
  numeros: Record<string, string> = {};
  couverture: CouverturePEI | null = null;
  departementImport = '';
  fichierImport: File | null = null;
  rapport: RapportImportPEI | null = null;
  readonly filtres = [
    { valeur: 'A_VALIDER', libelle: 'À valider' }, { valeur: 'VALIDE', libelle: 'Validés' },
    { valeur: 'TRANSMIS_SDIS', libelle: 'Transmis au SDIS' }, { valeur: 'REJETE', libelle: 'Rejetés' },
    { valeur: '', libelle: 'Tous' },
  ];
  readonly natures: Record<string, string> = {
    PI: "Poteau d'incendie", BI: "Bouche d'incendie", PA: "Point d'aspiration", CI: 'Citerne ou réserve',
  };

  constructor(private service: PointsEauService, private auth: AuthService) {}

  get estAdmin(): boolean { return this.auth.isAdmin(); }

  ngOnInit(): void {
    this.charger();
    this.service.couverture().subscribe({ next: c => this.couverture = c, error: () => {} });
  }

  choisir(onglet: Onglet): void {
    this.onglet = onglet;
    if (onglet === 'couverture') this.service.couverture().subscribe({ next: c => this.couverture = c, error: () => {} });
  }

  charger(): void {
    this.chargement = true;
    this.service.signalements(this.filtre || undefined).subscribe({
      next: s => { this.signalements = s; this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = 'Les signalements n\'ont pas pu être chargés.'; },
    });
  }

  lienCarte(s: SignalementPEI): string {
    return `https://www.openstreetmap.org/?mlat=${s.latitude}&mlon=${s.longitude}#map=18/${s.latitude}/${s.longitude}`;
  }

  decider(s: SignalementPEI, geste: 'valider' | 'rejeter'): void {
    if (geste === 'rejeter' && !(this.motifs[s.id] || '').trim()) {
      this.erreur = 'Indiquez le motif du rejet : il est envoyé à la personne qui a signalé.';
      return;
    }
    this.erreur = null;
    this.enCours = s.id;
    this.service.decider(s.id, geste, this.motifs[s.id] || '').subscribe({
      next: () => { this.enCours = null; this.charger(); this.rafraichirCompte(); },
      error: e => { this.enCours = null; this.erreur = this.message(e); },
    });
  }

  transmettre(s: SignalementPEI): void {
    this.enCours = s.id;
    this.service.transmis(s.id, this.numeros[s.id] || '').subscribe({
      next: () => { this.enCours = null; this.charger(); },
      error: e => { this.enCours = null; this.erreur = this.message(e); },
    });
  }

  exporter(): void {
    this.service.exporter().subscribe({
      next: blob => {
        const lien = document.createElement('a');
        lien.href = URL.createObjectURL(blob);
        lien.download = 'points-eau-schema-national.csv';
        lien.click();
        URL.revokeObjectURL(lien.href);
      },
      error: e => this.erreur = this.message(e),
    });
  }

  choisirFichier(evenement: Event): void {
    this.fichierImport = (evenement.target as HTMLInputElement).files?.[0] ?? null;
  }

  importer(): void {
    if (!this.departementImport.trim() || !this.fichierImport) {
      this.erreur = 'Choisissez le département et le fichier du SDIS.';
      return;
    }
    this.erreur = null;
    this.enCours = 'import';
    this.service.importer(this.departementImport.trim().toUpperCase(), this.fichierImport).subscribe({
      next: r => { this.enCours = null; this.rapport = r; },
      error: e => { this.enCours = null; this.erreur = this.message(e); },
    });
  }

  private rafraichirCompte(): void {
    this.service.couverture().subscribe({ next: c => this.couverture = c, error: () => {} });
  }

  private message(e: any): string {
    const corps = e?.error;
    return (corps && (corps.detail || corps.fichier || corps.error)) || 'L\'opération a échoué. Réessayez.';
  }
}
