import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../environments/environment';
import { DepartRetourComponent } from '../../shared/components/common/depart-retour/depart-retour.component';

export interface LigneReleve {
  id: string;
  crise: string | null;
  /** Le nom de l'activité : la crise, ou la manifestation (nom gardé pour les écrans existants). */
  crise_nom: string;
  /** Manifestation d'association (26/11/2026), à la place d'une crise. */
  manifestation?: string | null;
  /** Kilomètres aller-retour, en texte (« 42.5 »), vide sans déplacement. */
  kilometres?: string;
  vehicule?: string;
  /** DECLARE ou PLANNING (née du pointage d'une manifestation par le bureau). */
  source?: string;
  equipe: string | null;
  equipe_nom: string;
  parti_le: string;
  rentre_le: string | null;
  depart_de: string;
  retour_a: string;
  hebergement: string;
  /** Complétée ou corrigée à la main, après coup. */
  saisie_manuelle: boolean;
  heures: number | null;
  /** Validée par l'encadrement : elle ne se modifie plus. */
  validee: boolean;
  /** Ce que l'encadrement demande de revoir. */
  remarque_chef: string;
  // Relevé kilométrique (28/11/2026).
  vehicule_personnel?: string | null;
  vehicule_designation?: string;
  lieu_depart?: string;
  lieu_arrivee?: string;
  motif?: string;
  aller_retour?: boolean;
  compteur_depart?: string;
  compteur_arrivee?: string;
  frais?: FraisLigne[];
}

/** Un péage ou un stationnement d'un déplacement, avec ou sans ticket. */
export interface FraisLigne {
  id: string;
  nature: 'PEAGE' | 'STATIONNEMENT' | 'AUTRE';
  nature_libelle: string;
  montant: string;
  justificatif: boolean;
  justificatif_nom: string;
}

/** Un véhicule que la personne a déclaré pour son relevé kilométrique. */
export interface VehiculePersonnel {
  id: string;
  genre: 'VOITURE' | 'DEUX_ROUES';
  libelle: string;
  immatriculation: string;
  puissance_cv: number | null;
  designation: string;
}

/** « Domicile → Floirac (A/R) », vide si rien n'est dit. */
export function trajetDe(l: LigneReleve): string {
  if (!l.lieu_depart && !l.lieu_arrivee) return '';
  return `${l.lieu_depart || '?'} → ${l.lieu_arrivee || '?'}${l.aller_retour === false ? '' : ' (A/R)'}`;
}

/** Kilomètres d'après les compteurs, ou null s'ils ne sont pas tous deux saisis (ou incohérents). */
export function kmDesCompteurs(depart: string, arrivee: string): number | null {
  const d = Number(String(depart ?? '').replace(/\s/g, ''));
  const a = Number(String(arrivee ?? '').replace(/\s/g, ''));
  if (!String(depart ?? '').trim() || !String(arrivee ?? '').trim() || !Number.isInteger(d) || !Number.isInteger(a) || a < d) return null;
  return a - d;
}

/** Le relevé d'une personne, tel que son chef d'équipe le relit. */
export interface FicheEquipe {
  personne: string;
  lignes: LigneReleve[];
  total_heures: number;
  heures_validees: number;
  a_valider: number;
}

export interface Releve {
  du: string;
  au: string;
  lignes: LigneReleve[];
  total_heures: number;
  activite: { quand: string; heure: boolean; source: 'moi' | 'equipe'; equipe: string; quoi: string }[];
  crises: { id: string; nom: string }[];
  equipes: { id: string; nom: string }[];
  lieux: { code: string; libelle: string }[];
  /** La personne encadre au moins une équipe : elle relit et valide les relevés des siens. */
  encadre: boolean;
  total_kilometres?: number;
  manifestations?: { id: string; nom: string; debut: string }[];
  vehicules?: { code: string; libelle: string }[];
  mes_vehicules?: VehiculePersonnel[];
  /** Frais de l'année, par association, et renonciation au remboursement (reçu fiscal). */
  frais?: FraisAssociation[];
}

