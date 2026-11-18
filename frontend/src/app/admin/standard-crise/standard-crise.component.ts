import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { CrisisService } from '../../services/crisis.service';
import {
  AppelStandard, NatureAppel, PointDeSituation, StandardCriseService, SuiteAppel, SyntheseAppels, FicheLiee } from '../../services/standard-crise.service';
import { Crisis } from '../../shared/models/crisis.model';

/**
 * Standard de crise et point de situation (17/11/2026).
 *
 * **Standard** : une fiche par appel reçu — qui, pour quoi, quelle suite. La nature reprend les
 * catégories de l'application (demande d'aide, offre, signalement). Un appel qui demande une
 * intervention ouvre un dossier, que les équipes traitent comme les autres.
 *
 * **Point de situation** : les chiffres que la collectivité annonce à chaque point avec la
 * préfecture. Ils existent déjà dans l'application ; le serveur les rassemble sur toute la
 * crise, et en donne le texte prêt à coller.
 */
@Component({
  selector: 'app-standard-crise',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './standard-crise.component.html',
  styleUrl: './standard-crise.component.scss',
})
export class StandardCriseComponent implements OnInit {
  onglet: 'appels' | 'situation' = 'appels';
  crises: Crisis[] = [];
  criseId: string | null = null;
  appels: AppelStandard[] = [];
  synthese: SyntheseAppels | null = null;
  situation: PointDeSituation | null = null;
  erreur = '';
  message = '';
  envoi = false;

  /** La fiche en cours de saisie : l'agent a le combiné à l'oreille, tout tient sur un écran. */
  saisie = this.ficheVide();
  /** La fiche à laquelle on donne une suite. */
  enCloture: AppelStandard | null = null;
  suiteDonnee = '';

  readonly titresFamilles: Record<string, string> = {
    population: 'Population', demandes: 'Demandes et dossiers', moyens: 'Moyens engagés',
    standard: 'Standard de crise', relogement: 'Relogement',
  };
  readonly ordreFamilles = ['population', 'demandes', 'moyens', 'standard', 'relogement'];

  constructor(
    private service: StandardCriseService,
    private crisisService: CrisisService,
    private route: ActivatedRoute,
  ) {}

  ngOnInit(): void {
    if (this.route.snapshot.data['onglet'] === 'situation') this.onglet = 'situation';
    this.crisisService.getAll().subscribe({
      next: (crises) => {
        this.crises = crises.filter(c => c.is_open !== false);
        // Une seule crise en cours : inutile de la faire choisir à quelqu'un qui décroche.
        if (this.crises.length === 1) this.criseId = this.crises[0].id;
        this.charger();
      },
      error: () => this.charger(),
    });
  }

  /** Paramètres passés au formulaire du public : il sait ainsi qu'il est rempli pour autrui. */
  pourAutrui(): Record<string, string> {
    return this.criseId ? { standard: '1', crise: this.criseId } : { standard: '1' };
  }

  /** Où se lit et se traite la vraie fiche créée pendant l'appel. */
  lienFiche(fiche: FicheLiee): string[] {
    return fiche.type === 'recherche' ? ['/admin/recherches-personnes', fiche.id] : ['/admin/signalements'];
  }

  libelleFiche(fiche: FicheLiee): string {
    return { demande: 'Voir la demande', offre: "Voir l'offre", information: 'Voir le signalement', recherche: 'Voir la recherche' }[fiche.type];
  }

  private ficheVide() {
    return { nature: 'RENSEIGNEMENT' as NatureAppel, objet: '', appelant_nom: '', appelant_telephone: '', lieu: '' };
  }

  ouvrir(onglet: 'appels' | 'situation'): void {
    this.onglet = onglet;
    this.erreur = '';
    this.charger();
  }

  charger(): void {
    if (this.onglet === 'situation') {
      this.situation = null;
      if (!this.criseId) return;
      this.service.pointDeSituation(this.criseId).subscribe({
        next: (point) => this.situation = point,
        error: () => this.erreur = "Le point de situation n'a pas pu être établi.",
      });
      return;
    }
    this.service.appels(this.criseId).subscribe({
      next: (appels) => this.appels = appels,
      error: (err) => this.erreur = err?.error?.detail || "Les appels n'ont pas pu être chargés.",
    });
    this.service.synthese(this.criseId).subscribe({ next: (s) => this.synthese = s, error: () => {} });
  }

  enregistrer(): void {
    if (!this.saisie.objet.trim()) { this.erreur = "Notez en une phrase l'objet de l'appel."; return; }
    this.envoi = true;
    this.erreur = '';
    this.service.enregistrer({ ...this.saisie, crise: this.criseId }).subscribe({
      next: (appel) => {
        this.envoi = false;
        this.message = `Fiche d'appel n° ${appel.numero} enregistrée.`;
        this.saisie = this.ficheVide();
        this.charger();
      },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.objet?.[0] || "La fiche n'a pas pu être enregistrée."; },
    });
  }

  ouvrirDossier(appel: AppelStandard, priorite: 'NORMALE' | 'URGENTE'): void {
    this.service.ouvrirDossier(appel.id, priorite).subscribe({
      next: (maj) => { this.message = `Dossier ${maj.dossier_numero} ouvert pour l'appel n° ${maj.numero}.`; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || "Le dossier n'a pas pu être ouvert.",
    });
  }

  clore(suite: SuiteAppel): void {
    if (!this.enCloture) return;
    this.service.clore(this.enCloture.id, suite, this.suiteDonnee.trim()).subscribe({
      next: () => { this.enCloture = null; this.suiteDonnee = ''; this.charger(); },
      error: () => this.erreur = "La suite n'a pas pu être enregistrée.",
    });
  }

  copier(): void {
    if (!this.situation) return;
    navigator.clipboard?.writeText(this.situation.texte).then(
      () => this.message = 'Point de situation copié.',
      () => this.erreur = "La copie n'a pas fonctionné : sélectionnez le texte à la main.",
    );
  }
}
