import { Routes } from '@angular/router';

/** Le poste de pilotage (directeur des opérations sur iPad). La situation et les alertes sont
 * écrites pour lui ; la cellule de crise, la carte, les dossiers et le point de situation
 * reprennent les pages de l'administration, sans son menu. */
export const PILOTAGE_ROUTES: Routes = [
  { path: '', redirectTo: 'situation', pathMatch: 'full' },
  { path: 'situation', loadComponent: () => import('./situation/pilotage-situation.component').then(m => m.PilotageSituationComponent) },
  { path: 'cellule', loadComponent: () => import('../admin/cellule-crise/cellule-crise.component').then(m => m.CelluleCriseComponent) },
  { path: 'carte', loadComponent: () => import('../shared/components/common/map/map.component').then(m => m.MapComponent) },
  { path: 'dossiers', loadComponent: () => import('../admin/dossiers/dossiers.component').then(m => m.DossiersComponent) },
  { path: 'point', loadComponent: () => import('../admin/standard-crise/standard-crise.component').then(m => m.StandardCriseComponent),
    data: { onglet: 'situation' } },
  { path: 'terrain', loadComponent: () => import('./terrain/pilotage-terrain.component').then(m => m.PilotageTerrainComponent) },
  { path: 'alertes', loadComponent: () => import('./alertes/pilotage-alertes.component').then(m => m.PilotageAlertesComponent) },
];