export interface FraisAssociation {
  institution: string;
  nom: string;
  annee: number;
  recus_fiscaux: boolean;
  kilometres: number;
  montant: string;
  frais_km?: string;
  peages?: string;
  stationnement?: string;
  abandon: { id: string; statut: string; statut_libelle: string; numero_recu: string; motif_refus: string; montant: string | null } | null;
}

/** Une ligne en cours de saisie : les champs d'un tableur, en texte local (`AAAA-MM-JJTHH:MM`). */
interface Brouillon {
  id?: string;
  /** « c:<id> » (crise) ou « m:<id> » (manifestation). */
  activite: string;
  kilometres: string;
  vehicule: string;
  equipe: string;
  parti_le: string;
  rentre_le: string;
  depart_de: string;
  retour_a: string;
  vehicule_personnel: string;
  lieu_depart: string;
  lieu_arrivee: string;
  motif: string;
  aller_retour: boolean;
  compteur_depart: string;
  compteur_arrivee: string;
}

interface NouveauVehicule { genre: 'VOITURE' | 'DEUX_ROUES'; libelle: string; immatriculation: string; puissance_cv: string }

/**
 * Mon relevé d'heures (17/11/2026) : ce que j'ai déclaré par « je pars » / « je rentre », et de
 * quoi compléter mes oublis à la main, dans un tableau.
 *
 * À côté, mon activité et celle de mes équipes sur la même période : c'est en relisant « le
 * dossier a été pris en charge à 14 h 10 » qu'on retrouve l'heure à laquelle on est parti.
 *
 * Une ligne complétée ou corrigée à la main est marquée comme telle, ici et dans le relevé que
 * lit l'institution : on ne fait pas passer une correction pour une déclaration du moment.
 */
@Component({
  selector: 'app-mon-releve',
  standalone: true,
  imports: [CommonModule, FormsModule, DepartRetourComponent],
  templateUrl: './mon-releve.component.html',
  styleUrl: './mon-releve.component.scss',
})
export class MonReleveComponent implements OnInit {
  releve: Releve | null = null;
  du = '';
  au = '';
  erreur = '';
  message = '';
  envoi = false;
  /** La ligne en cours d'édition : une nouvelle (sans `id`) ou une existante. */
  brouillon: Brouillon | null = null;
  filtreActivite: 'tout' | 'moi' | 'equipe' = 'tout';
  /** « mes heures », ou — pour qui encadre une équipe — « les heures de mon équipe ». */
  onglet: 'moi' | 'equipe' = 'moi';
  fiches: FicheEquipe[] = [];
  /** La ligne qu'on renvoie à son auteur, et ce qu'on lui demande de revoir. */
  aRenvoyer: LigneReleve | null = null;
  remarque = '';
  /** Renonciation au remboursement en cours de saisie : l'association, et l'adresse du reçu. */
  renonciation: FraisAssociation | null = null;
  adresse = '';
  /** Véhicule en cours de déclaration (relevé kilométrique). */
  nouveauVehicule: NouveauVehicule | null = null;
  /** Péage ou stationnement en cours d'ajout sur la ligne éditée. */
  fraisNature: 'PEAGE' | 'STATIONNEMENT' | 'AUTRE' = 'PEAGE';
  fraisMontant = '';
  fraisFichier: File | null = null;
  readonly trajet = trajetDe;

