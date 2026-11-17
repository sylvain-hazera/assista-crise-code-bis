import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { FormulaireTerrainService } from '../../services/formulaire-terrain.service';
import {
  FormulaireTerrain, QuestionTerrain, ReponseTerrain, TypeQuestion, ValeurReponse,
} from '../../shared/models/formulaire-terrain.model';

type Vue = 'liste' | 'composer' | 'repondre' | 'reponses';

/**
 * Formulaires de terrain : composer un questionnaire, le remplir sur place — même sans réseau —
 * et relire les réponses (17/11/2026).
 *
 * Réservé aux collectivités, qui composent et relisent, et aux institutions à qui elles ont
 * délégué une compétence, qui répondent. C'est le serveur qui décide de qui voit quoi : cet
 * écran ne fait que suivre `peut_composer` et `peut_gerer`.
 */
@Component({
  selector: 'app-formulaires-terrain',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './formulaires-terrain.component.html',
  styleUrl: './formulaires-terrain.component.scss',
})
export class FormulairesTerrainComponent implements OnInit, OnDestroy {
  vue: Vue = 'liste';
  formulaires: FormulaireTerrain[] = [];
  types: { code: string; libelle: string }[] = [];
  peutComposer = false;
  chargement = true;
  erreur = '';
  message = '';
  enAttente = 0;

  /** Le questionnaire en cours de composition, de saisie ou de relecture. */
  courant: FormulaireTerrain | null = null;
  brouillon: { id?: string; titre: string; description: string; questions: QuestionTerrain[] } | null = null;
  saisie: Record<string, ValeurReponse> = {};
  position: { latitude: number; longitude: number } | null = null;
  positionEnCours = false;
  reponses: ReponseTerrain[] = [];
  envoi = false;

  private readonly auRetourDuReseau = () => this.viderLaFile();

  constructor(private service: FormulaireTerrainService) {}

  ngOnInit(): void {
    this.service.types().subscribe({
      next: (r) => { this.types = r.types; this.peutComposer = r.peut_composer; },
      error: () => {},
    });
    this.charger();
    this.viderLaFile();
    window.addEventListener('online', this.auRetourDuReseau);
  }

  ngOnDestroy(): void {
    window.removeEventListener('online', this.auRetourDuReseau);
  }

  charger(): void {
    this.chargement = true;
    this.service.liste().subscribe({
      next: (liste) => { this.formulaires = liste; this.chargement = false; },
      error: () => {
        this.chargement = false;
        this.erreur = "Les questionnaires n'ont pas pu être chargés (pas de réseau ?).";
      },
    });
  }

  async viderLaFile(): Promise<void> {
    const parties = await this.service.viderLaFile();
    this.enAttente = await this.service.enAttente();
    if (parties) {
      this.message = `${parties} réponse${parties > 1 ? 's' : ''} en attente ${parties > 1 ? 'ont' : 'a'} été envoyée${parties > 1 ? 's' : ''}.`;
      this.charger();
    }
  }

  retour(): void {
    this.vue = 'liste';
    this.courant = null;
    this.brouillon = null;
    this.erreur = '';
  }

  // ── Composer ────────────────────────────────────────────────────────────────────────────
  composer(formulaire?: FormulaireTerrain): void {
    this.message = '';
    this.erreur = '';
    this.brouillon = formulaire
      ? { id: formulaire.id, titre: formulaire.titre, description: formulaire.description,
          questions: formulaire.questions.map(q => ({ ...q, options: [...(q.options ?? [])] })) }
      : { titre: '', description: '', questions: [this.questionVide()] };
    this.vue = 'composer';
  }

  private questionVide(): QuestionTerrain {
    return { libelle: '', type: 'TEXTE', obligatoire: false };
  }

  ajouterQuestion(): void { this.brouillon?.questions.push(this.questionVide()); }

  retirerQuestion(rang: number): void { this.brouillon?.questions.splice(rang, 1); }

  monter(rang: number): void {
    const q = this.brouillon?.questions;
    if (!q || rang === 0) return;
    [q[rang - 1], q[rang]] = [q[rang], q[rang - 1]];
  }

  aDesChoix(type: TypeQuestion): boolean { return type === 'CHOIX' || type === 'CHOIX_MULTIPLE'; }

  optionsEnTexte(question: QuestionTerrain): string { return (question.options ?? []).join('\n'); }

  lireOptions(question: QuestionTerrain, texte: string): void {
    question.options = texte.split('\n').map(o => o.trim()).filter(o => !!o);
  }

  /** Une condition ne peut porter que sur une question oui/non ou à choix unique placée
   * AVANT, et déjà enregistrée (elle a donc sa clé). */
  conditionsPossibles(rang: number): QuestionTerrain[] {
    return (this.brouillon?.questions ?? []).slice(0, rang)
      .filter(q => !!q.cle && (q.type === 'OUI_NON' || q.type === 'CHOIX'));
  }

  valeursPossibles(cle: string): { valeur: unknown; libelle: string }[] {
    const source = this.brouillon?.questions.find(q => q.cle === cle);
    if (!source) return [];
    if (source.type === 'OUI_NON') return [{ valeur: true, libelle: 'oui' }, { valeur: false, libelle: 'non' }];
    return (source.options ?? []).map(o => ({ valeur: o, libelle: o }));
  }

  choisirCondition(question: QuestionTerrain, cle: string): void {
    question.si = cle ? { cle, valeur: this.valeursPossibles(cle)[0]?.valeur } : null;
  }

