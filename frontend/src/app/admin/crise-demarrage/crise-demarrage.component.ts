import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { CrisisService } from '../../services/crisis.service';
import { PlanService } from '../../services/plan.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { TeamService } from '../../services/team.service';
import { Crisis } from '../../shared/models/crisis.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Team } from '../../shared/models/team.model';

interface EtapePoint {
  code: 'CELLULE_CRISE' | 'HEBERGEMENT' | 'REGROUPEMENT_MOYENS';
  titre: string;
  description: string;
  suggestions: string[];
  nom: string;
  skipped: boolean;
  cree: boolean;
  point: PointOperationnel | null;
  equipeId: string | null;
  nouvelleEquipeNom: string;
}

/** Wizard proposé juste après la déclaration d'une crise (ou depuis son détail, plus tard) pour
 * poser rapidement ses éléments stratégiques — voir la demande utilisateur du 2026-09-10.
 * Premier composant "multi-étapes" du projet : pas de librairie de stepper, juste un index
 * `step` et des panneaux conditionnels, cohérent avec le reste du code. Réutilise entièrement
 * des endpoints déjà existants (PointOperationnelViewSet, TeamViewSet) — aucune route backend
 * dédiée. */
@Component({
  selector: 'app-crise-demarrage',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './crise-demarrage.component.html',
  styleUrl: './crise-demarrage.component.scss',
})
export class CriseDemarrageComponent implements OnInit {

  criseId!: string;
  crise: Crisis | null = null;
  pointTypes: PointType[] = [];
  teams: Team[] = [];

  step = 1; // 1..3 = points, 4 = équipes, 5 = récapitulatif
  saving = false;
  errorMessage = '';

  savingPlan = false;
  planSaved = false;
  planErrorMessage = '';

