import { forkJoin } from 'rxjs';

import { ContactInstitutionService } from '../../services/contact-institution.service';
import { DossierPcsService } from '../../services/dossier-pcs.service';
import { ContactInstitution } from '../../shared/models/institution.model';
import { CanalAlerte, EtatAlertes } from '../../services/alerte-habitants.service';
import { PiecesPlanComponent } from '../../shared/components/common/pieces-plan/pieces-plan.component';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';
import { ZoneService } from '../../services/zone.service';
import { TeamService } from '../../services/team.service';
import { Team } from '../../shared/models/team.model';
import { Zone } from '../../shared/models/zone.model';
import { ChampListe, Ligne, PARAGRAPHES_EN_LISTE, ParagrapheListe } from './pcs-listes.config';

/** Nom de la zone créée d'office pour chaque collectivité : ce n'est pas un quartier. */
const ZONE_AUTOMATIQUE = 'Mon territoire';

/**
 * Un paragraphe du plan communal de sauvegarde tenu en liste : organigramme du poste de
 * commandement, moyens d'alerte, exercices. Le paragraphe affiché vient de la route
 * (`data.paragraphe`), sa description de `pcs-listes.config.ts`.
 *
 * Comme les autres écrans du plan, il dit d'abord à quoi le paragraphe sert en crise, et rien de
 * ce qu'on n'y a pas mis n'empêche d'ouvrir une crise.
 */
