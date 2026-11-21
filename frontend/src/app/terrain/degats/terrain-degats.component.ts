import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Crisis } from '../../shared/models/crisis.model';
import { PointPickerComponent } from '../../shared/components/common/point-picker/point-picker.component';
import { HorsLigneService } from '../hors-ligne.service';
import { Releve, distanceEntre } from '../position/regles-suivi';
import { suivrePosition } from '../position/position-du-moment';
import { DegatsService, Tournee } from './degats.service';
import { Constat, DANGERS, ETATS_BIEN, PointTournee, cleDuPoint, distanceM, libelleEtat, prochainPoint } from './degats';

type Etape =
  | { nom: 'accueil' }
  | { nom: 'tournee' }
  | { nom: 'position'; point: PointTournee }
  | { nom: 'replacer'; point: PointTournee; lieu: { latitude: number; longitude: number } }
  | { nom: 'evaluer'; point: PointTournee | null; lieu: { latitude: number; longitude: number } | null; replace: boolean };

/**
 * L'évaluation des dégâts à pied, dans l'application web (DOSSIER-ADRESSES-ET-DEGATS.md, § 5 ;
 * DOSSIER-PWA-INTERVENANTS.md, lot 5) : le même parcours que l'application Android. Tournée des
 * points les plus proches → « le point est-il bien placé ? » (sinon : le replacer) → évaluer →
 * suivant ; et « nouveau point ici » là où il n'y a pas d'adresse. Tout part par la file ; sans
 * réseau, la tournée se calcule sur le secteur embarqué. Réservé au personnel municipal et aux
 * élus : le serveur vérifie la commune.
 */
