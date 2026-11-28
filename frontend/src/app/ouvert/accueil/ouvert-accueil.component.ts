import { Component, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';

import { CarteOuverteService, ResumeOuvert } from '../../services/carte-ouverte.service';

interface Entree {
  titre: string; icone: string; lien: string; vue?: string; description: string;
  etat: (r: ResumeOuvert) => string | null;
}

/**
 * `/ouvert` : ce qu'on partage sans connexion, « pour les copains » (28/11/2026). Une seule
 * adresse à donner, et des boutons vers chaque page, avec une ligne d'état lue en direct.
 * Rien sur les crises ni les manifestations : c'est la partie hors crise.
 */
@Component({
  selector: 'app-ouvert-accueil',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './ouvert-accueil.component.html',
  styleUrl: './ouvert-accueil.component.scss',
})
export class OuvertAccueilComponent implements OnInit {
  resume: ResumeOuvert | null = null;

  readonly entrees: Entree[] = [
    { titre: 'Carte', icone: 'map', lien: '/ouvert/carte',
      description: 'Pluie du radar, orages, éclairs, vent, crues, routes, feux, séismes, stations-service, répéteurs radio.',
      etat: r => r.cellules_orageuses ? `${r.cellules_orageuses} cellule${r.cellules_orageuses > 1 ? 's' : ''} orageuse${r.cellules_orageuses > 1 ? 's' : ''} en ce moment`
        : 'Aucune cellule orageuse en ce moment' },
    { titre: 'Propagation radio', icone: 'wifi_tethering', lien: '/ouvert/carte', vue: 'propagation',
      description: 'Ondes courtes d\'après la NOAA, conduits troposphériques en VHF, UHF et LoRa (nos estimations).',
      etat: r => r.kp === null ? null : `Kp ${r.kp.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}${r.g ? ` — orage géomagnétique ${r.g_libelle}` : ' — calme'}` },
    { titre: 'Est-ce que ça passe ?', icone: 'settings_input_antenna', lien: '/ouvert/carte', vue: 'liaison',
      description: 'Deux points sur la carte : le profil du terrain entre eux, et la marge radio en LoRa.',
      etat: r => r.couvertures ? `${r.couvertures} couverture${r.couvertures > 1 ? 's' : ''} de relais publiée${r.couvertures > 1 ? 's' : ''}` : null },
    { titre: 'Santé du réseau', icone: 'monitor_heart', lien: '/ouvert/reseau',
      description: 'Occupation du canal, trafic des dernières 24 heures, répéteurs entendus.',
      etat: r => r.occupation_canal === null ? null : `Canal Meshtastic occupé à ${r.occupation_canal.toLocaleString('fr-FR')} %` },
    { titre: 'Rejoindre le réseau', icone: 'diversity_3', lien: '/ouvert/rejoindre',
      description: 'Le matériel, les réglages de la bande 868 MHz, le canal public et les règles de courtoisie.',
      etat: r => r.repeteurs ? `${r.repeteurs} répéteurs et rooms connus` : null },
  ];

  constructor(private service: CarteOuverteService) {}

  ngOnInit(): void {
    // Les lignes d'état sont un plus : sans elles, les boutons restent.
    this.service.resume().subscribe({ next: r => this.resume = r, error: () => this.resume = null });
  }

  etat(e: Entree): string | null { return this.resume ? e.etat(this.resume) : null; }
}
