import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HttpClient } from '@angular/common/http';

import { environment } from '../../../environments/environment';

interface Invitation {
  institution: string;
  type: string;
  invite_par: string;
  convention_requise: boolean;
}

/**
 * « Rejoindre votre collectivité » (21/11/2026) : le lien envoyé par l'association qui exploite
 * la plateforme pour le département. La collectivité existe déjà (créée par l'amorçage) : on y
 * ouvre son compte, on reçoit son lien d'activation, puis on arrive sur « Mon plan de
 * sauvegarde » pour compléter ce qui manque.
 */
@Component({
  selector: 'app-rejoindre-collectivite',
  standalone: true,
  imports: [FormsModule, RouterLink],
  template: `
    <main class="rejoindre">
      <section class="carte">
        @if (etat === 'chargement') { <p>Chargement…</p> }
        @if (etat === 'invalide') {
          <h1>Lien expiré ou invalide</h1>
          <p>Demandez un nouveau lien à l'association qui vous l'a envoyé.</p>
          <a routerLink="/accueil">Retour à l'accueil</a>
        }
        @if (etat === 'formulaire' && invitation) {
          <h1>Rejoindre {{ invitation.institution }}</h1>
          <p class="aide">{{ invitation.invite_par }} exploite la plateforme de gestion de crise pour votre territoire.
            Votre espace est prêt : ouvrez votre compte, puis complétez ce qui permet de préparer la gestion de crise
            (organisation, annuaire, lieux, moyens d'alerte).</p>
          <div class="grille">
            <label>Prénom * <input type="text" [(ngModel)]="saisie.prenom" autocomplete="given-name"></label>
            <label>Nom * <input type="text" [(ngModel)]="saisie.nom" autocomplete="family-name"></label>
            <label>Courriel professionnel * <input type="email" [(ngModel)]="saisie.email" autocomplete="email" placeholder="prenom.nom@commune.fr"></label>
            <label>Téléphone <input type="tel" [(ngModel)]="saisie.telephone" autocomplete="tel" placeholder="06 12 34 56 78"></label>
            <label class="large">Fonction <input type="text" [(ngModel)]="saisie.fonction" placeholder="Maire, adjoint, secrétaire de mairie, DGS…"></label>
          </div>
          @if (invitation.convention_requise) {
            <label class="case">
              <input type="checkbox" [(ngModel)]="saisie.convention">
              J'accepte, pour ma collectivité, la <a routerLink="/convention-sous-traitance" target="_blank">convention de sous-traitance</a> (RGPD, art. 28).
            </label>
          }
          @if (erreur) { <p class="erreur" role="alert">{{ erreur }}</p> }
          <button type="button" class="btn-primary" [disabled]="!peutEnvoyer" (click)="envoyer()">
            {{ envoi ? 'Création…' : 'Créer mon compte' }}
          </button>
        }
        @if (etat === 'envoye') {
          <h1>Consultez votre messagerie</h1>
          <p>Un lien d'activation vient d'être envoyé à {{ saisie.email }}. Il vous ouvre votre espace, sur
            « Mon plan de sauvegarde » : l'encadré « Ce qui reste à compléter » vous guide.</p>
        }
      </section>
    </main>
  `,
  styles: [`
    .rejoindre { display: flex; justify-content: center; padding: 3rem 1rem; }
    .carte { max-width: 38rem; width: 100%; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      border-radius: 12px; padding: 2rem; display: flex; flex-direction: column; gap: .9rem; }
    h1 { margin: 0; font-size: 1.4rem; }
    .aide { color: var(--ac-text-muted, #5b6275); line-height: 1.5; margin: 0; }
    .grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: .7rem; }
    .grille .large { grid-column: 1 / -1; }
    label { display: flex; flex-direction: column; gap: .25rem; font-size: .9rem; }
    .case { flex-direction: row; align-items: flex-start; gap: .5rem; }
    input[type=text], input[type=email], input[type=tel] { padding: .5rem .6rem; border: 1px solid var(--ac-border, #cbd5e1); border-radius: 6px; font: inherit; }
    .erreur { color: #b91c1c; margin: 0; }
  `],
})
export class RejoindreCollectiviteComponent implements OnInit {
  etat: 'chargement' | 'invalide' | 'formulaire' | 'envoye' = 'chargement';
  invitation: Invitation | null = null;
  saisie = { prenom: '', nom: '', email: '', telephone: '', fonction: '', convention: false };
  envoi = false;
  erreur = '';
  private jeton = '';

  constructor(private route: ActivatedRoute, private http: HttpClient) {}

  private get url(): string {
    return `${environment.apiUrl}/rejoindre-collectivite/${encodeURIComponent(this.jeton)}/`;
  }

  ngOnInit(): void {
    this.jeton = this.route.snapshot.paramMap.get('jeton') ?? '';
    this.http.get<Invitation>(this.url).subscribe({
      next: inv => { this.invitation = inv; this.etat = 'formulaire'; },
      error: () => this.etat = 'invalide',
    });
  }

  get peutEnvoyer(): boolean {
    const s = this.saisie;
    return !!s.prenom.trim() && !!s.nom.trim() && s.email.includes('@') && !this.envoi
      && (!this.invitation?.convention_requise || s.convention);
  }

  envoyer(): void {
    this.envoi = true;
    this.erreur = '';
    const s = this.saisie;
    this.http.post(this.url, {
      prenom: s.prenom.trim(), nom: s.nom.trim(), email: s.email.trim(), telephone: s.telephone.trim(),
      fonction: s.fonction.trim(), convention_acceptee: s.convention,
    }).subscribe({
      next: () => { this.envoi = false; this.etat = 'envoye'; },
      error: e => { this.envoi = false; this.erreur = e?.error?.error ?? 'Création impossible. Réessayez.'; },
    });
  }
}
