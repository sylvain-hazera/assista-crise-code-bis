import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { RelaisSerieService, CompagnonRelayable } from '../../services/relais-serie.service';
import { RelaisLocalService } from '../../services/relais-local.service';
import {
  RelaisLocauxComponent,
} from '../../shared/components/common/relais-locaux/relais-locaux.component';

/**
 * « Devenir passerelle » : la porte d'entrée pour qui n'a pas accès à l'administration.
 *
 * **Le moteur n'est plus ici.** Il vit dans `RelaisLocalService`, partagé avec la page des
 * companions MeshCore — demande du 14/11/2026 : brancher plusieurs radios depuis l'écran qui
 * les liste déjà, sans changer d'onglet. Cette page ne fait donc plus que deux choses : lister
 * les radios que cette personne peut relayer, et en brancher une d'un clic.
 *
 * Elle reste utile parce qu'un bénévole n'est pas administrateur : il ne peut pas ouvrir
 * `/admin/meshcore-companions`, et c'est pourtant lui qui a une radio dans la poche. Même
 * composant de liste, même moteur, deux portes.
 *
 * **Ce n'est pas un satellite** : si internet tombe, cette page ne joint plus l'API non plus.
 * Le profil `gw` du satellite reste la bonne réponse partout où l'on peut installer quelque
 * chose.
 */
@Component({
  selector: 'app-devenir-passerelle',
  standalone: true,
  imports: [CommonModule, RouterLink, RelaisLocauxComponent],
  templateUrl: './devenir-passerelle.component.html',
  styleUrl: './devenir-passerelle.component.scss',
})
export class DevenirPasserelleComponent implements OnInit, OnDestroy {
  erreur = '';
  avertissement = '';
  chargement = true;

  radios: CompagnonRelayable[] = [];
  enCours = '';
  actifs = new Set<string>();

  /** Web Serial n'existe ni sur Firefox, ni sur Safari, ni sur iOS. Le dire avant que la
   * personne ne cherche pourquoi le bouton ne fait rien. */
  readonly supporte: boolean;

  private abonnement: Subscription | null = null;

  constructor(private service: RelaisSerieService, private moteur: RelaisLocalService) {
    this.supporte = this.moteur.supporte;
  }

  ngOnInit(): void {
    this.service.etat().subscribe({
      next: (etat) => {
        this.radios = etat.compagnons;
        this.chargement = false;
      },
      error: () => {
        this.erreur = 'Impossible de charger les radios que vous pouvez relayer.';
        this.chargement = false;
      },
    });
    this.abonnement = this.moteur.liste().subscribe(
      liste => this.actifs = new Set(liste.map(r => r.compagnonId)));
  }

  ngOnDestroy(): void {
    // On se désabonne, on n'arrête PAS les relais : ils vivent dans le service, et quitter
    // cette page ne doit pas couper une radio branchée.
    this.abonnement?.unsubscribe();
  }

  libelle(c: CompagnonRelayable): string {
    if (c.genre === 'noeud') { return `${c.nom} — ma radio`; }
    return c.institution_nom ? `${c.nom} — ${c.institution_nom}` : c.nom;
  }

  /** Une radio personnelle n'a pas encore d'identifiant de companion : elle est promue au
   * branchement. On suit donc l'état par l'identifiant rendu par le serveur, pas par celui du
   * nœud — d'où ce rapprochement par nom pour les lignes déjà branchées. */
  estBranchee(c: CompagnonRelayable): boolean {
    return this.actifs.has(c.id);
  }

  async brancher(c: CompagnonRelayable): Promise<void> {
    this.erreur = '';
    this.avertissement = '';
    this.enCours = c.id;
    try {
      const compagnonId = await this.moteur.brancher(
        { genre: c.genre, id: c.id, nom: c.nom });
      // Un nœud personnel vient d'être promu : on recharge pour qu'il apparaisse désormais
      // comme passerelle, et non plus comme « ma radio » à déclarer.
      if (c.genre === 'noeud' && compagnonId !== c.id) {
        this.service.etat().subscribe({ next: (etat) => this.radios = etat.compagnons });
      }
      this.avertissement = this.moteur.dernierAvertissement;
    } catch (e) {
      this.erreur = this.moteur.lisible(e);
    } finally {
      this.enCours = '';
    }
  }

  debrancher(c: CompagnonRelayable): void {
    void this.moteur.debrancher(c.id);
  }
}