  enregistrer(): void {
    if (!this.brouillon) return;
    this.envoi = true;
    this.erreur = '';
    this.service.enregistrer(this.brouillon).subscribe({
      next: (f) => {
        this.envoi = false;
        this.message = `Questionnaire « ${f.titre} » enregistré.`;
        this.retour();
        this.charger();
      },
      error: (err) => { this.envoi = false; this.erreur = this.lisible(err, "Le questionnaire n'a pas pu être enregistré."); },
    });
  }

  basculerOuverture(formulaire: FormulaireTerrain): void {
    this.service.enregistrer({ id: formulaire.id, actif: !formulaire.actif }).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = this.lisible(err, 'Modification impossible.'),
    });
  }

  supprimer(formulaire: FormulaireTerrain): void {
    if (!confirm(`Supprimer le questionnaire « ${formulaire.titre} » ?`)) return;
    this.service.supprimer(formulaire.id).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = this.lisible(err, 'Suppression impossible.'),
    });
  }

  // ── Répondre ────────────────────────────────────────────────────────────────────────────
  ouvrirSaisie(formulaire: FormulaireTerrain): void {
    this.courant = formulaire;
    this.saisie = {};
    this.position = null;
    this.message = '';
    this.erreur = '';
    this.vue = 'repondre';
  }

  /** Même règle que le serveur : une question conditionnelle ne se pose que si sa condition
   * est remplie. */
  estPosee(question: QuestionTerrain): boolean {
    if (!question.si) return true;
    const valeur = this.saisie[question.si.cle];
    return Array.isArray(valeur) ? valeur.includes(question.si.valeur as string) : valeur === question.si.valeur;
  }

  estCoche(cle: string, option: string): boolean {
    const valeur = this.saisie[cle];
    return Array.isArray(valeur) && valeur.includes(option);
  }

  cocher(cle: string, option: string): void {
    const actuelle = Array.isArray(this.saisie[cle]) ? [...(this.saisie[cle] as string[])] : [];
    const rang = actuelle.indexOf(option);
    if (rang === -1) actuelle.push(option); else actuelle.splice(rang, 1);
    this.saisie[cle] = actuelle;
  }

  relevePosition(): void {
    if (!navigator.geolocation) { this.erreur = "Cet appareil ne donne pas sa position."; return; }
    this.positionEnCours = true;
    navigator.geolocation.getCurrentPosition(
      (p) => { this.position = { latitude: p.coords.latitude, longitude: p.coords.longitude }; this.positionEnCours = false; },
      () => { this.positionEnCours = false; this.erreur = "La position n'a pas pu être relevée."; },
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  /** Ce qui part : seulement les questions posées, sans les réponses laissées vides. */
  private donneesAEnvoyer(): Record<string, ValeurReponse> {
    const donnees: Record<string, ValeurReponse> = {};
    for (const question of this.courant?.questions ?? []) {
      const valeur = this.saisie[question.cle!];
      const vide = valeur === undefined || valeur === null || valeur === '' || (Array.isArray(valeur) && !valeur.length);
      if (this.estPosee(question) && !vide) donnees[question.cle!] = valeur;
    }
    return donnees;
  }

  async envoyerReponse(): Promise<void> {
    if (!this.courant || this.envoi) return;
    this.envoi = true;
    this.erreur = '';
    try {
      const issue = await this.service.repondre({
        formulaire: this.courant.id,
        identifiant_client: crypto.randomUUID(),
        donnees: this.donneesAEnvoyer(),
        saisie_le: new Date().toISOString(),
        latitude: this.position?.latitude ?? null,
        longitude: this.position?.longitude ?? null,
      });
      this.message = issue === 'envoyee'
        ? 'Réponse enregistrée. Vous pouvez saisir la suivante.'
        : "Pas de réseau : la réponse est gardée sur cet appareil et partira dès qu'il reviendra.";
      this.saisie = {};
      this.position = null;
      this.enAttente = await this.service.enAttente();
    } catch (err) {
      this.erreur = this.lisible(err, "La réponse n'a pas pu être enregistrée.");
    }
    this.envoi = false;
  }

  // ── Relire ──────────────────────────────────────────────────────────────────────────────
  ouvrirReponses(formulaire: FormulaireTerrain): void {
    this.courant = formulaire;
    this.reponses = [];
    this.vue = 'reponses';
    this.service.reponses(formulaire.id).subscribe({
      next: (r) => this.reponses = r,
      error: (err) => this.erreur = this.lisible(err, "Les réponses n'ont pas pu être chargées."),
    });
  }

  enTexte(valeur: ValeurReponse | undefined): string {
    if (valeur === undefined || valeur === null) return '';
    if (typeof valeur === 'boolean') return valeur ? 'oui' : 'non';
    return Array.isArray(valeur) ? valeur.join(' ; ') : String(valeur);
  }

  exporter(type: 'csv' | 'geojson'): void {
    if (!this.courant) return;
    this.service.exporter(this.courant.id, type).subscribe({
      next: (fichier) => {
        const lien = document.createElement('a');
        lien.href = URL.createObjectURL(fichier);
        lien.download = `reponses.${type}`;
        lien.click();
        URL.revokeObjectURL(lien.href);
      },
      error: (err) => this.erreur = this.lisible(err, "L'export n'a pas pu être produit."),
    });
  }

  private lisible(err: any, defaut: string): string {
    const corps = err?.error;
    if (typeof corps?.detail === 'string') return corps.detail;
    if (Array.isArray(corps?.questions)) return corps.questions[0];
    if (typeof corps?.questions === 'string') return corps.questions;
    if (Array.isArray(corps?.titre)) return 'Le titre est obligatoire.';
    return defaut;
  }
}