@Component({
  selector: 'app-terrain-degats',
  imports: [DatePipe, DecimalPipe, FormsModule, PointPickerComponent],
  templateUrl: './terrain-degats.component.html',
  styleUrl: './terrain-degats.component.scss',
})
export class TerrainDegatsComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  readonly degats = inject(DegatsService);
  readonly horsLigne = inject(HorsLigneService);
  readonly ETATS = ETATS_BIEN;
  readonly DANGERS = DANGERS;

  readonly etape = signal<Etape>({ nom: 'accueil' });
  readonly crises = signal<{ id: string; nom: string }[]>([]);
  readonly crise = signal<string | null>(null);
  readonly position = signal<Releve | null>(null);
  readonly positionRefusee = signal(false);
  readonly tournee = signal<Tournee | null>(null);
  readonly tourneeEnCours = signal(false);
  readonly embarquement = signal(false);
  readonly message = signal<string | null>(null);
  readonly enregistrement = signal(false);
  private readonly dernier = signal<string | null>(null);
  private lueA: Releve | null = null;
  private arreterPosition: () => void = () => {};

  // Le formulaire d'évaluation.
  etat: string | null = null;
  dangers = new Set<string>();
  personne = false;
  reloger = false;
  commentaire = '';
  type: string | null = null;
  typeLibre = '';
  description = '';
  readonly photos = signal<File[]>([]);
  private identifiant = crypto.randomUUID();

  readonly suivant = computed(() => prochainPoint(this.tournee()?.points ?? [], this.dernier()));
  readonly typesSansAdresse = computed(() => this.degats.types().filter(t => !t.a_une_adresse || t.nom === 'Autre'));
  readonly resumeSecteur = computed(() => {
    const s = this.degats.secteur();
    if (!s) return null;
    return { genere_le: s.genere_le, adresses: s.adresses.length, biens: s.biens.length, constats: s.constats_faits ?? 0 };
  });

  async ngOnInit(): Promise<void> {
    this.arreterPosition = suivrePosition(r => {
      this.position.set(r);
      this.positionRefusee.set(false);
      // La liste suit la marche : relue quand on s'est déplacé de plus de 20 m.
      if (this.etape().nom === 'tournee' && (!this.lueA || distanceEntre(this.lueA, r) > 20)) this.chargerTournee();
    }, () => this.positionRefusee.set(true));
    await this.degats.restaurer();
    this.degats.chargerTypes();
    try {
      const crises = await firstValueFrom(this.http.get<Crisis[]>(`${environment.apiUrl}/crises/`));
      const ouvertes = crises.filter(c => c.is_open !== false).map(c => ({ id: c.id, nom: c.name }));
      this.horsLigne.garder('degats-crises', ouvertes).catch(() => {});
      this.crises.set(ouvertes);
    } catch {
      this.crises.set((await this.horsLigne.relire<{ id: string; nom: string }[]>('degats-crises'))?.valeur ?? []);
    }
    const secteur = this.degats.secteur();
    this.crise.set(this.crises().length === 1 ? this.crises()[0].id
      : secteur && this.crises().some(c => c.id === secteur.crise) ? secteur.crise : null);
  }

  ngOnDestroy(): void { this.arreterPosition(); }

  async embarquer(): Promise<void> {
    const crise = this.crise(), ici = this.position();
    if (!crise || !ici) return;
    this.embarquement.set(true);
    this.message.set(await this.degats.embarquer(crise, ici));
    this.embarquement.set(false);
  }

  effacerSecteur(): void { this.degats.effacerSecteur(); }

  commencer(): void {
    this.message.set(null);
    this.etape.set({ nom: 'tournee' });
    this.chargerTournee();
  }

  retour(): void {
    const e = this.etape();
    this.etape.set(e.nom === 'tournee' ? { nom: 'accueil' } : { nom: 'tournee' });
  }

  async chargerTournee(): Promise<void> {
    const crise = this.crise(), ici = this.position();
    if (!crise || !ici) return;
    this.lueA = ici;
    this.tourneeEnCours.set(true);
    this.tournee.set(await this.degats.tournee(crise, ici));
    this.tourneeEnCours.set(false);
  }

  cle(p: PointTournee): string { return cleDuPoint(p); }
  libelleEtat(p: PointTournee): string { return libelleEtat(p); }

  ecart(p: PointTournee): number | null {
    const ici = this.position();
    return ici ? Math.round(distanceM(ici.latitude, ici.longitude, p.latitude, p.longitude)) : null;
  }

  choisirPoint(p: PointTournee): void { this.etape.set({ nom: 'position', point: p }); }

  nouveauPoint(): void {
    const ici = this.position();
    this.ouvrirEvaluation(null, ici ? { latitude: ici.latitude, longitude: ici.longitude } : null, false);
  }

  replacer(p: PointTournee): void {
    this.etape.set({ nom: 'replacer', point: p, lieu: { latitude: p.latitude, longitude: p.longitude } });
  }

  deplacer(lieu: { latitude: number; longitude: number }): void {
    const e = this.etape();
    if (e.nom === 'replacer') this.etape.set({ ...e, lieu });
  }

  aMaPosition(): void {
    const ici = this.position();
    if (ici) this.deplacer({ latitude: ici.latitude, longitude: ici.longitude });
  }

  ouvrirEvaluation(point: PointTournee | null, lieu: { latitude: number; longitude: number } | null, replace: boolean): void {
    this.etat = null;
    this.dangers = new Set();
    this.personne = this.reloger = false;
    this.commentaire = this.typeLibre = this.description = '';
    this.type = null;
    this.photos.set([]);
    this.identifiant = crypto.randomUUID();
    this.etape.set({ nom: 'evaluer', point, lieu, replace });
  }

  surTypeLibre(valeur: string): void {
    this.typeLibre = valeur;
    if (valeur.trim()) this.type = null;
  }

  basculerDanger(code: string): void {
    if (this.dangers.has(code)) this.dangers.delete(code); else this.dangers.add(code);
  }

  ajouterPhoto(evenement: Event): void {
    const champ = evenement.target as HTMLInputElement;
    const fichier = champ.files?.[0];
    champ.value = '';
    if (fichier) this.photos.update(p => [...p, fichier]);
  }

  peutEnregistrer(): boolean {
    const e = this.etape();
    if (e.nom !== 'evaluer' || !this.etat || this.enregistrement()) return false;
    if (e.point === null) return e.lieu !== null;
    return !!(e.point.ban_id || e.point.habitation);
  }

  async enregistrer(): Promise<void> {
    const e = this.etape();
    const crise = this.crise();
    if (e.nom !== 'evaluer' || !crise || !this.peutEnregistrer()) return;
    const nouveau = e.point === null;
    const lieu = nouveau || e.replace ? e.lieu : null;
    const constat: Constat = {
      id: this.identifiant, crise, ban_id: e.point?.ban_id ?? null,
      habitation: e.point && !e.point.ban_id ? e.point.habitation ?? null : null,
      latitude: lieu?.latitude ?? null, longitude: lieu?.longitude ?? null,
      position_corrigee: e.replace && !nouveau,
      type_bien: nouveau ? this.type : null, type_bien_libre: this.typeLibre.trim() || null,
      description: this.description.trim() || null, statut_evaluation: this.etat!,
      dangers: [...this.dangers], personne_sur_place: this.personne, a_reloger: this.reloger,
      ouvrir_dossier: this.reloger, commentaire: this.commentaire.trim() || null,
      constate_le: new Date().toISOString(),
    };
    const libelle = `Évaluation : ${e.point?.libelle ?? (this.description.trim() || 'point ajouté')}`;
    this.enregistrement.set(true);
    const illisibles = await this.degats.constater(constat, libelle, this.photos(), this.position());
    this.enregistrement.set(false);
    const enAttente = await this.degats.constatEncoreEnFile(constat.id);
    this.message.set([
      enAttente ? 'Constat gardé sur ce téléphone : il partira dès que le réseau reviendra.' : 'Constat envoyé.',
      illisibles ? `${illisibles} photo(s) illisible(s), non jointe(s).` : '',
    ].filter(Boolean).join(' '));
    this.dernier.set(e.point ? cleDuPoint(e.point) : null);
    this.etape.set({ nom: 'tournee' });
    this.chargerTournee();
  }
}
