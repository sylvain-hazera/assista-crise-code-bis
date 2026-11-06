import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { CompteMqttService } from '../../services/compte-mqtt.service';
import { CompteMqtt, RoleCompteMqtt } from '../../shared/models/compte-mqtt.model';

/** Comptes du broker MQTT local : un compte par passerelle radio du site.
 *
 * Le mot de passe n'est jamais affiché spontanément — il s'obtient par un clic explicite, et
 * chaque consultation laisse une trace au journal d'audit côté serveur. Un administrateur doit
 * pouvoir le relire des mois plus tard pour configurer un boîtier sur un toit, mais il n'a pas à
 * traîner à l'écran.
 *
 * Réservé aux administrateurs (rôle PROD réel) : un compte MQTT donne accès au trafic radio de
 * l'institution. Le garde de route masque la page, le serveur refuse de toute façon. */
@Component({
  selector: 'app-comptes-mqtt',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './comptes-mqtt.component.html',
  styleUrl: './comptes-mqtt.component.scss',
})
export class ComptesMqttComponent implements OnInit {

  comptes: CompteMqtt[] = [];
  chargement = true;
  erreur: string | null = null;

  /** Formulaire de création. `racine_topic` doit correspondre au `topic_racine` du companion. */
  nouveau: { nom: string; role: RoleCompteMqtt; racine_topic: string; description: string } = {
    nom: '', role: 'RADIO', racine_topic: 'msh/EU_868', description: '',
  };
  creationEnCours = false;
  erreurCreation: string | null = null;

  /** Mots de passe révélés, par identifiant de compte : rien n'est gardé au-delà de la page. */
  motsDePasseAffiches: Record<string, string> = {};
  /** Compte dont on attend une confirmation de régénération. */
  regenerationDemandee: string | null = null;

  constructor(private service: CompteMqttService) {}

  ngOnInit(): void {
    this.charger();
  }

  charger(): void {
    this.chargement = true;
    this.service.getAll().subscribe({
      next: (comptes) => { this.comptes = comptes; this.erreur = null; this.chargement = false; },
      error: (e: HttpErrorResponse) => {
        this.erreur = e.status === 403
          ? 'La gestion des comptes MQTT est réservée aux administrateurs.'
          : 'Impossible de charger les comptes du broker.';
        this.chargement = false;
      },
    });
  }

  creer(): void {
    const nom = this.nouveau.nom.trim();
    if (!nom) { return; }
    this.creationEnCours = true;
    this.erreurCreation = null;
    this.service.create({
      nom,
      role: this.nouveau.role,
      racine_topic: this.nouveau.racine_topic.trim(),
      description: this.nouveau.description.trim(),
    }).subscribe({
      next: (compte) => {
        this.creationEnCours = false;
        this.nouveau = { nom: '', role: 'RADIO', racine_topic: 'msh/EU_868', description: '' };
        // Le mot de passe est engendré par le serveur : on l'affiche tout de suite, c'est le
        // seul moment où l'administrateur l'attend à l'écran pour configurer son boîtier.
        this.afficherMotDePasse(compte.id);
        this.charger();
      },
      error: (e: HttpErrorResponse) => {
        this.creationEnCours = false;
        this.erreurCreation = this.messageDErreur(e) ?? 'Création impossible.';
      },
    });
  }

  afficherMotDePasse(id: string): void {
    this.service.motDePasse(id).subscribe({
      next: ({ mot_de_passe }) => { this.motsDePasseAffiches[id] = mot_de_passe; },
      error: () => { this.erreur = 'Impossible d’afficher le mot de passe.'; },
    });
  }

  masquerMotDePasse(id: string): void {
    delete this.motsDePasseAffiches[id];
  }

  confirmerRegeneration(id: string): void {
    this.regenerationDemandee = id;
  }

  annulerRegeneration(): void {
    this.regenerationDemandee = null;
  }

  regenerer(id: string): void {
    this.service.regenerer(id).subscribe({
      next: ({ mot_de_passe }) => {
        this.motsDePasseAffiches[id] = mot_de_passe;
        this.regenerationDemandee = null;
        this.charger();
      },
      error: () => {
        this.regenerationDemandee = null;
        this.erreur = 'Régénération impossible.';
      },
    });
  }

  basculerActif(compte: CompteMqtt): void {
    this.service.update(compte.id, { actif: !compte.actif }).subscribe({
      next: () => this.charger(),
      error: () => { this.erreur = 'Modification impossible.'; },
    });
  }

  supprimer(compte: CompteMqtt): void {
    this.service.delete(compte.id).subscribe({
      next: () => this.charger(),
      error: (e: HttpErrorResponse) => {
        this.erreur = this.messageDErreur(e) ?? 'Suppression impossible.';
      },
    });
  }

  /** Premier message d'erreur exploitable d'une réponse DRF, quelle que soit sa forme
   * (`{detail}`, `{champ: [messages]}`, ou une liste à la racine). */
  private messageDErreur(e: HttpErrorResponse): string | null {
    const corps = e.error;
    if (typeof corps === 'string') { return corps; }
    if (Array.isArray(corps)) { return String(corps[0]); }
    if (corps && typeof corps === 'object') {
      if (corps['detail']) { return String(corps['detail']); }
      const premier = Object.values(corps)[0];
      if (Array.isArray(premier)) { return String(premier[0]); }
      if (premier) { return String(premier); }
    }
    return null;
  }
}
