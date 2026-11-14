import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';

import { RelaisLocalService, RelaisVisible } from '../../../../services/relais-local.service';

/**
 * « Les radios que CE poste relaie » — la liste, les compteurs, et le bouton pour débrancher.
 *
 * Volontairement sans bouton « connecter » : ce composant ne sait pas quelles radios existent,
 * c'est l'écran qui l'accueille qui le sait (la page des companions en a la liste complète, la
 * page publique celle de ses propres nœuds). Il n'affiche que l'état du matériel branché ici,
 * et il est le même partout — une seule implémentation pour trois points d'entrée.
 *
 * Il ne s'affiche pas du tout quand rien n'est branché : un bloc vide sur une page
 * d'administration déjà dense n'apporte rien.
 */
@Component({
  selector: 'app-relais-locaux',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './relais-locaux.component.html',
  styleUrl: './relais-locaux.component.scss',
})
export class RelaisLocauxComponent implements OnInit, OnDestroy {
  relais: RelaisVisible[] = [];

  private abonnement: Subscription | null = null;

  constructor(private moteur: RelaisLocalService) {}

  ngOnInit(): void {
    this.abonnement = this.moteur.liste().subscribe(r => this.relais = r);
  }

  ngOnDestroy(): void {
    // On se désabonne, on n'arrête PAS les relais : ils vivent dans un service, pas dans cette
    // vue — c'est tout l'intérêt, le relais continue quand on change de page.
    this.abonnement?.unsubscribe();
  }

  debrancher(r: RelaisVisible): void {
    void this.moteur.debrancher(r.compagnonId);
  }
}
