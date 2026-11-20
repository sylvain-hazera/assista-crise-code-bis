import { Routes } from '@angular/router';
import { PublicLayoutComponent } from './layouts/public-layout/public-layout.component';
import { AdminLayoutComponent } from './layouts/admin-layout/admin-layout.component';
import { adminGuard } from './core/guards/admin.guard';
import { enableGuard } from './core/guards/enable.guard';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
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
    path: 'admin',
    component: AdminLayoutComponent,
    loadChildren: () => import('./admin/admin.routes').then(m => m.ADMIN_ROUTES),
     canActivate: [adminGuard, enableGuard]
  },
  { path: '**', redirectTo: '' }
];