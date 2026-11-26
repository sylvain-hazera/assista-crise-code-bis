import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface InscritPoste {
  id: string; utilisateur: string; nom: string; statut: string; inscrit_le: string; pointe_le: string | null;
}

export interface Poste {
  id: string; intitule: string; debut: string; fin: string; places: number; occupes: number; attente: number;
  remarque: string; mon_statut: string | null; mon_rang_attente: number | null;
  /** Pour le bureau seulement. */
  inscrits?: InscritPoste[];
}

export interface Manifestation {
  id: string; institution: string; institution_nom: string; type: string; type_libelle: string; titre: string;
  lieu: string; organisateur: string; debut: string; fin: string; statut: string; statut_libelle: string;
  places: number; occupes: number; je_suis_inscrit: boolean; organise: boolean;
  consignes?: string; postes?: Poste[]; documents?: { id: string; nom: string }[];
}

interface ListeManifestations {
  manifestations: Manifestation[];
  associations_organisees: { id: string; nom: string }[];
  types: { code: string; libelle: string }[];
}

/** Une manifestation en cours de saisie : champs `datetime-local` (heure du poste). */
interface Brouillon {
  id?: string; institution: string; type: string; titre: string; lieu: string; organisateur: string; consignes: string;
  debut: string; fin: string;
  postes: { intitule: string; debut: string; fin: string; places: number }[];
}

/**
 * Manifestations d'association (26/11/2026, après l'annonce de FCBA 33) : le calendrier des
 * manifestations, des dispositifs de signalisation radio et des exercices, et l'inscription sur
 * leurs postes. Sur un poste complet, on passe en liste d'attente ; une place libérée fait monter
 * le premier.
 *
 * Le bureau de l'association y organise aussi : créer (brouillon), publier (les membres sont
 * prévenus), modifier (les inscrits sont prévenus si l'horaire ou le lieu change), annuler,
 * pointer les présents — ce qui crée leur ligne dans « Mon relevé d'heures ».
 */
@Component({
  selector: 'app-manifestations',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './manifestations.component.html',
  styleUrl: './manifestations.component.scss',
})
export class ManifestationsComponent implements OnInit {
  liste: ListeManifestations | null = null;
  choisie: Manifestation | null = null;
  brouillon: Brouillon | null = null;
  vue: 'a-venir' | 'passees' = 'a-venir';
  erreur = '';
  message = '';
  envoi = false;
  /** Nouveau poste en cours de saisie sur la manifestation ouverte (bureau). */
  nouveauPoste: { intitule: string; debut: string; fin: string; places: number } | null = null;
  motifAnnulation = '';
  annulation = false;

  private readonly url = `${environment.apiUrl}/manifestations/`;

  constructor(private http: HttpClient, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.charger();
    const id = this.route.snapshot.queryParamMap.get('m');
    if (id) this.ouvrir(id);
  }

  charger(): void {
    this.http.get<ListeManifestations>(this.url).subscribe({
      next: (l) => this.liste = l,
      error: (err) => this.erreur = err?.error?.detail || 'Les manifestations n\'ont pas pu être chargées.',
    });
  }

  get affichees(): Manifestation[] {
    const maintenant = Date.now();
    const toutes = this.liste?.manifestations ?? [];
    return this.vue === 'a-venir'
      ? toutes.filter(m => new Date(m.fin).getTime() >= maintenant)
      : toutes.filter(m => new Date(m.fin).getTime() < maintenant).reverse();
  }

  get organise(): boolean { return (this.liste?.associations_organisees.length ?? 0) > 0; }

  /** Un poste ou une manifestation commencés : le bureau peut pointer. */
  commence(debut: string): boolean { return new Date(debut).getTime() <= Date.now(); }

  ouvrir(id: string): void {
    this.erreur = '';
    this.http.get<Manifestation>(`${this.url}${id}/`).subscribe({
      next: (m) => { this.choisie = m; this.brouillon = null; this.nouveauPoste = null; this.annulation = false; },
      error: (err) => this.erreur = err?.error?.detail || 'Manifestation introuvable.',
    });
  }

  private recevoir(m: Manifestation, message = ''): void {
    this.choisie = m;
    this.message = message;
    this.envoi = false;
    this.charger();
  }

