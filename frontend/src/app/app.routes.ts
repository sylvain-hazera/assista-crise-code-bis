import { Routes } from '@angular/router';
import { PublicLayoutComponent } from './layouts/public-layout/public-layout.component';
import { AdminLayoutComponent } from './layouts/admin-layout/admin-layout.component';
import { adminGuard } from './core/guards/admin.guard';
import { enableGuard } from './core/guards/enable.guard';
import { authGuard } from './core/guards/auth.guard';
import { pilotageGuard } from './pilotage/pilotage.guard';

export const routes: Routes = [
  // Ce qu'on partage sans connexion, « pour les copains » (28/11/2026) : hors de la mise en
  // page publique, qui porte la connexion.
  { path: 'ouvert', loadChildren: () => import('./ouvert/ouvert.routes').then(m => m.OUVERT_ROUTES) },
  {
    path: '',
    component: PublicLayoutComponent,
    loadChildren: () => import('./public/public.routes').then(m => m.PUBLIC_ROUTES)
  },
  {
    // L'application « Terrain » des intervenants, installable sur iPhone (DOSSIER-PWA-INTERVENANTS.md).
    path: 'terrain',
    canActivate: [authGuard],
    loadComponent: () => import('./terrain/terrain-layout.component').then(m => m.TerrainLayoutComponent),
    loadChildren: () => import('./terrain/terrain.routes').then(m => m.TERRAIN_ROUTES),
  },
  {
    // L'application « Pilotage » du directeur des opérations, installable sur iPad
    // (DOSSIER-PWA-INTERVENANTS.md, § 6) : un espace à part, pas l'administration.
    path: 'pilotage',
    canActivate: [authGuard, pilotageGuard],
    loadComponent: () => import('./pilotage/pilotage-layout.component').then(m => m.PilotageLayoutComponent),
    loadChildren: () => import('./pilotage/pilotage.routes').then(m => m.PILOTAGE_ROUTES),
  },
  {
    path: 'admin',
    component: AdminLayoutComponent,
    loadChildren: () => import('./admin/admin.routes').then(m => m.ADMIN_ROUTES),
     canActivate: [adminGuard, enableGuard]
  },
  { path: '**', redirectTo: '' }
];