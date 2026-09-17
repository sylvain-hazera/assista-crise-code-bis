import { InstitutionsComponent } from './institutions/institutions.component';
import { CrisesComponent } from './crises/crises.component';
import { CentresComponent } from './centres/centres.component';
import { StocksComparaisonComponent } from './stocks-comparaison/stocks-comparaison.component';
import { ZonesComponent } from './zones/zones.component';
import { PlansComponent } from './plans/plans.component';
import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard/dashboard.component';
import { ReportingComponent } from './reporting/reporting.component';
import { TeamsComponent } from './teams/teams.component';
import { MapComponent } from '../shared/components/common/map/map.component';
import { ResultsComponent } from './results/results.component';
import { UsersComponent } from './users/users.component';
import { AuditLogsComponent } from './audit-logs/audit-logs.component';
import { sysAdminGuard, institutionalEffectiveGuard, accountValidationGuard, zonesGuard } from '../core/guards/admin.guard';
import { AccesRefuseComponent } from './acces-refuse/acces-refuse.component';
import { AccountValidationsComponent } from './account-validations/account-validations.component';
import { CompetencesComponent } from './competences/competences.component';
import { AffectationsComponent } from './affectations/affectations.component';
import { DossiersComponent } from './dossiers/dossiers.component';
import { MissionsComponent } from './missions/missions.component';
import { VueMairieComponent } from './vue-mairie/vue-mairie.component';
import { ImportPersonnelComponent } from './import-personnel/import-personnel.component';
import { ImportInstitutionsComponent } from './import-institutions/import-institutions.component';
import { DeclarationsSecuriteComponent } from './declarations-securite/declarations-securite.component';
import { BesoinsComponent } from './besoins/besoins.component';
import { BesoinsCompetencesComponent } from './besoins-competences/besoins-competences.component';
import { MaterielComponent } from './materiel/materiel.component';
import { RessourcesMobiliseesComponent } from './ressources-mobilisees/ressources-mobilisees.component';
import { CriseDemarrageComponent } from './crise-demarrage/crise-demarrage.component';
import { MeshcoreCompanionsComponent } from './meshcore-companions/meshcore-companions.component';
import { MeshcoreCanauxComponent } from './meshcore-canaux/meshcore-canaux.component';
import { MeshtasticCompanionsComponent } from './meshtastic-companions/meshtastic-companions.component';
import { MeshtasticCanauxComponent } from './meshtastic-canaux/meshtastic-canaux.component';
import { RecherchesPersonnesComponent } from '../pages/recherches-personnes/recherches-personnes.component';
import { RecherchePersonneCreateComponent } from '../pages/recherche-personne-create/recherche-personne-create.component';
import { RecherchePersonneDetailComponent } from '../pages/recherche-personne-detail/recherche-personne-detail.component';

export const ADMIN_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'acces-refuse', component: AccesRefuseComponent },
  { path: 'dashboard', component: DashboardComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'signalements', component: ReportingComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'dossiers', component: DossiersComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'missions', component: MissionsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'vue-mairie', component: VueMairieComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'import-personnel', component: ImportPersonnelComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'import-institutions', component: ImportInstitutionsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'declarations-securite', component: DeclarationsSecuriteComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'equipes', component: TeamsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'institutions', component: InstitutionsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'crises', component: CrisesComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'crises/:crisisId/stocks', component: StocksComparaisonComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'crises/:id/demarrage', component: CriseDemarrageComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'meshcore-companions', component: MeshcoreCompanionsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'meshcore-canaux', component: MeshcoreCanauxComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'meshtastic-companions', component: MeshtasticCompanionsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'meshtastic-canaux', component: MeshtasticCanauxComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'centres', component: CentresComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'zones', component: ZonesComponent, canActivate: [institutionalEffectiveGuard, zonesGuard] },
  { path: 'plans', component: PlansComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'carte', component: MapComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'resultats', component: ResultsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'utilisateurs', component: UsersComponent, canActivate: [sysAdminGuard] },
  { path: 'main-courante', component: AuditLogsComponent, canActivate: [sysAdminGuard] },
  { path: 'validations-comptes', component: AccountValidationsComponent, canActivate: [accountValidationGuard] },
  { path: 'competences', component: CompetencesComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'besoins', component: BesoinsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'materiel', component: MaterielComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'ressources-mobilisees', component: RessourcesMobiliseesComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'correspondances', component: BesoinsCompetencesComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'affectations', component: AffectationsComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes', component: RecherchesPersonnesComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes/new', component: RecherchePersonneCreateComponent, canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes/:id', component: RecherchePersonneDetailComponent, canActivate: [institutionalEffectiveGuard] },
];

