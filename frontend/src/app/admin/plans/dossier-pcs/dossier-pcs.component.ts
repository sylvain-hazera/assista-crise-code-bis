import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Observable } from 'rxjs';

import { DossierPcs, DossierPcsService, PartieAdministrative } from '../../../services/dossier-pcs.service';

/**
 * Le document du plan communal de sauvegarde.
 *
 * Le plan n'est pas rédigé ici : il existe déjà, par morceaux, dans le reste de l'application
 * (risques, sites sensibles, dispositifs et missions types, annuaire, équipes, lieux d'accueil).
 * Ce panneau dit ce que le document en reprendra, **ce qui manque encore**, recueille les trois
 * choses que rien d'autre ne porte (l'arrêté, le poste de commandement, les modalités
 * d'activation), tient le tableau des mises à jour, et sort le PDF.
 *
 * La liste des personnes vulnérables n'en fait pas partie : elle s'édite depuis leur écran, par
 * les personnes désignées par le maire.
 */
@Component({
  selector: 'app-dossier-pcs',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './dossier-pcs.component.html',
  styleUrl: './dossier-pcs.component.scss',
})
export class DossierPcsComponent implements OnInit {
  dossier: DossierPcs | null = null;
  /** Vrai quand le compte n'a pas de collectivité : il n'y a alors pas de plan à montrer. */
  sansCollectivite = false;
  erreur = '';
  message = '';

  saisie: PartieAdministrative = {
    arrete_numero: '', arrete_date: null, lieu_pcc: '', lieu_pcc_repli: '', modalites_activation: '',
  };
  formulaireOuvert = false;
  enregistrement = false;
  edition = false;

  objetRevision = '';
  ajoutRevision = false;

  constructor(private service: DossierPcsService) {}

  ngOnInit(): void {
    this.service.lire().subscribe({
      next: (dossier) => this.recevoir(dossier),
      error: (e) => {
        if (e?.status === 403) this.sansCollectivite = true;
        else this.erreur = 'Impossible de lire le dossier du plan.';
      },
    });
  }

  private recevoir(dossier: DossierPcs): void {
    this.dossier = dossier;
    this.saisie = {
      arrete_numero: dossier.arrete_numero, arrete_date: dossier.arrete_date, lieu_pcc: dossier.lieu_pcc,
      lieu_pcc_repli: dossier.lieu_pcc_repli, modalites_activation: dossier.modalites_activation,
    };
  }

  /** Ce que le document reprendra du reste de l'application, en une phrase. */
  get repris(): string {
    const c = this.dossier?.contenu;
    if (!c) return '';
    const pluriel = (n: number, mot: string, pl = mot + 's') => `${n} ${n > 1 ? pl : mot}`;
    return [
      pluriel(c.risques, 'risque'), pluriel(c.sites_sensibles, 'site sensible', 'sites sensibles'),
      `${pluriel(c.dispositifs, 'dispositif')} (${pluriel(c.missions_types, 'mission type', 'missions types')})`,
      pluriel(c.interlocuteurs, 'interlocuteur'), pluriel(c.membres, 'membre'),
      pluriel(c.equipes, 'équipe'), pluriel(c.points, "lieu d'accueil ou point", "lieux d'accueil ou points"),
    ].join(', ');
  }

  enregistrer(): void {
    this.enregistrement = true;
    this.erreur = this.message = '';
    this.service.enregistrer({ ...this.saisie, arrete_date: this.saisie.arrete_date || null }).subscribe({
      next: (dossier) => {
        this.recevoir(dossier);
        this.enregistrement = false;
        this.formulaireOuvert = false;
        this.message = 'Enregistré. Le document édité reprendra ces informations.';
      },
      error: () => { this.enregistrement = false; this.erreur = "L'enregistrement a échoué."; },
    });
  }

  ajouterRevision(): void {
    const objet = this.objetRevision.trim();
    if (!objet) return;
    this.ajoutRevision = true;
    this.erreur = this.message = '';
    this.service.ajouterRevision(objet).subscribe({
      next: (dossier) => { this.recevoir(dossier); this.objetRevision = ''; this.ajoutRevision = false; },
      error: () => { this.ajoutRevision = false; this.erreur = "La mise à jour n'a pas pu être inscrite."; },
    });
  }

  /** Cartes d'annexe sur le Plan IGN (une image par carte, demandée à l'IGN pour la seule
   * emprise de la commune) plutôt qu'en schéma sans fond. Décoché par défaut : le schéma
   * n'attend aucun service extérieur au moment d'imprimer. */
  fondIgn = false;

  editer(): void {
    this.telecharger(this.service.document(this.fondIgn), 'plan-communal-de-sauvegarde');
  }

  /** Le DICRIM : ce que les habitants doivent savoir des risques. Public, sans aucun nom. */
  editerDicrim(): void {
    this.telecharger(this.service.dicrim(), 'dicrim');
  }

  private telecharger(source: Observable<Blob>, nom: string): void {
    this.edition = true;
    this.erreur = this.message = '';
    source.subscribe({
      next: (blob) => {
        this.edition = false;
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = `${nom}-${this.dossier?.commune.code || 'collectivite'}.pdf`;
        lien.click();
        URL.revokeObjectURL(url);
      },
      error: () => { this.edition = false; this.erreur = "Le document n'a pas pu être édité."; },
    });
  }
}
