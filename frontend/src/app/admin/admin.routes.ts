import { InstitutionsComponent } from './institutions/institutions.component';
import { CrisesComponent } from './crises/crises.component';
import { CentresComponent } from './centres/centres.component';
import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard/dashboard.component';
import { ReportingComponent } from './reporting/reporting.component';
import { TeamsComponent } from './teams/teams.component';
import { MapComponent } from '../shared/components/common/map/map.component';
import { ResultsComponent } from './results/results.component';
import { UsersComponent } from './users/users.component';
import { sysAdminGuard } from '../core/guards/admin.guard';
import { CompetencesComponent } from './competences/competences.component';
import { AffectationsComponent } from './affectations/affectations.component';
import { DossiersComponent } from './dossiers/dossiers.component';
import { MissionsComponent } from './missions/missions.component';
import { BesoinsComponent } from './besoins/besoins.component';
import { BesoinsCompetencesComponent } from './besoins-competences/besoins-competences.component';
import { RecherchesPersonnesComponent } from '../pages/recherches-personnes/recherches-personnes.component';
import { RecherchePersonneCreateComponent } from '../pages/recherche-personne-create/recherche-personne-create.component';
import { RecherchePersonneDetailComponent } from '../pages/recherche-personne-detail/recherche-personne-detail.component';

export const ADMIN_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'signalements', component: ReportingComponent }, 
  { path: 'dossiers', component: DossiersComponent },
  { path: 'missions', component: MissionsComponent },
  { path: 'equipes', component: TeamsComponent },
  { path: 'institutions', component: InstitutionsComponent },
  { path: 'crises', component: CrisesComponent },
  { path: 'centres', component: CentresComponent },
  { path: 'carte', component: MapComponent },
  { path: 'resultats', component: ResultsComponent },
  { path: 'utilisateurs', component: UsersComponent, canActivate: [sysAdminGuard] },
  { path: 'competences', component: CompetencesComponent },
  { path: 'besoins', component: BesoinsComponent },
  { path: 'correspondances', component: BesoinsCompetencesComponent },
  { path: 'affectations', component: AffectationsComponent },
  { path: 'recherches-personnes', component: RecherchesPersonnesComponent },
  { path: 'recherches-personnes/new', component: RecherchePersonneCreateComponent },
  { path: 'recherches-personnes/:id', component: RecherchePersonneDetailComponent },
];

