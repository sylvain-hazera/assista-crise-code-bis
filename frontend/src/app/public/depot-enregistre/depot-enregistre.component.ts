import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';

/** Ce qui vient d'être déposé : le texte, et l'onglet de « Mon espace » qui le suit. */
export type GenreDepot = 'demande' | 'offre' | 'signalement' | 'securite';

interface TexteDepot {
  titre: string;
  suite: string;
  onglet: string;
  libelleOnglet: string;
}

export const TEXTES_DEPOT: Record<GenreDepot, TexteDepot> = {
  demande: {
    titre: 'Votre demande est enregistrée',
    suite: "Elle est transmise à la mairie et aux équipes engagées sur la crise. Dès qu'une équipe la prend en charge, vous êtes prévenu par courriel, avec un lien pour suivre ce qui se passe.",
    onglet: 'request', libelleOnglet: "Suivre mes demandes d'aide",
  },
  offre: {
    titre: 'Votre proposition est enregistrée',
    suite: "Merci. Si une équipe vous retient, vous recevrez un courriel avec un lien pour confirmer votre venue. Vous n'avez rien d'autre à faire d'ici là.",
    onglet: 'offer', libelleOnglet: 'Voir ce que je propose',
  },
  signalement: {
    titre: 'Votre signalement est enregistré',
    suite: "Il est transmis à la mairie, qui le confie si besoin à une équipe. En cas de danger immédiat, appelez le 112.",
    onglet: 'information', libelleOnglet: "Voir ce que j'ai signalé",
  },
  securite: {
    titre: 'Votre déclaration est enregistrée',
    suite: 'La mairie et les secours savent que vous êtes en sécurité : ils ne vous chercheront pas.',
    onglet: 'declaration', libelleOnglet: 'Voir ma déclaration',
  },
};

/**
 * Confirmation après un dépôt public (21/11/2026). Elle remplace la fenêtre du navigateur
 * (`alert`), qui ne disait ni ce qui allait se passer, ni où suivre ce qu'on venait de déposer.
 */
@Component({
  selector: 'app-depot-enregistre',
  standalone: true,
  imports: [RouterLink],
  template: `
    <main class="depot">
      <section class="carte" role="status">
        <span class="material-icons coche" aria-hidden="true">check_circle</span>
        <h1>{{ texte.titre }}</h1>
        <p>{{ texte.suite }}</p>
        <p class="courriel">Un courriel de confirmation vient de partir, avec un lien pour modifier ou retirer ce que vous avez déposé.</p>
        <div class="actions">
          @if (connecte) {
            <a class="btn-primary" routerLink="/settings" [queryParams]="{ tab: texte.onglet }">{{ texte.libelleOnglet }}</a>
          }
          <a class="btn-secondaire" routerLink="/accueil">Retour à l'accueil</a>
        </div>
        @if (!connecte) {
          <p class="aide">Avec un compte, tout ce que vous déposez se retrouve dans « Mon espace ».</p>
        }
      </section>
    </main>
  `,
  styles: [`
    .depot { display: flex; justify-content: center; padding: 3rem 1rem; }
    .carte { max-width: 34rem; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      border-radius: 12px; padding: 2rem; text-align: center; display: flex; flex-direction: column; gap: .8rem; }
    .coche { font-size: 3rem; color: #16a34a; }
    h1 { margin: 0; font-size: 1.4rem; }
    p { margin: 0; line-height: 1.5; }
    .courriel, .aide { color: var(--ac-text-muted, #5b6275); font-size: .92rem; }
    .actions { display: flex; flex-wrap: wrap; gap: .6rem; justify-content: center; margin-top: .6rem; }
    .btn-primary, .btn-secondaire { padding: .6rem 1.1rem; border-radius: 8px; text-decoration: none; font-weight: 600; }
    .btn-primary { background: var(--ac-primary, #1d4ed8); color: #fff; }
    .btn-secondaire { border: 1px solid var(--ac-border, #cbd5e1); color: inherit; }
  `],
})
export class DepotEnregistreComponent implements OnInit {
  texte: TexteDepot = TEXTES_DEPOT.demande;
  connecte = false;

  constructor(private route: ActivatedRoute, private auth: AuthService) {}

  ngOnInit(): void {
    const genre = this.route.snapshot.queryParamMap.get('type') as GenreDepot | null;
    this.texte = (genre && TEXTES_DEPOT[genre]) || TEXTES_DEPOT.demande;
    this.connecte = !!this.auth.getCurrentUser();
  }
}
