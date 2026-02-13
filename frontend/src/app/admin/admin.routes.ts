import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard/dashboard.component';
import { ReportingComponent } from './reporting/reporting.component';
import { TeamsComponent } from './teams/teams.component';
import { MapComponent } from '../shared/components/common/map/map.component';
import { ResultsComponent } from './results/results.component';
import { UsersComponent } from './users/users.component';

export const ADMIN_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'signalements', component: ReportingComponent }, 
  { path: 'equipes', component: TeamsComponent }, 
  { path: 'carte', component: MapComponent },
  { path: 'resultats', component: ResultsComponent },
  { path: 'users', component: UsersComponent } 
];