  private echec(err: { error?: { detail?: string } }, defaut: string): void {
    this.envoi = false;
    this.erreur = err?.error?.detail || defaut;
  }

  /** ISO du serveur → valeur d'un champ `datetime-local`, à l'heure du poste. */
  enLocal(instant: string | null | undefined): string {
    if (!instant) return '';
    const d = new Date(instant);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  private iso(local: string): string { return new Date(local).toISOString(); }

  // --- Bénévole ---------------------------------------------------------------------------

  inscrire(poste: Poste, geste: 'inscrire' | 'desister'): void {
    this.erreur = '';
    this.envoi = true;
    this.http.post<Manifestation>(`${this.url}postes/${poste.id}/`, { geste }).subscribe({
      next: (m) => {
        const p = m.postes?.find(x => x.id === poste.id);
        this.recevoir(m, geste === 'desister' ? 'Désistement enregistré.'
          : p?.mon_statut === 'LISTE_ATTENTE' ? `Poste complet : vous êtes n° ${p.mon_rang_attente} sur la liste d'attente.`
          : 'Inscription enregistrée.');
      },
      error: (err) => this.echec(err, 'L\'inscription n\'a pas pu être enregistrée.'),
    });
  }

  telechargerCalendrier(): void {
    this.http.get(`${this.url}mon-calendrier.ics`, { responseType: 'blob' }).subscribe({
      next: (ics) => this.enregistrerFichier(ics, 'mes-manifestations.ics'),
      error: () => this.erreur = 'Le calendrier n\'a pas pu être téléchargé.',
    });
  }

  telechargerDocument(doc: { id: string; nom: string }): void {
    if (!this.choisie) return;
    this.http.get(`${this.url}${this.choisie.id}/documents/${doc.id}/`, { responseType: 'blob' }).subscribe({
      next: (f) => this.enregistrerFichier(f, doc.nom),
      error: () => this.erreur = 'Le document n\'a pas pu être téléchargé.',
    });
  }

  private enregistrerFichier(contenu: Blob, nom: string): void {
    const lien = document.createElement('a');
    lien.href = URL.createObjectURL(contenu);
    lien.download = nom;
    lien.click();
    URL.revokeObjectURL(lien.href);
  }

  libelleStatut(statut: string | null): string {
    return ({ INSCRIT: 'inscrit', LISTE_ATTENTE: 'liste d\'attente', PRESENT: 'présent', ABSENT: 'absent', DESISTE: 'désisté' } as Record<string, string>)[statut ?? ''] ?? '';
  }

  // --- Bureau -----------------------------------------------------------------------------

  creer(): void {
    const asso = this.liste?.associations_organisees[0];
    if (!asso) return;
    this.choisie = null;
    this.erreur = '';
    this.brouillon = {
      institution: asso.id, type: 'MANIFESTATION', titre: '', lieu: '', organisateur: '', consignes: '',
      debut: '', fin: '', postes: [{ intitule: '', debut: '', fin: '', places: 1 }],
    };
  }

  modifier(): void {
    const m = this.choisie;
    if (!m) return;
    this.brouillon = {
      id: m.id, institution: m.institution, type: m.type, titre: m.titre, lieu: m.lieu, organisateur: m.organisateur,
      consignes: m.consignes ?? '', debut: this.enLocal(m.debut), fin: this.enLocal(m.fin), postes: [],
    };
  }

  ajouterLignePoste(): void { this.brouillon?.postes.push({ intitule: '', debut: '', fin: '', places: 1 }); }

  enregistrer(): void {
    const b = this.brouillon;
    if (!b) return;
    if (!b.titre.trim() || !b.debut || !b.fin) { this.erreur = 'Indiquez au moins le titre, le début et la fin.'; return; }
    this.erreur = '';
    this.envoi = true;
    const corps: Record<string, unknown> = {
      institution: b.institution, type: b.type, titre: b.titre, lieu: b.lieu, organisateur: b.organisateur,
      consignes: b.consignes, debut: this.iso(b.debut), fin: this.iso(b.fin),
    };
    if (!b.id) {
      // Un poste sans horaire prend ceux de la manifestation.
      corps['postes'] = b.postes.filter(p => p.intitule.trim()).map(p => ({
        intitule: p.intitule, places: p.places,
        ...(p.debut ? { debut: this.iso(p.debut) } : {}), ...(p.fin ? { fin: this.iso(p.fin) } : {}),
      }));
    }
    const envoi = b.id ? this.http.patch<Manifestation>(`${this.url}${b.id}/`, corps) : this.http.post<Manifestation>(this.url, corps);
    envoi.subscribe({
      next: (m) => { this.brouillon = null; this.recevoir(m, b.id ? 'Manifestation modifiée.' : 'Brouillon créé : publiez-le quand il est prêt.'); },
      error: (err) => this.echec(err, 'La manifestation n\'a pas pu être enregistrée.'),
    });
  }

  geste(geste: 'publier' | 'annuler' | 'terminer'): void {
    const m = this.choisie;
    if (!m) return;
    if (geste === 'terminer' && !confirm('Clore cette manifestation ? Plus personne ne pourra s\'y inscrire.')) return;
    this.erreur = '';
    this.envoi = true;
    this.http.post<Manifestation>(`${this.url}${m.id}/geste/`, { geste, motif: this.motifAnnulation }).subscribe({
      next: (r) => {
        this.annulation = false;
        this.motifAnnulation = '';
        this.recevoir(r, { publier: 'Publiée : les membres de l\'association sont prévenus.', annuler: 'Annulée : les inscrits sont prévenus.', terminer: 'Manifestation close.' }[geste]);
      },
      error: (err) => this.echec(err, 'Le geste n\'a pas pu être enregistré.'),
    });
  }

  supprimerBrouillon(): void {
    const m = this.choisie;
    if (!m || !confirm('Supprimer ce brouillon ?')) return;
    this.http.delete(`${this.url}${m.id}/`).subscribe({
      next: () => { this.choisie = null; this.message = 'Brouillon supprimé.'; this.charger(); },
      error: (err) => this.echec(err, 'Suppression impossible.'),
    });
  }

  ouvrirNouveauPoste(): void { this.nouveauPoste = { intitule: '', debut: this.enLocal(this.choisie?.debut), fin: this.enLocal(this.choisie?.fin), places: 1 }; }

  ajouterPoste(): void {
    const m = this.choisie, p = this.nouveauPoste;
    if (!m || !p) return;
    if (!p.intitule.trim()) { this.erreur = 'Donnez un intitulé au poste.'; return; }
    this.erreur = '';
    this.http.post<Manifestation>(`${this.url}${m.id}/postes/`, {
      intitule: p.intitule, places: p.places, debut: this.iso(p.debut), fin: this.iso(p.fin),
    }).subscribe({
      next: (r) => { this.nouveauPoste = null; this.recevoir(r, 'Poste ajouté.'); },
      error: (err) => this.echec(err, 'Le poste n\'a pas pu être ajouté.'),
    });
  }

  retirerPoste(poste: Poste): void {
    if (!confirm(`Retirer le poste « ${poste.intitule} » ?`)) return;
    this.http.delete<Manifestation>(`${this.url}postes/${poste.id}/`).subscribe({
      next: (r) => this.recevoir(r, 'Poste retiré.'),
      error: (err) => this.echec(err, 'Le poste n\'a pas pu être retiré.'),
    });
  }

  pointer(inscrit: InscritPoste, present: boolean): void {
    this.erreur = '';
    this.http.post<Manifestation>(`${this.url}inscriptions/${inscrit.id}/pointer/`, { present }).subscribe({
      next: (r) => this.recevoir(r, present ? `${inscrit.nom} : présent, ses heures sont dans son relevé.` : `${inscrit.nom} : absent.`),
      error: (err) => this.echec(err, 'Le pointage n\'a pas pu être enregistré.'),
    });
  }

  joindre(evenement: Event): void {
    const m = this.choisie;
    const fichier = (evenement.target as HTMLInputElement).files?.[0];
    if (!m || !fichier) return;
    const donnees = new FormData();
    donnees.append('fichier', fichier);
    this.http.post<Manifestation>(`${this.url}${m.id}/documents/`, donnees).subscribe({
      next: (r) => this.recevoir(r, 'Image jointe.'),
      error: (err) => this.echec(err, 'L\'image n\'a pas pu être jointe.'),
    });
  }
}
