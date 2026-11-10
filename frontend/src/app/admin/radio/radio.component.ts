import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { AccesRadioService } from '../../services/acces-radio.service';
import { AuthService } from '../../auth/services/auth.service';
import { DemandeAccesRadio, EtatAccesRadio, StatutDemandeAccesRadio } from '../../shared/models/acces-radio.model';
import { NiveauAccesRadio, UserRole } from '../../shared/models/user.model';

/** Porte d'entrée du domaine radio — et, pour qui n'y a pas droit, la seule page qu'il voit.
 *
 * Trois publics sur un même écran, et c'est voulu :
 *
 * 1. **Un compte sans accès** : il apprend ici ce qu'il lui faut (un nœud personnel rattaché à
 *    son compte, ou une passerelle rattachée à son institution), et il peut demander le droit.
 *    `radioGuard` renvoie vers cette page plutôt que vers « accès refusé » : « refusé » est
 *    exact et inutile, la personne a besoin de savoir ce qui lui manque.
 * 2. **Un opérateur ou un administrateur** : il voit à quel titre il a l'accès — donc ce qu'il
 *    perdrait en désactivant son nœud — et le sommaire des écrans radio.
 * 3. **Un administrateur de la plateforme** : il instruit les demandes en attente.
 *
 * Le niveau n'est jamais calculé ici. Il dépend du matériel enregistré et des droits accordés,
 * dont le navigateur ne sait rien (backend/core/acces_radio.py). */
@Component({
  selector: 'app-radio',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './radio.component.html',
  styleUrl: './radio.component.scss',
})
export class RadioComponent implements OnInit {

  etat: EtatAccesRadio | null = null;
  chargement = true;
  erreur: string | null = null;

  /** Formulaire de demande. OPERATEUR par défaut : c'est le besoin courant, et demander
   * l'administration complète d'emblée se fait refuser plus souvent qu'accorder. */
  niveauDemande: NiveauAccesRadio = 'OPERATEUR';
  motif = '';
  envoi = false;
  erreurEnvoi: string | null = null;

  /** Instruction (administrateur de la plateforme seulement). */
  demandes: DemandeAccesRadio[] = [];
  commentaires: Record<string, string> = {};
  niveauxAccordes: Record<string, NiveauAccesRadio> = {};
  instructionEnCours: string | null = null;

  constructor(private service: AccesRadioService, private auth: AuthService) {}

  ngOnInit(): void {
    this.charger();
  }

  get estAdministrateur(): boolean {
    // Rôle RÉEL et non effectif : accorder la main sur du matériel qui émet n'est pas un geste
    // de démonstration. Le serveur applique la même règle, c'est lui qui fait foi.
    return this.auth.getCurrentUser()?.type === UserRole.ADMIN;
  }

  get aAcces(): boolean {
    return !!this.etat && this.etat.niveau !== 'AUCUN';
  }

  get peutAdministrerLInfrastructure(): boolean {
    return this.etat?.niveau === 'ADMINISTRATEUR';
  }

  get demandeEnAttente(): boolean {
    return this.etat?.demande?.statut === 'EN_ATTENTE';
  }

  charger(): void {
    this.chargement = true;
    this.erreur = null;
    this.service.monAcces().subscribe({
      next: (etat) => {
        this.etat = etat;
        this.chargement = false;
        // Qui est déjà opérateur ne demande pas à l'être : le seul niveau qu'il lui reste à
        // demander est l'administration complète.
        if (etat.niveau === 'OPERATEUR') this.niveauDemande = 'ADMINISTRATEUR';
        if (this.estAdministrateur) this.chargerDemandes();
      },
      error: () => {
        this.erreur = "Impossible de lire votre niveau d'accès radio.";
        this.chargement = false;
      },
    });
  }

  private chargerDemandes(): void {
    this.service.lister('EN_ATTENTE').subscribe({
      next: (demandes) => {
        this.demandes = demandes;
        for (const demande of demandes) {
          // Le niveau proposé par défaut est celui demandé : l'instructeur l'abaisse s'il le
          // juge, il ne doit pas avoir à le ressaisir dans le cas courant.
          this.niveauxAccordes[demande.id] = demande.niveau_demande;
        }
      },
      // Pas de message : un échec ici ne doit pas masquer la page à l'administrateur, qui vient
      // peut-être simplement voir son propre niveau.
      error: () => { this.demandes = []; },
    });
  }

  envoyerDemande(): void {
    if (!this.motif.trim() || this.envoi) return;
    this.envoi = true;
    this.erreurEnvoi = null;
    this.service.demander(this.niveauDemande, this.motif.trim()).subscribe({
      next: () => {
        this.motif = '';
        this.envoi = false;
        // On recharge l'état complet plutôt que d'insérer la demande localement : le serveur
        // seul sait si le droit vient de s'ouvrir par un autre titre entre-temps.
        this.charger();
      },
      error: (e: HttpErrorResponse) => {
        this.erreurEnvoi = this.messageErreur(e);
        this.envoi = false;
      },
    });
  }

  instruire(demande: DemandeAccesRadio, decision: StatutDemandeAccesRadio): void {
    if (this.instructionEnCours) return;
    this.instructionEnCours = demande.id;
    const niveau = decision === 'ACCORDEE' ? (this.niveauxAccordes[demande.id] ?? 'OPERATEUR') : null;
    this.service.instruire(demande.id, decision, niveau, this.commentaires[demande.id] ?? '').subscribe({
      next: () => {
        this.instructionEnCours = null;
        this.charger();
      },
      error: (e: HttpErrorResponse) => {
        this.erreur = this.messageErreur(e);
        this.instructionEnCours = null;
      },
    });
  }

  /** Message du serveur quand il y en a un : il dit la vraie raison (demande déjà en attente,
   * motif vide, niveau refusé), qu'un texte générique effacerait. */
  private messageErreur(e: HttpErrorResponse): string {
    const corps = e.error;
    if (typeof corps === 'string') return corps;
    if (corps && typeof corps === 'object') {
      const premier = Object.values(corps)[0];
      if (Array.isArray(premier) && premier.length) return String(premier[0]);
      if (typeof premier === 'string') return premier;
    }
    return "L'envoi a échoué.";
  }
}
