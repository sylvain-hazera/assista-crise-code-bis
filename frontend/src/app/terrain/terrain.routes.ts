import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { AuthService } from '../auth/services/auth.service';
import { evalueLesDegats } from './droits';

const degatsGuard = () => evalueLesDegats(inject(AuthService)) || inject(Router).parseUrl('/terrain/missions');

/** L'espace terrain (DOSSIER-PWA-INTERVENANTS.md, lots 2 et 5). Les équipes et la carte
 * reprennent les pages du site ; missions, alertes, dossiers, QR codes, dégâts et compte sont
 * écrits pour le téléphone. */
export const TERRAIN_ROUTES: Routes = [
  { path: '', redirectTo: 'missions', pathMatch: 'full' },
  { path: 'missions', loadComponent: () => import('./missions/terrain-missions.component').then(m => m.TerrainMissionsComponent) },
  { path: 'equipes', loadComponent: () => import('../pages/mes-equipes/mes-equipes.component').then(m => m.MesEquipesComponent) },
  { path: 'equipe/:id', loadComponent: () => import('../pages/mon-equipe/mon-equipe.component').then(m => m.MonEquipeComponent) },
  { path: 'carte', loadComponent: () => import('../public/global-map/global-map.component').then(m => m.GlobalMapComponent) },
  { path: 'alertes', loadComponent: () => import('./alertes/terrain-alertes.component').then(m => m.TerrainAlertesComponent) },
  { path: 'dossiers', loadComponent: () => import('./dossiers/terrain-dossiers.component').then(m => m.TerrainDossiersComponent) },
  { path: 'qr', loadComponent: () => import('./qr/terrain-qr.component').then(m => m.TerrainQrComponent) },
  { path: 'degats', canActivate: [degatsGuard], loadComponent: () => import('./degats/terrain-degats.component').then(m => m.TerrainDegatsComponent) },
  { path: 'moi', loadComponent: () => import('./moi/terrain-moi.component').then(m => m.TerrainMoiComponent) },
];
