import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { RelaisSerieService, CompagnonRelayable } from '../../services/relais-serie.service';
import { RelaisLocalService } from '../../services/relais-local.service';
import {
  ConnecterRadioComponent,
} from '../../shared/components/common/connecter-radio/connecter-radio.component';
import {
  RelaisLocauxComponent,
} from '../../shared/components/common/relais-locaux/relais-locaux.component';

/**
 * « Devenir passerelle » : la porte d'entrée de qui n'a pas accès à l'administration.
 *
 * Même moteur (`RelaisLocalService`) et mêmes composants que les pages des companions MeshCore
 * et Meshtastic : un bénévole n'est pas administrateur, il ne peut pas ouvrir `/admin/…`, et
 * c'est pourtant lui qui a une radio dans la poche.
 *
 * **Ce n'est pas un satellite** : si internet tombe, cette page ne joint plus l'API non plus.
 */
@Component({
  selector: 'app-devenir-passerelle',
  standalone: true,
  imports: [CommonModule, RouterLink, ConnecterRadioComponent, RelaisLocauxComponent],
  templateUrl: './devenir-passerelle.component.html',
  styleUrl: './devenir-passerelle.component.scss',
})
export class DevenirPasserelleComponent implements OnInit, OnDestroy {
  erreur = '';
  chargement = true;
  radios: CompagnonRelayable[] = [];
  actifs = new Set<string>();

  /** Au moins un transport possible dans ce navigateur. */
  readonly supporte: boolean;

  private abonnement: Subscription | null = null;

  constructor(private service: RelaisSerieService, private moteur: RelaisLocalService) {
    this.supporte = this.moteur.supporte;
  }

  ngOnInit(): void {
    this.charger();
    this.abonnement = this.moteur.liste().subscribe(
      liste => this.actifs = new Set(liste.map(r => r.compagnonId)));
  }

  ngOnDestroy(): void {
    // On se désabonne, on n'arrête PAS les relais : ils vivent dans le service.
    this.abonnement?.unsubscribe();
  }

  charger(): void {
    this.service.etat().subscribe({
      next: etat => { this.radios = etat.compagnons; this.chargement = false; },
      error: () => {
        this.erreur = 'Impossible de charger les radios que vous pouvez relayer.';
        this.chargement = false;
      },
    });
  }

  libelle(c: CompagnonRelayable): string {
    const protocole = c.protocole === 'MESHTASTIC' ? 'Meshtastic' : 'MeshCore';
    const proprietaire = c.genre === 'noeud' ? 'ma radio' : c.institution_nom;
    return [c.nom, protocole, proprietaire].filter(Boolean).join(' — ');
  }

  radioDe(c: CompagnonRelayable): { genre: 'compagnon' | 'noeud'; id: string; nom: string } {
    return { genre: c.genre, id: c.id, nom: c.nom };
  }

  debrancher(c: CompagnonRelayable): void {
    void this.moteur.debrancher(c.id);
  }
}
