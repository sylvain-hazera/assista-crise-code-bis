import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { RelaisLocalService } from '../../../../services/relais-local.service';
import { Protocole } from '../../../mesh/pilotes';
import { NomTransport } from '../../../mesh/transports';

/**
 * « Connecter une radio » : choisir le protocole et la liaison, cliquer, c'est relayé.
 *
 * Demande du 14/11/2026 : « un simple bouton connecter, et hop, ça me rajoute au réseau comme
 * passerelle de l'institution ». Sans `radio`, ce composant ne désigne rien : la radio dit
 * elle-même qui elle est, et le serveur la retrouve ou la déclare. Avec `radio`, il branche
 * CETTE ligne — et le serveur vérifie que la radio branchée est bien celle-là.
 *
 * Les transports impossibles sont **désactivés avec leur raison**, jamais cachés : on doit
 * comprendre pourquoi le Wi-Fi n'est pas proposé pour MeshCore, pas le chercher.
 */
@Component({
  selector: 'app-connecter-radio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './connecter-radio.component.html',
  styleUrl: './connecter-radio.component.scss',
})
export class ConnecterRadioComponent implements OnInit {
  /** Protocoles proposés. Un seul : pas de choix affiché. */
  @Input() protocoles: Protocole[] = ['MESHCORE', 'MESHTASTIC'];
  /** Une ligne précise à brancher ; absent = identification par la radio. */
  @Input() radio: { genre: 'compagnon' | 'noeud'; id: string; nom: string } | null = null;
  /** Adresse réseau pré-remplie (companion Meshtastic déclaré en TCP). */
  @Input() adresseParDefaut = '';
  /** Présentation en ligne de tableau : boutons seuls, sans titre ni aide. */
  @Input() compact = false;

  @Output() branche = new EventEmitter<string>();

  protocole: Protocole = 'MESHCORE';
  adresse = '';
  enCours: NomTransport | '' = '';
  erreur = '';
  avertissement = '';
  saisieAdresse = false;

  readonly transports: { nom: NomTransport; libelle: string; icone: string }[] = [
    { nom: 'USB', libelle: 'USB', icone: 'usb' },
    { nom: 'BLE', libelle: 'Bluetooth', icone: 'bluetooth' },
    { nom: 'WIFI', libelle: 'Réseau local', icone: 'wifi' },
  ];

  constructor(readonly moteur: RelaisLocalService) {}

  ngOnInit(): void {
    this.protocole = this.protocoles[0];
    this.adresse = this.adresseParDefaut;
  }

  raison(t: NomTransport): string {
    return this.moteur.raisonIndisponible(this.protocole, t);
  }

  libelleProtocole(p: Protocole): string {
    return p === 'MESHTASTIC' ? 'Meshtastic' : 'MeshCore';
  }

  async connecter(t: NomTransport): Promise<void> {
    this.erreur = '';
    this.avertissement = '';
    if (t === 'WIFI' && !this.adresse.trim()) {
      // Pas de geste à préserver pour le réseau local : on peut demander l'adresse d'abord.
      this.saisieAdresse = true;
      return;
    }
    this.enCours = t;
    try {
      const id = await this.moteur.brancher({
        protocole: this.protocole, transport: t, adresse: this.adresse,
        radio: this.radio ? { genre: this.radio.genre, id: this.radio.id } : undefined,
      });
      this.avertissement = this.moteur.dernierAvertissement;
      this.saisieAdresse = false;
      this.branche.emit(id);
    } catch (e) {
      this.erreur = this.moteur.lisible(e);
    } finally {
      this.enCours = '';
    }
  }
}
