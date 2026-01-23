import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard/dashboard.component';

export const ADMIN_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'signalements', component: DashboardComponent }, 
  { path: 'equipes', component: DashboardComponent }, 
  { path: 'carte', component: DashboardComponent },
  { path: 'resultats', component: DashboardComponent } 
];