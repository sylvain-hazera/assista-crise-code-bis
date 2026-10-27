import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable, forkJoin } from 'rxjs';

import { CrisisService } from '../../services/crisis.service';
import { PlanService } from '../../services/plan.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { TeamService } from '../../services/team.service';
import { AffectationCompetenceService } from '../../services/affectation-competence.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { UserService } from '../../services/user.service';
import { NotificationAlertePCSService } from '../../services/notification-alerte-pcs.service';
import { NotificationAlertePCS } from '../../shared/models/notification-alerte-pcs.model';
import { Crisis } from '../../shared/models/crisis.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Team } from '../../shared/models/team.model';
import { RoleOperationnel } from '../../shared/models/institution.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { User } from '../../shared/models/user.model';
import { AddressResult } from '../../shared/models/address-result.model';
import { AddressPickerComponent } from '../../shared/components/common/address-picker/address-picker.component';

/** Une personne à inviter dans l'équipe. Invitée = rattachée à l'institution de l'équipe avec
 * les droits collectivité locale (voir TeamViewSet.inviter_membre) : c'est le même geste que
 * depuis la page Équipes, rendu répétable ici pour poser une équipe complète d'un coup
 * (demande Nicolas Larvor du 26/10/2026). */
interface InvitationMembre {
  prenom: string;
  nom: string;
  email: string;
  telephone: string;
  roleCode: string | null;
}

interface EtapePoint {
  // null tant que le type n'est pas choisi (lignes ajoutées par ajouterPoint()).
  pointTypeCode: string | null;
  titre: string;
  description: string;
  suggestions: string[];
  // Distingue les 3 lignes par défaut d'une ligne ajoutée (type + nom seulement).
  isDefault: boolean;
  nom: string;
  // Adresse postale du point, exigée à la création : sans coordonnées, le point n'apparaît sur
  // aucune carte, aucune distance n'est calculable depuis une demande, et sa commune reste
  // inconnue (PointOperationnel n'a pas de commune_code, elle est déduite du point GPS).
  adresse: string;
  latitude: number | null;
  longitude: number | null;
  cree: boolean;
  // Vrai quand le point existait DÉJÀ sur la crise avant d'ouvrir l'assistant : il ne sera
  // pas recréé, et son nom/adresse ne s'éditent pas ici (voir reconcilierAvecLExistant).
  dejaEnPlace: boolean;
  point: PointOperationnel | null;
  equipeId: string | null;
  nouvelleEquipeNom: string;
  // Saisi au récapitulatif pour une équipe juste créée ; zone déduite du territoire de la crise.
  responsable: { prenom: string; nom: string; email: string; telephone: string; roleCode: string | null; membreExistantId: string | null };
  // Personnes externes à inviter, en plus du contact principal ci-dessus.
  invitations: InvitationMembre[];
  membresAjoutes: string[];
  themeIds: string[];
  competenceIds: string[];
  missionDescription: string;
  infosSaving: boolean;
  infosDone: boolean;
  infosSkipped: boolean;
  infosError: string;
  // Candidats résolus depuis l'institution réelle de l'équipe (voir chargerContexteEquipe).
  candidateMembers: User[];
}

/** Assistant de démarrage de crise : points stratégiques, équipes, récapitulatif.
 * Simple index `step` et panneaux conditionnels ; uniquement des endpoints existants
 * (PointOperationnelViewSet, TeamViewSet). Voir DOCUMENTATION.md, § 6.2. */
@Component({
  selector: 'app-crise-demarrage',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AddressPickerComponent],
  templateUrl: './crise-demarrage.component.html',
  styleUrl: './crise-demarrage.component.scss',
})
export class CriseDemarrageComponent implements OnInit {

  criseId!: string;
  crise: Crisis | null = null;
  pointTypes: PointType[] = [];
  teams: Team[] = [];
  roles: RoleOperationnel[] = [];
  besoins: Besoin[] = [];
  competences: Competence[] = [];
  // Territoire communal de la crise (pas de l'institution pilote), zone par défaut des équipes créées ici.
  criseCommuneCode: string | null = null;

