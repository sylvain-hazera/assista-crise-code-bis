import { Component, EventEmitter, Input, OnChanges, Output, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { QrCanauxRadioComponent } from '../../../shared/components/common/qr-canaux-radio/qr-canaux-radio.component';

import { TeamService } from '../../../services/team.service';
import { CanalPasserelle, CanauxRadioEquipe, EtatCanalRadio, ProtocoleRadio, Team } from '../../../shared/models/team.model';

type Mode = 'passerelle' | 'notre-cle' | 'cle-generee';

/**
 * Le canal radio de l'équipe (25/11/2026), Meshtastic et MeshCore. Par défaut « AC-<INDICATIF> »,
 * créé avec l'équipe et installé d'office par l'application sur la radio des membres. Une
 * structure qui a déjà ses canaux (ADRASEC…) peut :
 * - reprendre un canal déjà installé sur sa passerelle ;
 * - saisir son nom ET sa clé (la plateforme ne la remplacera jamais) ;
 * - choisir un nom, avec une clé générée.
 * La clé n'est jamais affichée : son origine et une empreinte courte, pour vérifier qu'elle
 * concorde avec celle des radios.
 */
@Component({
  selector: 'app-canal-radio-equipe',
  standalone: true,
  imports: [FormsModule, QrCanauxRadioComponent],
  template: `
    <div class="detail-section">
      <div class="section-header">
        <h3><span class="material-icons">cell_tower</span> Canal radio de l'équipe</h3>
      </div>
      <p class="page-hint">
        Indicatif <strong>&#64;{{ equipe.indicatif || '—' }}</strong>. L'application installe ce canal sur la radio
        de chaque membre ; en crise, la cellule appelle l'équipe par « &#64;{{ equipe.indicatif || 'INDICATIF' }} » sur le canal de la crise.
      </p>
      @for (p of protocoles; track p.code) {
        @let canal = etat(p.code);
        <div class="canal-ligne" [attr.data-protocole]="p.code">
          <div class="canal-titre">
            <span class="material-icons statut-ok">tag</span>
            <strong>{{ p.libelle }}</strong>
            @if (canal) {
              <span class="canal-nom">{{ canal.nom }}</span>
              <span class="pastille" [class.perso]="canal.personnalise">{{ libelleOrigine(canal) }}</span>
            } @else {
              <span class="canal-attente">aucun canal</span>
            }
          </div>
          @if (canal) {
            <div class="canal-detail">
              Clé {{ canal.cle_fournie ? 'fournie par la structure' : 'générée par la plateforme' }}
              @if (canal.empreinte) { · empreinte <code>{{ canal.empreinte }}</code> }
              @if (canal.sur_passerelle) { · installé sur la passerelle }
            </div>
          }
          @if (peutGerer) {
            <div class="canal-actions">
              <button class="btn-secondary sm" type="button" (click)="ouvrir(p.code)" [disabled]="occupe">Personnaliser</button>
              @if (canal?.personnalise) {
                <button class="btn-secondary sm" type="button" (click)="parDefaut(p.code)" [disabled]="occupe">Revenir au canal par défaut</button>
              }
              <button class="btn-secondary sm" type="button" (click)="renvoyer(p.code)" [disabled]="occupe"
                      title="Envoie nom et clé par message radio direct aux membres qui ont déclaré leur nœud">
                Renvoyer les infos par radio
              </button>
              @if (canal && !canal.cle_fournie) {
                <button class="btn-danger sm" type="button" (click)="regenerer(p.code)" [disabled]="occupe"
                        title="Nouvelle clé : un ancien détenteur qui n'est plus membre perd l'accès">Régénérer la clé</button>
              }
            </div>
          }

          @if (edite === p.code) {
            <form class="canal-form" (ngSubmit)="enregistrer()">
              <div class="modes" role="radiogroup" aria-label="Façon de personnaliser">
                @if (passerelle(p.code).length) {
                  <label><input type="radio" name="mode" value="passerelle" [(ngModel)]="mode"> Reprendre un canal de notre passerelle</label>
                }
                <label><input type="radio" name="mode" value="notre-cle" [(ngModel)]="mode"> Notre nom et notre clé</label>
                <label><input type="radio" name="mode" value="cle-generee" [(ngModel)]="mode"> Notre nom, clé générée</label>
              </div>

              @if (mode === 'passerelle') {
                <select name="reprendre" [(ngModel)]="reprendre" aria-label="Canal de la passerelle" required>
                  <option value="">Choisir un canal…</option>
                  @for (c of passerelle(p.code); track c.id) {
                    <option [value]="c.id">{{ c.nom }}{{ c.passerelle ? ' — ' + c.passerelle : '' }}{{ c.public ? ' (public)' : '' }}</option>
                  }
                </select>
                <span class="field-hint">La passerelle et les radios de la structure l'ont déjà : rien à reconfigurer.</span>
              } @else {
                <label class="champ">Nom du canal
                  <input type="text" name="nom" [(ngModel)]="nom" required [attr.maxlength]="p.code === 'MESHTASTIC' ? 11 : 31"
                         [placeholder]="p.code === 'MESHTASTIC' ? 'ADRASEC42' : 'ADRASEC 42'" autocomplete="off"/>
                </label>
                <span class="field-hint">
                  @if (p.code === 'MESHTASTIC') { 11 caractères au plus, sans espace ni accent. }
                  @else { 31 caractères ; « #nom » pour un canal public (sans clé). }
                </span>
                @if (mode === 'notre-cle') {
                  <label class="champ">Clé de chiffrement
                    <input type="password" name="cle" [(ngModel)]="cle" autocomplete="off" spellcheck="false"
                           [placeholder]="p.code === 'MESHTASTIC' ? 'base64, hexadécimal ou lien meshtastic.org/e/#…' : '32 caractères hexadécimaux'"/>
                  </label>
                  <span class="field-hint">Elle est chiffrée sur nos serveurs, n'est plus jamais affichée et n'est donnée qu'aux radios des membres.</span>
                  @if (p.code === 'MESHTASTIC') {
                    <label><input type="checkbox" name="en_clair" [(ngModel)]="enClair"> Canal en clair (clé publique par défaut, lisible par tous)</label>
                  }
                }
              }
              @if (entendusSansCle && mode !== 'cle-generee') {
                <p class="field-hint">{{ entendusSansCle }} canal(aux) entendu(s) par la passerelle sans que nous en ayons la clé :
                  pour l'un d'eux, choisissez « Notre nom et notre clé ».</p>
              }
              <div class="canal-actions">
                <button class="btn-primary sm" type="submit" [disabled]="occupe">Enregistrer</button>
                <button class="btn-secondary sm" type="button" (click)="edite = null">Annuler</button>
              </div>
            </form>
          }
        </div>
      }
      @if (peutGerer && equipe.id) {
        <div class="canal-qr">
          <app-qr-canaux-radio [equipe]="equipe.id" libelle="QR code des canaux d'urgence (crise, équipe, commune)"></app-qr-canaux-radio>
        </div>
      }
      @if (message) { <p class="canal-message" role="status">{{ message }}</p> }
      @if (erreur) { <p class="canal-erreur" role="alert">{{ erreur }}</p> }
    </div>
  `,
  styles: [`
    .canal-ligne { padding: .6rem 0; border-top: 1px solid var(--ac-border, #e5e7eb); }
    .canal-titre { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
    .canal-nom { font-family: ui-monospace, monospace; }
    .pastille { font-size: .75rem; padding: .05rem .5rem; border-radius: 999px; background: var(--ac-surface-2, #eef2f7); }
    .pastille.perso { background: #fef3c7; color: #92400e; }
    .canal-detail { font-size: .85rem; color: var(--ac-text-muted, #6b7280); margin: .2rem 0 .4rem 2rem; }
    .canal-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .4rem; }
    .canal-form { display: grid; gap: .5rem; margin-top: .6rem; padding: .75rem; border-radius: 8px; background: var(--ac-surface-2, #f8fafc); }
    .modes { display: flex; flex-wrap: wrap; gap: .4rem 1rem; }
    .champ { display: grid; gap: .2rem; }
    .canal-qr { margin-top: .6rem; }
    .canal-erreur { color: #b91c1c; }
    .canal-message { color: #15803d; }
  `],
})
export class CanalRadioEquipeComponent implements OnChanges {
  @Input({ required: true }) equipe!: Team;
  @Input() peutGerer = false;
  @Output() modifie = new EventEmitter<{ canaux_radio: CanauxRadioEquipe; indicatif: string }>();

  private readonly teams = inject(TeamService);
  readonly protocoles: { code: ProtocoleRadio; libelle: string }[] = [
    { code: 'MESHTASTIC', libelle: 'Meshtastic' }, { code: 'MESHCORE', libelle: 'MeshCore' },
  ];

  edite: ProtocoleRadio | null = null;
  mode: Mode = 'notre-cle';
  nom = '';
  cle = '';
  enClair = false;
  reprendre = '';
  occupe = false;
  message = '';
  erreur = '';
  entendusSansCle = 0;
  private canauxPasserelle: CanalPasserelle[] = [];
  private passerelleLue = false;

  ngOnChanges(): void {
    this.passerelleLue = false;
    this.canauxPasserelle = [];
  }

  etat(p: ProtocoleRadio): EtatCanalRadio | null {
    return (p === 'MESHTASTIC' ? this.equipe.canaux_radio?.meshtastic : this.equipe.canaux_radio?.meshcore) ?? null;
  }

  libelleOrigine(c: EtatCanalRadio): string {
    if (c.repris) return 'repris de la passerelle';
    return c.personnalise ? 'personnalisé' : 'par défaut';
  }

  passerelle(p: ProtocoleRadio): CanalPasserelle[] {
    return this.canauxPasserelle.filter(c => c.protocole === p && !c.deja_le_notre);
  }

  ouvrir(p: ProtocoleRadio): void {
    this.edite = p;
    this.erreur = this.message = '';
    const actuel = this.etat(p);
    this.nom = actuel?.personnalise ? actuel.nom : '';
    this.cle = '';
    this.enClair = false;
    this.reprendre = '';
    this.mode = 'notre-cle';
    if (!this.passerelleLue && this.equipe.id) {
      this.passerelleLue = true;
      this.teams.canauxPasserelle(this.equipe.id).subscribe({
        next: (r) => {
          this.canauxPasserelle = r.canaux;
          this.entendusSansCle = r.entendus_sans_cle;
          // La reprise d'un canal de la passerelle est proposée en premier quand il en existe.
          if (this.edite && this.passerelle(this.edite).length) this.mode = 'passerelle';
        },
        error: () => { this.canauxPasserelle = []; },
      });
    } else if (this.passerelle(p).length) {
      this.mode = 'passerelle';
    }
  }

  enregistrer(): void {
    if (!this.edite || !this.equipe.id) return;
    const protocole = this.edite;
    const corps = this.mode === 'passerelle'
      ? { protocole, reprendre: this.reprendre }
      : { protocole, nom: this.nom.trim(), ...(this.mode === 'notre-cle' && this.cle.trim() ? { cle: this.cle.trim(), en_clair: this.enClair } : {}) };
    if (this.mode === 'passerelle' && !this.reprendre) { this.erreur = 'Choisissez un canal de la passerelle.'; return; }
    if (this.mode === 'notre-cle' && !this.cle.trim() && !this.nom.trim().startsWith('#')) {
      this.erreur = 'Saisissez la clé de votre canal, ou choisissez « clé générée ».'; return;
    }
    this.occupe = true;
    this.erreur = '';
    this.teams.personnaliserCanalRadio(this.equipe.id, corps).subscribe({
      next: (r) => this.applique(r, 'Canal enregistré : il sera installé sur les radios des membres à leur prochaine connexion.'),
      error: (e) => this.echec(e),
    });
  }

  parDefaut(p: ProtocoleRadio): void {
    if (!this.equipe.id || !confirm('Revenir au canal par défaut ? Un canal repris est rendu à la passerelle de la structure.')) return;
    this.occupe = true;
    this.teams.canalRadioParDefaut(this.equipe.id, p).subscribe({
      next: (r) => this.applique(r, 'Canal par défaut rétabli.'),
      error: (e) => this.echec(e),
    });
  }

  renvoyer(p: ProtocoleRadio): void {
    if (!this.equipe.id) return;
    this.occupe = true;
    const appel = p === 'MESHTASTIC' ? this.teams.provisionnerCanalMeshtastic(this.equipe.id) : this.teams.provisionnerCanalMeshCore(this.equipe.id);
    appel.subscribe({
      next: (r) => {
        this.occupe = false;
        this.message = r.compagnon_disponible
          ? `Infos envoyées à ${r.destinataires} membre(s) qui ont déclaré leur nœud.`
          : 'Aucune radio de passerelle disponible pour les envoyer pour l’instant.';
      },
      error: (e) => this.echec(e),
    });
  }

  regenerer(p: ProtocoleRadio): void {
    if (!this.equipe.id || !confirm("Régénérer la clé ? Un ancien détenteur qui n'est plus membre perd l'accès ; les radios des membres reçoivent la nouvelle clé.")) return;
    this.occupe = true;
    const appel = p === 'MESHTASTIC' ? this.teams.provisionnerCanalMeshtastic(this.equipe.id, true) : this.teams.provisionnerCanalMeshCore(this.equipe.id, true);
    appel.subscribe({
      next: () => { this.occupe = false; this.message = 'Clé régénérée.'; },
      error: (e) => this.echec(e),
    });
  }

  private applique(r: { canaux_radio: CanauxRadioEquipe; indicatif: string }, texte: string): void {
    this.occupe = false;
    this.edite = null;
    this.cle = '';
    this.message = texte;
    this.equipe = { ...this.equipe, canaux_radio: r.canaux_radio, indicatif: r.indicatif };
    this.passerelleLue = false;
    this.modifie.emit(r);
  }

  private echec(e: { error?: { error?: string } }): void {
    this.occupe = false;
    this.erreur = e?.error?.error ?? 'Enregistrement impossible.';
  }
}