  private readonly url = `${environment.apiUrl}/mon-releve/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  ouvrir(onglet: 'moi' | 'equipe'): void {
    this.onglet = onglet;
    this.erreur = '';
    this.message = '';
    if (onglet === 'equipe') this.chargerEquipe(); else this.charger();
  }

  private periode(): Record<string, string> {
    const params: Record<string, string> = {};
    if (this.du) params['du'] = this.du;
    if (this.au) params['au'] = this.au;
    return params;
  }

  chargerEquipe(): void {
    this.http.get<{ fiches: FicheEquipe[] }>(`${environment.apiUrl}/releves-equipe/`, { params: this.periode() }).subscribe({
      next: (r) => this.fiches = r.fiches,
      error: () => this.erreur = "Les relevés de l'équipe n'ont pas pu être chargés.",
    });
  }

  get aValider(): number { return this.fiches.reduce((n, f) => n + f.a_valider, 0); }

  /** Le chef valide ou renvoie ; il ne corrige pas : seule la personne complète son relevé. */
  relire(ligne: LigneReleve, geste: 'valider' | 'renvoyer'): void {
    if (geste === 'renvoyer' && !this.remarque.trim()) { this.erreur = 'Dites ce qui est à revoir.'; return; }
    this.erreur = '';
    this.http.post(`${environment.apiUrl}/releves-equipe/`, { ligne: ligne.id, geste, remarque: this.remarque.trim() }).subscribe({
      next: () => { this.aRenvoyer = null; this.remarque = ''; this.chargerEquipe(); },
      error: (err) => this.erreur = err?.error?.detail || "La relecture n'a pas pu être enregistrée.",
    });
  }

  rechargerPeriode(): void {
    if (this.onglet === 'equipe') this.chargerEquipe(); else this.charger();
  }

  charger(): void {
    const params: Record<string, string> = {};
    if (this.du) params['du'] = this.du;
    if (this.au) params['au'] = this.au;
    this.http.get<Releve>(this.url, { params }).subscribe({
      next: (releve) => { this.releve = releve; this.du = releve.du; this.au = releve.au; },
      error: (err) => this.erreur = err?.error?.detail || "Le relevé n'a pas pu être chargé.",
    });
  }

  get activite(): Releve['activite'] {
    const toute = this.releve?.activite ?? [];
    return this.filtreActivite === 'tout' ? toute : toute.filter(a => a.source === this.filtreActivite);
  }

  libelleLieu(code: string): string {
    return this.releve?.lieux.find(l => l.code === code)?.libelle.split(' (')[0] ?? '';
  }

  /** ISO du serveur → valeur d'un champ `datetime-local`, à l'heure du poste. */
  enLocal(instant: string | null): string {
    if (!instant) return '';
    const d = new Date(instant);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  ajouter(): void {
    const releve = this.releve;
    if (!releve) return;
    this.erreur = '';
    const premiere = releve.crises[0] ? `c:${releve.crises[0].id}` : (releve.manifestations?.[0] ? `m:${releve.manifestations[0].id}` : '');
    this.brouillon = {
      activite: premiere, equipe: releve.equipes.length === 1 ? releve.equipes[0].id : '',
      parti_le: '', rentre_le: '', depart_de: 'DOMICILE', retour_a: 'DOMICILE', kilometres: '', vehicule: 'AUCUN',
      ...this.deplacementVide(),
    };
  }

  private deplacementVide() {
    const seul = this.releve?.mes_vehicules?.length === 1 ? this.releve.mes_vehicules[0].id : '';
    return { vehicule_personnel: seul, lieu_depart: '', lieu_arrivee: '', motif: '', aller_retour: true,
             compteur_depart: '', compteur_arrivee: '' };
  }

  modifier(ligne: LigneReleve): void {
    this.erreur = '';
    this.brouillon = {
      id: ligne.id, activite: ligne.manifestation ? `m:${ligne.manifestation}` : `c:${ligne.crise}`, equipe: ligne.equipe ?? '',
      parti_le: this.enLocal(ligne.parti_le), rentre_le: this.enLocal(ligne.rentre_le),
      depart_de: ligne.depart_de, retour_a: ligne.retour_a || ligne.depart_de,
      kilometres: ligne.kilometres ?? '', vehicule: ligne.vehicule || 'AUCUN',
      vehicule_personnel: ligne.vehicule_personnel ?? '', lieu_depart: ligne.lieu_depart ?? '',
      lieu_arrivee: ligne.lieu_arrivee ?? '', motif: ligne.motif ?? '', aller_retour: ligne.aller_retour !== false,
      compteur_depart: ligne.compteur_depart ?? '', compteur_arrivee: ligne.compteur_arrivee ?? '',
    };
    this.fraisMontant = ''; this.fraisFichier = null;
  }

  /** La ligne en cours d'édition, telle que le serveur l'a renvoyée (pour ses frais). */
  get ligneEditee(): LigneReleve | undefined {
    return this.brouillon?.id ? this.releve?.lignes.find(l => l.id === this.brouillon?.id) : undefined;
  }

  /** Les deux compteurs saisis font les kilomètres : le champ km est alors calculé. */
  kmCompteurs(b: Brouillon): number | null { return kmDesCompteurs(b.compteur_depart, b.compteur_arrivee); }

  choisirVehicule(b: Brouillon): void {
    const v = this.releve?.mes_vehicules?.find(x => x.id === b.vehicule_personnel);
    if (v) b.vehicule = v.genre;
  }

  /** Reprend l'heure d'une ligne d'activité dans le champ encore vide de la ligne en cours. */
  reprendre(instant: string): void {
    if (!this.brouillon) return;
    const local = this.enLocal(instant);
    if (!this.brouillon.parti_le) this.brouillon.parti_le = local;
    else this.brouillon.rentre_le = local;
  }

  enregistrer(): void {
    const b = this.brouillon;
    if (!b) return;
    if (!b.parti_le || !b.rentre_le) { this.erreur = 'Indiquez le départ et le retour.'; return; }
    this.envoi = true;
    this.erreur = '';
    const [genre, id] = b.activite.split(':');
    const corps = {
      crise: genre === 'c' ? id : null, manifestation: genre === 'm' ? id : null,
      equipe: genre === 'c' ? (b.equipe || null) : null, depart_de: b.depart_de, retour_a: b.retour_a,
      kilometres: this.kmCompteurs(b) !== null ? String(this.kmCompteurs(b)) : b.kilometres, vehicule: b.vehicule,
      vehicule_personnel: b.vehicule_personnel || '', lieu_depart: b.lieu_depart, lieu_arrivee: b.lieu_arrivee,
      motif: b.motif, aller_retour: b.aller_retour, compteur_depart: b.compteur_depart, compteur_arrivee: b.compteur_arrivee,
      // Le navigateur convertit l'heure du poste en instant universel : le serveur n'a pas à
      // deviner le fuseau de la personne.
      parti_le: new Date(b.parti_le).toISOString(), rentre_le: new Date(b.rentre_le).toISOString(),
    };
    const envoi = b.id ? this.http.patch(`${this.url}${b.id}/`, corps) : this.http.post(this.url, corps);
    envoi.subscribe({
      next: () => { this.envoi = false; this.brouillon = null; this.message = 'Relevé mis à jour.'; this.charger(); },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.detail || "La ligne n'a pas pu être enregistrée."; },
    });
  }

  get peutAjouter(): boolean {
    return !!this.releve && (this.releve.crises.length > 0 || (this.releve.manifestations?.length ?? 0) > 0);
  }

  libelleVehicule(code?: string): string {
    return code && code !== 'AUCUN' ? (this.releve?.vehicules?.find(v => v.code === code)?.libelle ?? '') : '';
  }

  /** Je renonce au remboursement de mes frais validés de l'année : c'est un don, avec reçu fiscal. */
  renoncer(): void {
    const f = this.renonciation;
    if (!f) return;
    if (!this.adresse.trim()) { this.erreur = 'Indiquez votre adresse : elle figure sur le reçu fiscal.'; return; }
    this.erreur = '';
    this.http.post(`${environment.apiUrl}/mon-releve/abandon/`, { institution: f.institution, annee: f.annee, adresse: this.adresse.trim() }).subscribe({
      next: () => { this.renonciation = null; this.adresse = ''; this.message = 'Demande envoyée au bureau de votre association.'; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || "La demande n'a pas pu être envoyée.",
    });
  }

  telechargerRecu(f: FraisAssociation): void {
    if (!f.abandon) return;
    this.http.get(`${environment.apiUrl}/benevolat/abandons/${f.abandon.id}/recu/`, { responseType: 'blob' }).subscribe({
      next: (pdf) => {
        const lien = document.createElement('a');
        lien.href = URL.createObjectURL(pdf);
        lien.download = `recu-${f.abandon?.numero_recu}.pdf`;
        lien.click();
        URL.revokeObjectURL(lien.href);
      },
      error: () => this.erreur = "Le reçu n'a pas pu être téléchargé.",
    });
  }

  // ── Mes véhicules ────────────────────────────────────────────────────────────────────────

  declarerVehicule(): void {
    this.nouveauVehicule = { genre: 'VOITURE', libelle: '', immatriculation: '', puissance_cv: '' };
  }

  enregistrerVehicule(): void {
    const v = this.nouveauVehicule;
    if (!v) return;
    this.erreur = '';
    this.http.post<VehiculePersonnel>(`${environment.apiUrl}/mes-vehicules/`, v).subscribe({
      next: () => { this.nouveauVehicule = null; this.message = 'Véhicule enregistré.'; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || "Le véhicule n'a pas pu être enregistré.",
    });
  }

  retirerVehicule(v: VehiculePersonnel): void {
    if (!confirm(`Retirer « ${v.designation} » ? Il reste sur vos déplacements passés.`)) return;
    this.http.delete(`${environment.apiUrl}/mes-vehicules/${v.id}/`).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = err?.error?.detail || 'Retrait impossible.',
    });
  }

  // ── Péages et stationnement ──────────────────────────────────────────────────────────────

  choisirTicket(evenement: Event): void {
    this.fraisFichier = (evenement.target as HTMLInputElement).files?.[0] ?? null;
  }

  ajouterFrais(ligne: LigneReleve): void {
    // « Autre justificatif » (28/11/2026) : une photo sans montant, le tableau de bord par exemple.
    if (this.fraisNature === 'AUTRE' && !this.fraisFichier) { this.erreur = 'Joignez la photo ou le document.'; return; }
    if (this.fraisNature !== 'AUTRE' && !this.fraisMontant.trim()) { this.erreur = 'Indiquez le montant payé.'; return; }
    const corps = new FormData();
    corps.append('nature', this.fraisNature);
    if (this.fraisNature !== 'AUTRE') corps.append('montant', this.fraisMontant.trim());
    if (this.fraisFichier) corps.append('fichier', this.fraisFichier);
    this.erreur = '';
    this.http.post(`${this.url}${ligne.id}/frais/`, corps).subscribe({
      next: () => { this.fraisMontant = ''; this.fraisFichier = null; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || "Le frais n'a pas pu être ajouté.",
    });
  }

  retirerFrais(ligne: LigneReleve, f: FraisLigne): void {
    this.http.delete(`${this.url}${ligne.id}/frais/${f.id}/`).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = err?.error?.detail || 'Retrait impossible.',
    });
  }

  totalFrais(l: LigneReleve): number {
    return (l.frais ?? []).filter(f => f.nature !== 'AUTRE').reduce((t, f) => t + Number(f.montant || 0), 0);
  }

  ouvrirTicket(f: FraisLigne): void {
    this.telecharger(`${environment.apiUrl}/frais-deplacement/${f.id}/justificatif/`, f.justificatif_nom || 'ticket',
      "Le ticket n'a pas pu être ouvert.");
  }

  /** Mon relevé kilométrique imprimable, pour la période affichée. */
  telechargerReleveKm(f: FraisAssociation): void {
    const params = new URLSearchParams({ institution: f.institution, ...this.periode() });
    this.telecharger(`${environment.apiUrl}/mon-releve/kilometrique/?${params}`, `releve-km-${this.du}-${this.au}.pdf`,
      "Le relevé kilométrique n'a pas pu être téléchargé.");
  }

  private telecharger(url: string, nom: string, echec: string): void {
    this.http.get(url, { responseType: 'blob' }).subscribe({
      next: (fichier) => {
        const lien = document.createElement('a');
        lien.href = URL.createObjectURL(fichier);
        lien.download = nom;
        lien.click();
        URL.revokeObjectURL(lien.href);
      },
      error: () => this.erreur = echec,
    });
  }

  supprimer(ligne: LigneReleve): void {
    if (!confirm('Retirer cette ligne de votre relevé ?')) return;
    this.http.delete(`${this.url}${ligne.id}/`).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = err?.error?.detail || 'Suppression impossible.',
    });
  }
}