  step = 1; // 1 = points, 2 = équipes, 3 = récapitulatif
  saving = false;
  errorMessage = '';

  savingPlan = false;
  planSaved = false;
  planErrorMessage = '';

  private extrasEtape(): Pick<EtapePoint,
    'responsable' | 'invitations' | 'membresAjoutes' | 'themeIds' | 'competenceIds' | 'missionDescription' |
    'infosSaving' | 'infosDone' | 'infosSkipped' | 'infosError' | 'candidateMembers'
  > {
    return {
      responsable: { prenom: '', nom: '', email: '', telephone: '', roleCode: null, membreExistantId: null },
      invitations: [],
      membresAjoutes: [], themeIds: [], competenceIds: [], missionDescription: '',
      infosSaving: false, infosDone: false, infosSkipped: false, infosError: '',
      candidateMembers: [],
    };
  }

  etapes: EtapePoint[] = [
    {
      pointTypeCode: 'CELLULE_CRISE', titre: 'Cellule de crise',
      description: "Le lieu depuis lequel la crise est pilotée.",
      suggestions: ['Mairie'], isDefault: true,
      nom: 'Mairie', adresse: '', latitude: null, longitude: null,
      cree: false, dejaEnPlace: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
    {
      pointTypeCode: 'HEBERGEMENT', titre: 'Centre d\'accueil des populations',
      description: "Où les personnes évacuées ou sinistrées sont accueillies.",
      suggestions: ['Salle des fêtes'], isDefault: true,
      nom: 'Salle des fêtes', adresse: '', latitude: null, longitude: null,
      cree: false, dejaEnPlace: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
    {
      pointTypeCode: 'REGROUPEMENT_MOYENS', titre: 'Centre de regroupement des moyens',
      description: "Où le matériel et les ressources mobilisées sont centralisés.",
      // « Centre technique municipal » et non « Salle des fêtes » : le défaut proposait le
      // MÊME bâtiment qu'à l'étape précédente, et deux communes l'ont accepté tel quel —
      // sinistrés et dépôt de matériel dans la même salle, ce qui ne se décide pas par
      // inadvertance. La salle des fêtes reste proposée en second, pour les communes qui n'ont
      // pas de centre technique.
      suggestions: ['Centre technique municipal', 'Salle des fêtes'], isDefault: true,
      nom: 'Centre technique municipal', adresse: '', latitude: null, longitude: null,
      cree: false, dejaEnPlace: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
  ];

  /** Les lieux désignés par plus d'une étape.
   *
   * Un même bâtiment peut légitimement tenir deux rôles — dans une petite commune, la mairie
   * est souvent à la fois cellule de crise et point de regroupement. C'est donc un
   * AVERTISSEMENT et jamais un refus : on le montre pour que ce soit un choix, pas un défaut
   * subi. Comparaison insensible à la casse et aux accents, parce que « salle des fetes » et
   * « Salle des Fêtes » sont le même endroit. */
  get lieuxEnDoublon(): string[] {
    const parLieu = new Map<string, string[]>();
    for (const etape of this.etapes) {
      const nom = etape.nom.trim();
      if (!nom) { continue; }
      const cle = nom.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      parLieu.set(cle, [...(parLieu.get(cle) ?? []), nom]);
    }
    return [...parLieu.values()].filter(noms => noms.length > 1).map(noms => noms[0]);
  }

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private crisisService: CrisisService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private teamService: TeamService,
    private affectationCompetenceService: AffectationCompetenceService,
    private planService: PlanService,
    private roleOperationnelService: RoleOperationnelService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private userService: UserService,
    private notificationAlertePCSService: NotificationAlertePCSService,
  ) {}

  ngOnInit(): void {
    this.criseId = this.route.snapshot.paramMap.get('id')!;
    this.crisisService.getById(this.criseId).subscribe(c => {
      this.crise = c;
      if (!this.messagePCS) {
        this.messagePCS = `La crise « ${c.name} » vient d'être déclarée, ce qui active le plan `
          + `communal/intercommunal de sauvegarde. Merci de prendre contact avec la cellule de crise.`;
      }
    });
    this.crisisService.getCommune(this.criseId).subscribe({
      next: (res) => (this.criseCommuneCode = res.commune_code),
      error: () => {},
    });
    // Les types ET les points déjà posés sur la crise, ensemble : la réconciliation a besoin
    // des deux (voir reconcilierAvecLExistant).
    forkJoin({
      types: this.pointTypeService.getAll(),
      points: this.pointService.getByCrise(this.criseId),
    }).subscribe({
      next: ({ types, points }) => {
        this.pointTypes = types;
        this.reconcilierAvecLExistant(points);
      },
      error: () => this.pointTypeService.getAll().subscribe(t => (this.pointTypes = t)),
    });
    this.teamService.equipesInstitution().subscribe(teams => (this.teams = teams));
    this.roleOperationnelService.getAll().subscribe(roles => (this.roles = roles));
    this.besoinService.getAll().subscribe(besoins => (this.besoins = besoins));
    this.competenceService.getAll().subscribe(competences => (this.competences = competences));
    this.chargerNotificationsPCS();
  }

  // ══ Checklist d'alerte PCS/PICS (interlocuteurs à prévenir) ═══════════════
  notificationsPCS: NotificationAlertePCS[] = [];
  messagePCS = '';
  selectionEnvoiPCS = new Set<string>();
  envoiPCSEnCours = false;
  erreurEnvoiPCS = '';

  private chargerNotificationsPCS(): void {
    this.notificationAlertePCSService.getForCrise(this.criseId).subscribe(notifs => {
      this.notificationsPCS = notifs;
      // Lignes envoyables (non terminales) cochées par défaut.
      this.selectionEnvoiPCS = new Set(this.notificationsAutoEnAttente.map(n => n.id));
    });
  }

  get notificationsAuto(): NotificationAlertePCS[] {
    return this.notificationsPCS.filter(n => n.canal_tente === 'EMAIL' || n.canal_tente === 'MATRIX');
  }

  get notificationsAutoEnAttente(): NotificationAlertePCS[] {
    return this.notificationsAuto.filter(n => n.statut === 'EN_ATTENTE' || n.statut === 'ECHEC_AUTO');
  }

  get notificationsManuelles(): NotificationAlertePCS[] {
    return this.notificationsPCS.filter(n => n.canal_tente !== 'EMAIL' && n.canal_tente !== 'MATRIX');
  }

  toggleSelectionEnvoiPCS(id: string): void {
    if (this.selectionEnvoiPCS.has(id)) this.selectionEnvoiPCS.delete(id);
    else this.selectionEnvoiPCS.add(id);
  }

  envoyerSelectionPCS(): void {
    if (this.selectionEnvoiPCS.size === 0 || !this.messagePCS.trim()) return;
    this.envoiPCSEnCours = true;
    this.erreurEnvoiPCS = '';
    this.notificationAlertePCSService.envoyerLot(this.criseId, Array.from(this.selectionEnvoiPCS), this.messagePCS.trim()).subscribe({
      next: () => {
        this.envoiPCSEnCours = false;
        this.chargerNotificationsPCS();
      },
      error: () => {
        this.envoiPCSEnCours = false;
        this.erreurEnvoiPCS = "Échec de l'envoi — réessayez.";
      },
    });
  }

  confirmerNotificationPCS(notif: NotificationAlertePCS): void {
    this.notificationAlertePCSService.confirmer(notif.id).subscribe(updated => {
      this.notificationsPCS = this.notificationsPCS.map(n => (n.id === updated.id ? updated : n));
    });
  }

  libelleStatutPCS(statut: string): string {
    return {
      EN_ATTENTE: 'En attente', ENVOYE_AUTO: 'Envoyé', ECHEC_AUTO: "Échec d'envoi",
      CONFIRME_PAR_CONTACT: 'Confirmé par le contact', CONFIRME_MANUEL: 'Confirmé (manuel)',
    }[statut] || statut;
  }

  classeStatutPCS(statut: string): string {
    return {
      EN_ATTENTE: 'statut-attente', ENVOYE_AUTO: 'statut-envoye', ECHEC_AUTO: 'statut-echec',
      CONFIRME_PAR_CONTACT: 'statut-confirme', CONFIRME_MANUEL: 'statut-confirme',
    }[statut] || '';
  }

  libelleReponseContactPCS(notif: NotificationAlertePCS): string {
    if (!notif.reponse_contact) return '';
    return {
      PAS_DE_RAPPEL: 'Pas besoin de rappeler', MERCI_RAPPELER: 'Merci de rappeler', AUTRE: 'Autre',
    }[notif.reponse_contact] || '';
  }

  /** Relit l'institution via l'équipe elle-même, jamais l'institution en cache : un compte
   * multi-institutions résoudrait sinon la mauvaise liste. Préremplit aussi thèmes et
   * spécialités depuis la fiche quand l'équipe existe déjà, pour que la compléter au
   * récapitulatif soit une confirmation d'un clic et non une ressaisie. */
  private chargerContexteEquipe(etape: EtapePoint): void {
    if (!etape.equipeId) { return; }
    this.teamService.getById(etape.equipeId).subscribe(team => {
      if (etape.competenceIds.length === 0) { etape.competenceIds = [...(team.competence_ids || [])]; }
      if (etape.themeIds.length === 0) { etape.themeIds = [...(team.theme_ids || [])]; }
      if (!team.institution) { return; }
      this.userService.getAll({ institution: [team.institution] }).subscribe(users => {
        etape.candidateMembers = users;
      });
    });
  }

  ajouterInvitation(etape: EtapePoint): void {
    etape.invitations = [
      ...etape.invitations,
      { prenom: '', nom: '', email: '', telephone: '', roleCode: null },
    ];
  }

  retirerInvitation(etape: EtapePoint, invitation: InvitationMembre): void {
    etape.invitations = etape.invitations.filter(i => i !== invitation);
  }

  /** Une invitation commencée doit être complète : prénom, nom, email et rôle. */
  invitationIncomplete(invitation: InvitationMembre): boolean {
    const commencee = !!(invitation.prenom.trim() || invitation.nom.trim()
      || invitation.email.trim() || invitation.telephone.trim() || invitation.roleCode);
    return commencee && !(invitation.prenom.trim() && invitation.nom.trim()
      && invitation.email.trim() && invitation.roleCode);
  }

  private invitationsCompletes(etape: EtapePoint): InvitationMembre[] {
    return etape.invitations.filter(i =>
      i.prenom.trim() && i.nom.trim() && i.email.trim() && i.roleCode);
  }

  private typeIdFor(code: string): string | null {
    return this.pointTypes.find(t => t.code === code)?.id ?? null;
  }

  pointTypeLibelle(code: string | null): string {
    return this.pointTypes.find(t => t.code === code)?.libelle ?? '';
  }

  choisirSuggestion(etape: EtapePoint, nom: string): void {
    etape.nom = nom;
  }

  /** Le composant émet null quand le champ est vidé après une sélection : on repasse alors le
   * point en « adresse non renseignée » plutôt que de garder des coordonnées orphelines. */
  onAdressePoint(etape: EtapePoint, adresse: AddressResult | null): void {
    etape.adresse = adresse?.label ?? '';
    etape.latitude = adresse?.latitude ?? null;
    etape.longitude = adresse?.longitude ?? null;
  }

  ajouterPoint(): void {
    this.etapes = [
      ...this.etapes,
      {
        pointTypeCode: null, titre: 'Nouveau point', description: '', suggestions: [], isDefault: false,
        nom: '', adresse: '', latitude: null, longitude: null,
        cree: false, dejaEnPlace: false, point: null, equipeId: null, nouvelleEquipeNom: '',
        ...this.extrasEtape(),
      },
    ];
  }

  retirerPoint(etape: EtapePoint): void {
    this.etapes = this.etapes.filter(e => e !== etape);
  }

  /** Les points de la crise au moment d'ouvrir l'assistant. Sert aussi à prévenir sur une
   * ligne ajoutée qui redésigne un point existant. */
  pointsExistants: PointOperationnel[] = [];

  /** Reprend les points déjà posés sur la crise au lieu de proposer de les recréer.
   *
   * L'assistant repartait de ses trois étapes vierges à chaque ouverture et recréait tout.
   * Constaté le 26/10/2026 : un adjoint l'a lancé trois fois sur la même crise en deux
   * minutes, et le troisième passage a reproduit à l'identique le premier — trois points en
   * doublon exact (même crise, même nom, même type). Rien ne l'en avait averti, et rien ne lui
   * montrait que son premier passage avait abouti : c'est probablement pour ça qu'il a
   * recommencé.
   *
   * Un point repris est marqué `cree` : il traverse donc les étapes suivantes (affectation
   * d'équipe, récapitulatif) comme s'il venait d'être posé, ce qui est bien le but — on
   * revient dans l'assistant pour COMPLÉTER, pas pour tout refaire. */
  private reconcilierAvecLExistant(points: PointOperationnel[]): void {
    this.pointsExistants = points;
    for (const etape of this.etapes) {
      if (!etape.pointTypeCode) { continue; }
      const typeId = this.typeIdFor(etape.pointTypeCode);
      const existant = points.find(p => p.type === typeId);
      if (!existant) { continue; }
      etape.dejaEnPlace = true;
      etape.cree = true;
      etape.point = existant;
      etape.nom = existant.nom;
      etape.adresse = existant.adresse ?? '';
      etape.latitude = existant.latitude ?? null;
      etape.longitude = existant.longitude ?? null;
      etape.equipeId = existant.equipe ?? null;
    }
  }

  get etapesDejaEnPlace(): EtapePoint[] {
    return this.etapes.filter(e => e.dejaEnPlace);
  }

  /** Une ligne AJOUTÉE qui redésigne un point déjà présent sur la crise (même nom, même type).
   * Avertissement et non refus : deux bâtiments homonymes dans deux communes d'une crise
   * intercommunale sont parfaitement possibles. */
  get etapesDoublonDeLExistant(): EtapePoint[] {
    return this.etapes.filter(etape => {
      if (etape.dejaEnPlace || !etape.pointTypeCode || !etape.nom.trim()) { return false; }
      const typeId = this.typeIdFor(etape.pointTypeCode);
      return this.pointsExistants.some(
        p => p.type === typeId && this._memeLieu(p.nom, etape.nom));
    });
  }

  private _memeLieu(a: string, b: string): boolean {
    const normalise = (v: string) =>
      v.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    return normalise(a) === normalise(b);
  }

  /** Crée en un lot les points nommés (case vide = non pourvu, déjà en place = non recréé). */
  terminerEtapePoints(): void {
    const aCreer = this.etapes.filter(e => e.nom.trim() && !e.dejaEnPlace);
    const sansType = aCreer.find(e => !e.pointTypeCode);
    if (sansType) {
      this.errorMessage = `Choisissez un type pour "${sansType.nom}".`;
      return;
    }
    // L'adresse est exigée (26/10/2026) : un point sans coordonnées n'apparaît sur aucune
    // carte, ne peut être proposé à personne par proximité, et sa commune reste inconnue —
    // « Salle des fêtes » sans adresse n'aide personne à s'y rendre le jour de la crise.
    const sansAdresse = aCreer.find(e => e.latitude == null || e.longitude == null);
    if (sansAdresse) {
      this.errorMessage = `Indiquez l'adresse de « ${sansAdresse.nom} » : sans elle, le point `
        + `n'apparaîtra sur aucune carte et personne ne pourra y être orienté.`;
      return;
    }
    this.errorMessage = '';
    if (aCreer.length === 0) {
      this.step = 2;
      return;
    }
    this.saving = true;
    let restant = aCreer.length;
    let echec = false;
    const fini = () => {
      restant--;
      if (restant === 0) {
        this.saving = false;
        if (echec) {
          this.errorMessage = "Certains points n'ont pas pu être créés — réessayez, ou retirez-les avant de continuer.";
        } else {
          this.step = 2;
        }
      }
    };
    aCreer.forEach(etape => {
      const typeId = this.typeIdFor(etape.pointTypeCode!);
      if (!typeId) { echec = true; fini(); return; }
      this.pointService.create({
        nom: etape.nom.trim(), type: typeId, crise: this.criseId,
        adresse: etape.adresse,
        location: JSON.stringify({ type: 'Point', coordinates: [etape.longitude, etape.latitude] }),
      }).subscribe({
        next: (point) => { etape.cree = true; etape.point = point; fini(); },
        error: () => { echec = true; fini(); },
      });
    });
  }

  get etapesAvecPoint(): EtapePoint[] {
    return this.etapes.filter(e => e.cree && e.point);
  }

  /** Passe par `nouvelle_equipe_nom` sur le point, comme point-modal : implication de
   * l'institution, notification du référent, journalisation (_creer_equipe_pour_point). */
  terminerEtapeEquipes(): void {
    const affectations = this.etapesAvecPoint.filter(e => e.point && (e.equipeId || e.nouvelleEquipeNom.trim()));
    if (affectations.length === 0) {
      this.step = 3;
      return;
    }
    this.saving = true;
    let restant = affectations.length;
    const equipesACrise = new Set<string>();
    const terminerSiFini = () => {
      restant--;
      if (restant === 0) {
        // Lier un point n'ajoute pas la crise à Team.assigned_crises : appel explicite nécessaire.
        equipesACrise.forEach(equipeId => {
          this.teamService.assignerCrise(equipeId, this.criseId).subscribe({ error: () => {} });
        });
        this.saving = false;
        this.step = 3;
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
            // Aussi pour une équipe EXISTANTE : elle doit recevoir spécialités et mission sur
            // CETTE crise, sinon aucune demande ne lui sera suggérée ici (le formulaire du
            // récapitulatif ne s'affichait que pour une équipe créée à la volée).
            this.chargerContexteEquipe(etape);
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

  toggleThemeFor(etape: EtapePoint, id: string, checked: boolean): void {
    etape.themeIds = checked ? [...etape.themeIds, id] : etape.themeIds.filter(x => x !== id);
  }

  toggleCompetenceFor(etape: EtapePoint, id: string, checked: boolean): void {
    etape.competenceIds = checked ? [...etape.competenceIds, id] : etape.competenceIds.filter(x => x !== id);
  }

  /** Spécialité et mission sont EXIGÉES ici (décision du 24/10/2026) : sans au moins une
   * compétence, aucune affectation de compétence n'est créée sur la crise et plus rien ne peut
   * être suggéré automatiquement ensuite ; sans mission, l'équipe n'a rien à quoi rattacher ses
   * ressources ni ses bénévoles recrutés. Une équipe laissée incomplète ici est une équipe qui
   * ne servira à rien le jour où la crise démarre. */
  equipeIncomplete(etape: EtapePoint): boolean {
    return etape.competenceIds.length === 0 || !etape.missionDescription.trim();
  }

  /** Complète l'équipe juste créée (contact, thèmes, spécialité, mission) pour que les
   * automatisations (hébergement, recrutement) fonctionnent ; zone déduite du territoire de la crise. */
  enregistrerEquipe(etape: EtapePoint): void {
    if (!etape.equipeId) { return; }
    if (this.equipeIncomplete(etape)) {
      etape.infosError = "Indiquez au moins une spécialité et la mission confiée : "
        + "sans elles, aucune demande ne pourra être suggérée automatiquement à cette équipe.";
      return;
    }
    if (etape.invitations.some(i => this.invitationIncomplete(i))) {
      etape.infosError = "Complétez (ou retirez) les invitations commencées : prénom, nom, "
        + "email et rôle sont nécessaires pour créer l'accès de la personne.";
      return;
    }
    const r = etape.responsable;
    const invite = !!(r.prenom.trim() && r.nom.trim() && r.email.trim() && r.roleCode);

    etape.infosSaving = true;
    etape.infosError = '';

    const patchPayload: Partial<Team> = {
      theme_ids: etape.themeIds,
      competence_ids: etape.competenceIds,
      communes: this.criseCommuneCode ? [this.criseCommuneCode] : [],
    };
    if (r.membreExistantId) {
      patchPayload.member_ids = [...etape.membresAjoutes, r.membreExistantId];
    }

    const appels: Observable<any>[] = [this.teamService.patch(etape.equipeId, patchPayload)];
    if (invite) {
      appels.push(this.teamService.inviterMembre(etape.equipeId, {
        first_name: r.prenom.trim(), last_name: r.nom.trim(),
        email: r.email.trim(), phone_number: r.telephone.trim(), role_code: r.roleCode!,
      }));
    }
    // Chaque invitation rattache la personne à l'institution de l'équipe avec les droits
    // collectivité locale, et lui envoie son lien d'activation (TeamViewSet.inviter_membre) —
    // y compris quelqu'un qui n'a aucun compte sur la plateforme.
    for (const invitation of this.invitationsCompletes(etape)) {
      appels.push(this.teamService.inviterMembre(etape.equipeId, {
        first_name: invitation.prenom.trim(), last_name: invitation.nom.trim(),
        email: invitation.email.trim(), phone_number: invitation.telephone.trim(),
        role_code: invitation.roleCode!,
      }));
    }
    appels.push(this.teamService.definirMission(etape.equipeId, etape.missionDescription.trim(), this.criseId));

    // Ce qui rend l'affectation automatique possible : `competence_ids` ci-dessus ne remplit que
    // les compétences de la FICHE équipe, que le moteur de suggestion ne regarde pas. Seule une
    // AffectationCompetence (équipe ↔ compétence ↔ crise) est lue par
    // meilleure_equipe_pour_competence. Sans ces appels, on créait des équipes avec leurs
    // spécialités et aucune demande ne leur était jamais suggérée.
    for (const competenceId of etape.competenceIds) {
      appels.push(this.affectationCompetenceService.create({
        crise: this.criseId, competence: competenceId, equipe: etape.equipeId, active: true,
      }));
    }

    forkJoin(appels).subscribe({
      next: () => {
        if (r.membreExistantId) { etape.membresAjoutes = [...etape.membresAjoutes, r.membreExistantId]; }
        etape.invitations = [];
        etape.infosSaving = false;
        etape.infosDone = true;
      },
      error: () => {
        etape.infosSaving = false;
        etape.infosError = "Certaines informations n'ont pas pu être enregistrées. Réessayez, ou complétez plus tard depuis la fiche équipe.";
      },
    });
  }

  /** Même si l'utilisateur reporte, la zone d'intervention est fixée. */
  passerEquipe(etape: EtapePoint): void {
    etape.infosSkipped = true;
    if (etape.equipeId && this.criseCommuneCode) {
      this.teamService.patch(etape.equipeId, { communes: [this.criseCommuneCode] }).subscribe({ error: () => {} });
    }
  }

  /** Enregistre équipes et points comme Plan (références, pas de copie), réactivable sur une
   * prochaine crise via PlanViewSet.activer. */
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
        this.planErrorMessage = "Impossible d'enregistrer ce dispositif. Réessayez depuis la page Mon plan de sauvegarde.";
      },
    });
  }
}
