import { Routes } from '@angular/router';

/** L'espace terrain (DOSSIER-PWA-INTERVENANTS.md, lot 2). Les équipes et la carte reprennent
 * les pages du site ; missions, alertes et compte sont écrits pour le téléphone. */
export const TERRAIN_ROUTES: Routes = [
  { path: '', redirectTo: 'missions', pathMatch: 'full' },
  { path: 'missions', loadComponent: () => import('./missions/terrain-missions.component').then(m => m.TerrainMissionsComponent) },
  { path: 'equipes', loadComponent: () => import('../pages/mes-equipes/mes-equipes.component').then(m => m.MesEquipesComponent) },
  { path: 'equipe/:id', loadComponent: () => import('../pages/mon-equipe/mon-equipe.component').then(m => m.MonEquipeComponent) },
  { path: 'carte', loadComponent: () => import('../public/global-map/global-map.component').then(m => m.GlobalMapComponent) },
  { path: 'alertes', loadComponent: () => import('./alertes/terrain-alertes.component').then(m => m.TerrainAlertesComponent) },
  { path: 'moi', loadComponent: () => import('./moi/terrain-moi.component').then(m => m.TerrainMoiComponent) },
];