  etapes: EtapePoint[] = [
    {
      code: 'CELLULE_CRISE', titre: 'Cellule de crise',
      description: "Le lieu depuis lequel la crise est pilotée.",
      suggestions: ['Mairie'],
      nom: 'Mairie', skipped: false, cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
    },
    {
      code: 'HEBERGEMENT', titre: 'Centre d\'accueil des populations',
      description: "Où les personnes évacuées ou sinistrées sont accueillies.",
      suggestions: ['Salle des fêtes'],
      nom: 'Salle des fêtes', skipped: false, cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
    },
    {
      code: 'REGROUPEMENT_MOYENS', titre: 'Centre de regroupement des moyens',
      description: "Où le matériel et les ressources mobilisées sont centralisés.",
      suggestions: ['Salle des fêtes', 'Centre technique municipal'],
      nom: 'Salle des fêtes', skipped: false, cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
    },
  ];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private crisisService: CrisisService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private teamService: TeamService,
    private planService: PlanService,
  ) {}

  ngOnInit(): void {
    this.criseId = this.route.snapshot.paramMap.get('id')!;
    this.crisisService.getById(this.criseId).subscribe(c => (this.crise = c));
    this.pointTypeService.getAll().subscribe(types => (this.pointTypes = types));
    this.teamService.vueMairie().subscribe(teams => (this.teams = teams));
  }

  get etapeCourante(): EtapePoint | null {
    return this.step >= 1 && this.step <= 3 ? this.etapes[this.step - 1] : null;
  }

  private typeIdFor(code: string): string | null {
    return this.pointTypes.find(t => t.code === code)?.id ?? null;
  }

  choisirSuggestion(etape: EtapePoint, nom: string): void {
    etape.nom = nom;
  }

  passerEtape(etape: EtapePoint): void {
    etape.skipped = true;
    etape.cree = false;
    etape.point = null;
    this.step++;
  }

  validerEtape(etape: EtapePoint): void {
    if (!etape.nom.trim()) {
      return;
    }
    const typeId = this.typeIdFor(etape.code);
    if (!typeId) {
      this.errorMessage = `Type de point "${etape.code}" introuvable — contactez un administrateur.`;
      return;
    }
    this.saving = true;
    this.errorMessage = '';
    this.pointService.create({ nom: etape.nom.trim(), type: typeId, crise: this.criseId }).subscribe({
      next: (point) => {
        etape.skipped = false;
        etape.cree = true;
        etape.point = point;
        this.saving = false;
        this.step++;
      },
      error: () => {
        this.errorMessage = `Impossible de créer "${etape.nom}". Réessayez ou passez cette étape.`;
        this.saving = false;
      },
    });
  }

  /** Points réellement créés à l'étape "équipes" (les étapes passées n'y figurent pas). */
  get etapesAvecPoint(): EtapePoint[] {
    return this.etapes.filter(e => e.cree && e.point);
  }

  /** Un point n'a une équipe "complète" que si elle passe par le même mécanisme serveur que
   * partout ailleurs (point-modal, `nouvelle_equipe_nom` sur le create/update du point) : ça
   * déclare l'institution comme actrice de la crise (ImplicationInstitution), notifie son
   * référent et journalise le tout — un simple `TeamService.create({name})` fait ici avant ce
   * correctif ne faisait rien de tout ça (voir _creer_equipe_pour_point côté backend). */
  terminerEtapeEquipes(): void {
    const affectations = this.etapesAvecPoint.filter(e => e.point && (e.equipeId || e.nouvelleEquipeNom.trim()));
    if (affectations.length === 0) {
      this.step = 5;
      return;
    }
    this.saving = true;
    let restant = affectations.length;
    const equipesACrise = new Set<string>();
    const terminerSiFini = () => {
      restant--;
      if (restant === 0) {
        // Lier le point à l'équipe (ci-dessus) n'ajoute jamais la crise à
        // Team.assigned_crises — sans cet appel, l'équipe reste invisible dans les vues qui
        // s'appuient spécifiquement sur ce champ (ressources mobilisées, recrutement scopé,
        // matching hébergement), même si elle est bien affectée aux points de la crise.
        equipesACrise.forEach(equipeId => {
          this.teamService.assignerCrise(equipeId, this.criseId).subscribe({ error: () => {} });
        });
        this.saving = false;
        this.step = 5;
      }
    };
    affectations.forEach(etape => {
      const nomNouvelleEquipe = etape.nouvelleEquipeNom.trim();
      const payload = nomNouvelleEquipe && !etape.equipeId
        ? { nouvelle_equipe_nom: nomNouvelleEquipe }
        : { equipe: etape.equipeId };
      this.pointService.update(etape.point!.id, payload).subscribe({
        next: (updated) => {
          etape.point = updated;
          if (updated.equipe) {
            etape.equipeId = updated.equipe;
            equipesACrise.add(updated.equipe);
          }
          terminerSiFini();
        },
        error: () => terminerSiFini(),
      });
    });
  }

  terminer(): void {
    this.router.navigate(['/admin/crises']);
  }

  /** Réutilise Plan (dispositif pré-enregistré) tel quel : on référence les équipes/points déjà
   * créés (jamais de copie, voir docstring de Plan côté backend) sous un nom, pour pouvoir tout
   * ré-activer en un geste sur une prochaine crise via PlanViewSet.activer. Les équipes gardent
   * leur zone/compétences propres, le matériel reste attaché aux points eux-mêmes : rien à
   * dupliquer, il suffit de les regrouper ici. */
  enregistrerCommeDispositif(): void {
    const points = this.etapesAvecPoint;
    if (points.length === 0) {
      return;
    }
    const nomParDefaut = `Dispositif${this.crise?.name ? ' — ' + this.crise.name : ''}`;
    const nom = prompt('Nom du dispositif à sauvegarder pour la prochaine fois :', nomParDefaut);
    if (!nom || !nom.trim()) {
      return;
    }

    const pointsIds = points.map(e => e.point!.id);
    const equipesIds = [...new Set(points.map(e => e.equipeId).filter((id): id is string => !!id))];

    this.savingPlan = true;
    this.planErrorMessage = '';
    this.planService.create({ nom: nom.trim(), points_ids: pointsIds, equipes_ids: equipesIds }).subscribe({
      next: () => {
        this.savingPlan = false;
        this.planSaved = true;
      },
      error: () => {
        this.savingPlan = false;
        this.planErrorMessage = "Impossible d'enregistrer ce dispositif. Réessayez depuis la page Plans.";
      },
    });
  }
}
