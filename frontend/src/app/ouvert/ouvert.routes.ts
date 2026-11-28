import { Routes } from '@angular/router';

import { OuvertAccueilComponent } from './accueil/ouvert-accueil.component';
import { OuvertCarteComponent } from './carte/ouvert-carte.component';
import { OuvertReseauComponent } from './reseau/ouvert-reseau.component';
import { OuvertRejoindreComponent } from './rejoindre/ouvert-rejoindre.component';

/** Partie publique « pour les copains » (28/11/2026) : une seule adresse, `/ouvert`, et ses
 * pages. Aucune garde, aucun lien vers la connexion ni l'administration. */
export const OUVERT_ROUTES: Routes = [
  { path: '', component: OuvertAccueilComponent, title: 'Ce qu\'on partage' },
  { path: 'carte', component: OuvertCarteComponent, title: 'Carte ouverte' },
  { path: 'reseau', component: OuvertReseauComponent, title: 'Santé du réseau radio' },
  { path: 'rejoindre', component: OuvertRejoindreComponent, title: 'Rejoindre le réseau radio' },
];
