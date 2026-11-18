import { CanalAlerte, EtatAlertes } from '../../services/alerte-habitants.service';
import { PiecesPlanComponent } from '../../shared/components/common/pieces-plan/pieces-plan.component';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';
import { ZoneService } from '../../services/zone.service';
import { TeamService } from '../../services/team.service';
import { Team } from '../../shared/models/team.model';
import { Zone } from '../../shared/models/zone.model';
import { Ligne, PARAGRAPHES_EN_LISTE, ParagrapheListe } from './pcs-listes.config';

/** Nom de la zone créée d'office pour chaque collectivité : ce n'est pas un quartier. */
const ZONE_AUTOMATIQUE = 'Mon territoire';

/**
 * Un paragraphe du plan communal de sauvegarde tenu en liste : organigramme du poste de
 * commandement, moyens d'alerte, exercices. Le paragraphe affiché vient de la route
 * (`data.paragraphe`), sa description de `pcs-listes.config.ts`.
 *
 * Comme les autres écrans du plan, il dit d'abord à quoi le paragraphe sert en crise, et rien de
 * ce qu'on n'y a pas mis n'empêche d'ouvrir une crise.
 */
@Component({
  selector: 'app-pcs-liste',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, PiecesPlanComponent],
  templateUrl: './pcs-liste.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class PcsListeComponent implements OnInit {
  paragraphe!: ParagrapheListe;
  /** Page « Alerte de la population » seulement : les moyens numériques de la collectivité
   * (messagerie, application, courriel, SMS, radio), avec ce qui manque à chacun. */
  canauxNumeriques: CanalAlerte[] = [];
  lignes: Ligne[] = [];
  zones: Zone[] = [];
  equipes: Team[] = [];
  chargement = true;
  sansCollectivite = false;
  erreur = '';

  saisie: Record<string, any> = {};
  enModification: string | null = null;
  formulaireOuvert = false;
  enregistrement = false;

  constructor(private route: ActivatedRoute, private http: HttpClient, private zoneService: ZoneService,
              private teamService: TeamService) {}

  private get url(): string {
    return `${environment.apiUrl}/${this.paragraphe.ressource}/`;
  }

  ngOnInit(): void {
    this.paragraphe = PARAGRAPHES_EN_LISTE[this.route.snapshot.data['paragraphe']];
    if (this.paragraphe.ressource === 'pcs-moyens-alerte') {
      this.http.get<EtatAlertes>(`${environment.apiUrl}/alertes-population/`).subscribe({
        next: (etat) => { this.canauxNumeriques = etat.apercu.canaux; }, error: () => {},
      });
    }
    this.charger();
    if (this.paragraphe.champs.some(c => c.type === 'zone')) {
      // Les quartiers sont facultatifs : s'ils ne se chargent pas, le champ reste vide et c'est tout.
      this.zoneService.getAll().subscribe({
        next: (zones) => { this.zones = zones.filter(z => z.nom !== ZONE_AUTOMATIQUE); }, error: () => {},
      });
    }
    if (this.paragraphe.champs.some(c => c.type === 'equipe')) {
      // Les équipes de la collectivité : celles qu'on peut relier à une fonction.
      this.teamService.equipesInstitution().subscribe({ next: (equipes) => { this.equipes = equipes; }, error: () => {} });
    }
  }

  /** Champs qui désignent un autre objet de la collectivité : vides, ils valent « aucun ». */
  private estUnLien(type: string): boolean {
    return type === 'zone' || type === 'equipe';
  }

  private charger(): void {
    this.http.get<Ligne[]>(this.url).subscribe({
      next: (lignes) => { this.lignes = lignes; this.chargement = false; },
      error: (e) => {
        this.chargement = false;
        this.sansCollectivite = e?.status === 403;
        if (!this.sansCollectivite) this.erreur = 'Impossible de lire ce paragraphe du plan.';
      },
    });
  }

  private saisieVide(): Record<string, any> {
    const vide: Record<string, any> = {};
    for (const champ of this.paragraphe.champs) {
      vide[champ.cle] = champ.type === 'choix' ? champ.options![0].valeur
        : champ.type === 'date' ? new Date().toISOString().slice(0, 10)
        : this.estUnLien(champ.type) ? null : '';
    }
    return vide;
  }

  ouvrirAjout(): void {
    this.saisie = this.saisieVide();
    this.enModification = null;
    this.formulaireOuvert = true;
    this.erreur = '';
  }

  modifier(ligne: Ligne): void {
    this.saisie = {};
    for (const champ of this.paragraphe.champs) this.saisie[champ.cle] = ligne[champ.cle] ?? (this.estUnLien(champ.type) ? null : '');
    this.enModification = ligne.id;
    this.formulaireOuvert = true;
    this.erreur = '';
  }

  /** Texte fourni par le serveur pour un champ laissé vide (la fiche réflexe type). */
  parDefaut(cle: string | undefined): string {
    if (!cle) return '';
    const ligne = this.lignes.find(l => l.id === this.enModification);
    return ligne ? (ligne[cle] || '') : '';
  }

  enregistrer(): void {
    this.enregistrement = true;
    this.erreur = '';
    const donnees = { ...this.saisie };
    for (const champ of this.paragraphe.champs) {
      if (this.estUnLien(champ.type)) donnees[champ.cle] = donnees[champ.cle] || null;
      else if (typeof donnees[champ.cle] === 'string') donnees[champ.cle] = donnees[champ.cle].trim();
    }
    const appel = this.enModification
      ? this.http.patch<Ligne>(`${this.url}${this.enModification}/`, donnees)
      : this.http.post<Ligne>(this.url, donnees);
    appel.subscribe({
      next: () => { this.enregistrement = false; this.formulaireOuvert = false; this.charger(); },
      error: (e) => {
        this.enregistrement = false;
        const detail = e?.error && typeof e.error === 'object' ? Object.values(e.error).flat().join(' ') : '';
        this.erreur = detail || "L'enregistrement a échoué.";
      },
    });
  }

  retirer(ligne: Ligne): void {
    if (!confirm(`Retirer « ${this.paragraphe.titreLigne(ligne)} » du plan ?`)) return;
    this.http.delete(`${this.url}${ligne.id}/`).subscribe({
      next: () => this.charger(), error: () => { this.erreur = 'Le retrait a échoué.'; },
    });
  }
}