@Component({
  selector: 'app-pcs-liste',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, PiecesPlanComponent],
  templateUrl: './pcs-liste.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class PcsListeComponent implements OnInit {
  paragraphe!: ParagrapheListe;
  /** Page « Alerte de la population » seulement : les moyens numériques de la collectivité
   * (messagerie, application, courriel, SMS, radio), avec ce qui manque à chacun. */
  canauxNumeriques: CanalAlerte[] = [];

  // ── Poste de commandement : reprendre un contact, inviter quelqu'un, créer l'équipe (18/11/2026)
  /** L'institution dont on tient le plan : pour ses contacts, ses invitations, ses équipes. */
  institutionId = '';
  contacts: ContactInstitution[] = [];
  /** Adresse saisie pour inviter quelqu'un qui n'est pas encore sur la plateforme, par champ. */
  invitation: Record<string, string> = {};
  messageInvitation: Record<string, string> = {};
  creationEquipe = false;
  creationFonctionsTypes = false;
  readonly FONCTIONS_TYPES = ['DOS', 'COORDINATION', 'ALERTE', 'SOUTIEN', 'LOGISTIQUE', 'SECRETARIAT'];
  lignes: Ligne[] = [];
  zones: Zone[] = [];
  equipes: Team[] = [];
  chargement = true;
  sansCollectivite = false;
  erreur = '';

  saisie: Record<string, any> = {};
  enModification: string | null = null;
  formulaireOuvert = false;
  enregistrement = false;

  constructor(private route: ActivatedRoute, private http: HttpClient, private zoneService: ZoneService,
              private teamService: TeamService, private dossier: DossierPcsService,
              private contactService: ContactInstitutionService) {}

  private get url(): string {
    return `${environment.apiUrl}/${this.paragraphe.ressource}/`;
  }

  ngOnInit(): void {
    this.paragraphe = PARAGRAPHES_EN_LISTE[this.route.snapshot.data['paragraphe']];
    if (this.paragraphe.ressource === 'pcs-moyens-alerte') {
      this.http.get<EtatAlertes>(`${environment.apiUrl}/alertes-population/`).subscribe({
        next: (etat) => { this.canauxNumeriques = etat.apercu.canaux; }, error: () => {},
      });
    }
    this.charger();
    if (this.paragraphe.champs.some(c => c.parDefaut)) {
      this.http.get<Record<string, string>>(`${this.url}fiches-types/`).subscribe({ next: (f) => { this.fichesTypes = f; }, error: () => {} });
    }
    if (this.paragraphe.champs.some(c => c.type === 'zone')) {
      // Les quartiers sont facultatifs : s'ils ne se chargent pas, le champ reste vide et c'est tout.
      this.zoneService.getAll().subscribe({
        next: (zones) => { this.zones = zones.filter(z => z.nom !== ZONE_AUTOMATIQUE); }, error: () => {},
      });
    }
    if (this.paragraphe.champs.some(c => c.type === 'personne')) {
      // Les contacts de l'institution, proposés pendant la frappe ; sans eux, on saisit à la main.
      this.dossier.lire().subscribe({
        next: (d) => {
          this.institutionId = d.institution;
          this.contactService.getForInstitution(d.institution).subscribe({
            next: (contacts) => { this.contacts = contacts.filter(c => c.actif !== false); }, error: () => {},
          });
        },
        error: () => {},
      });
    }
    if (this.paragraphe.champs.some(c => c.type === 'equipe')) {
      // Les équipes de la collectivité : celles qu'on peut relier à une fonction.
      this.teamService.equipesInstitution().subscribe({ next: (equipes) => { this.equipes = equipes; }, error: () => {} });
    }
  }

  /** Champs qui désignent un autre objet de la collectivité : vides, ils valent « aucun ». */
  private estUnLien(type: string): boolean {
    return type === 'zone' || type === 'equipe';
  }

  private charger(): void {
    this.http.get<Ligne[]>(this.url).subscribe({
      next: (lignes) => { this.lignes = lignes; this.chargement = false; },
      error: (e) => {
        this.chargement = false;
        this.sansCollectivite = e?.status === 403;
        if (!this.sansCollectivite) this.erreur = 'Impossible de lire ce paragraphe du plan.';
      },
    });
  }

  private saisieVide(): Record<string, any> {
    const vide: Record<string, any> = {};
    for (const champ of this.paragraphe.champs) {
      vide[champ.cle] = champ.type === 'choix' ? champ.options![0].valeur
        : champ.type === 'date' ? new Date().toISOString().slice(0, 10)
        : this.estUnLien(champ.type) ? null : '';
    }
    return vide;
  }

  ouvrirAjout(): void {
    this.saisie = this.saisieVide();
    this.enModification = null;
    this.formulaireOuvert = true;
    this.erreur = '';
  }

  get estOrganigramme(): boolean { return this.paragraphe.ressource === 'pcs-fonctions'; }

  /** Les fonctions types que la commune n'a pas encore : proposées d'un clic. */
  get fonctionsTypesManquantes(): string[] {
    const presentes = new Set(this.lignes.map(l => l['fonction']));
    return this.estOrganigramme ? this.FONCTIONS_TYPES.filter(f => !presentes.has(f)) : [];
  }

  creerFonctionsTypes(): void {
    const manquantes = this.fonctionsTypesManquantes;
    if (!manquantes.length || this.creationFonctionsTypes) return;
    this.creationFonctionsTypes = true;
    forkJoin(manquantes.map(fonction => this.http.post<Ligne>(this.url, { fonction }))).subscribe({
      next: () => { this.creationFonctionsTypes = false; this.charger(); },
      error: () => { this.creationFonctionsTypes = false; this.erreur = "Les fonctions types n'ont pas toutes pu être créées."; this.charger(); },
    });
  }

  private libelleFonction(): string {
    const champ = this.paragraphe.champs.find(c => c.cle === 'fonction');
    return (this.saisie['libelle'] || champ?.options?.find(o => o.valeur === this.saisie['fonction'])?.libelle || 'Poste de commandement') as string;
  }

  /** L'équipe n'existe pas encore : on la crée ici, au nom de la fonction, et on la relie. */
  creerEquipe(): void {
    if (this.creationEquipe) return;
    this.creationEquipe = true;
    const nom = `PCC — ${this.libelleFonction()}`.slice(0, 100);
    this.teamService.create({ name: nom, ...(this.institutionId ? { institution: this.institutionId } : {}) } as never).subscribe({
      next: (equipe) => { this.creationEquipe = false; this.equipes = [...this.equipes, equipe]; this.saisie['equipe'] = equipe.id; },
      error: () => { this.creationEquipe = false; this.erreur = "L'équipe n'a pas pu être créée."; },
    });
  }

  nomContact(contact: ContactInstitution): string {
    return contact.utilisateur_nom || contact.utilisateur_email || '';
  }

  /** On a choisi (ou tapé) le nom d'un contact de l'institution : son téléphone suit. */
  choisirPersonne(champ: ChampListe): void {
    const nom = String(this.saisie[champ.cle] || '').trim().toLowerCase();
    const contact = this.contacts.find(c => this.nomContact(c).toLowerCase() === nom);
    if (contact?.utilisateur_telephone && champ.telephone && !this.saisie[champ.telephone]) {
      this.saisie[champ.telephone] = contact.utilisateur_telephone;
    }
  }

  /** Quelqu'un qui n'est pas encore sur la plateforme : il reçoit une invitation par courriel,
   * et rejoint l'équipe de la fonction si elle en a une. */
  inviter(champ: ChampListe): void {
    const email = (this.invitation[champ.cle] || '').trim();
    if (!email || !this.institutionId) return;
    this.messageInvitation[champ.cle] = 'Envoi…';
    this.contactService.inviter(this.institutionId, email, this.saisie['equipe'] || undefined).subscribe({
      next: () => {
        this.messageInvitation[champ.cle] = `Invitation envoyée à ${email}.`;
        if (!this.saisie[champ.cle]) this.saisie[champ.cle] = email;
        this.invitation[champ.cle] = '';
      },
      error: (e) => { this.messageInvitation[champ.cle] = e?.error?.detail || e?.error?.error || "L'invitation n'est pas partie."; },
    });
  }

  modifier(ligne: Ligne): void {
    this.saisie = {};
    for (const champ of this.paragraphe.champs) this.saisie[champ.cle] = ligne[champ.cle] ?? (this.estUnLien(champ.type) ? null : '');
    this.enModification = ligne.id;
    this.formulaireOuvert = true;
    this.erreur = '';
  }

  /** Les fiches types par fonction ou par moyen, servies par le serveur : montrées dès qu'on
   * choisit, à la création comme à la modification (18/11/2026 : elles n'apparaissaient qu'en
   * modifiant une ligne déjà enregistrée). */
  fichesTypes: Record<string, string> = {};

  /** Texte proposé tant que le champ est vide : la fiche type de ce qui est choisi. */
  parDefaut(cle: string | undefined): string {
    if (!cle) return '';
    const choix = this.saisie['fonction'] ?? this.saisie['type'];
    if (choix && this.fichesTypes[choix]) return this.fichesTypes[choix];
    const ligne = this.lignes.find(l => l.id === this.enModification);
    return ligne ? (ligne[cle] || '') : '';
  }

  enregistrer(): void {
    this.enregistrement = true;
    this.erreur = '';
    const donnees = { ...this.saisie };
    for (const champ of this.paragraphe.champs) {
      if (this.estUnLien(champ.type)) donnees[champ.cle] = donnees[champ.cle] || null;
      else if (typeof donnees[champ.cle] === 'string') donnees[champ.cle] = donnees[champ.cle].trim();
    }
    const appel = this.enModification
      ? this.http.patch<Ligne>(`${this.url}${this.enModification}/`, donnees)
      : this.http.post<Ligne>(this.url, donnees);
    appel.subscribe({
      next: () => { this.enregistrement = false; this.formulaireOuvert = false; this.charger(); },
      error: (e) => {
        this.enregistrement = false;
        const detail = e?.error && typeof e.error === 'object' ? Object.values(e.error).flat().join(' ') : '';
        this.erreur = detail || "L'enregistrement a échoué.";
      },
    });
  }

  retirer(ligne: Ligne): void {
    if (!confirm(`Retirer « ${this.paragraphe.titreLigne(ligne)} » du plan ?`)) return;
    this.http.delete(`${this.url}${ligne.id}/`).subscribe({
      next: () => this.charger(), error: () => { this.erreur = 'Le retrait a échoué.'; },
    });
  }
}
