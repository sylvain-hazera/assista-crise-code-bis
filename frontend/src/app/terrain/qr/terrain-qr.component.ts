import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { MaMobilisation, VerificationMobilisationService } from '../../services/verification-mobilisation.service';
import { ScannerMobilisationComponent } from '../../shared/components/common/scanner-mobilisation/scanner-mobilisation.component';
import { creerLecteurQr } from '../../services/lecteur-qr';
import { HorsLigneService } from '../hors-ligne.service';

interface VerrouEcran { release(): Promise<void>; }
type NavigateurAvecVerrou = Navigator & { wakeLock?: { request(type: 'screen'): Promise<VerrouEcran> } };

/**
 * Les QR codes de mobilisation, côté terrain (DOSSIER-PWA-INTERVENANTS.md, lot 5) :
 * - **lire** celui d'une attestation, avec la caméra, y compris sur iPhone (décodeur intégré) ;
 * - **montrer le mien** : l'image est celle de l'attestation PDF, gardée chiffrée sur le
 *   téléphone pour s'afficher sans réseau — c'est celui qui le lit qui a besoin du serveur.
 */
@Component({
  selector: 'app-terrain-qr',
  imports: [DatePipe, ScannerMobilisationComponent],
  template: `
    <h1>QR codes</h1>
    <button type="button" class="principal" (click)="scannerOuvert.set(true)">
      <span class="material-icons" aria-hidden="true">qr_code_scanner</span> Lire un QR code d'attestation
    </button>

    <h2>Mon QR code</h2>
    @if (copieDu()) {
      <p class="copie" role="status">Hors ligne : attestations telles qu'elles étaient le {{ copieDu() | date:'d MMM à HH:mm' }}.</p>
    }
    @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    @if (chargement()) {
      <p class="discret">Chargement…</p>
    } @else if (!montree()) {
      <p class="discret">Aucune demande de mobilisation ne vous est adressée pour l'instant. Quand une institution vous mobilisera, son QR code apparaîtra ici.</p>
    } @else {
      @if (montree(); as m) {
        <figure class="qr">
          <img [src]="'data:image/png;base64,' + m.qr_png" [alt]="'QR code de l\\'attestation ' + m.crise_nom">
          <figcaption>
            <strong [class.revoquee]="m.statut !== 'ACTIVE'">{{ m.statut === 'ACTIVE' ? 'Attestation active' : 'Attestation révoquée' }}</strong>
            <span>{{ m.institution_emettrice_nom }} · {{ m.crise_nom }} · {{ m.type_demande_libelle }}</span>
            @if (m.lieu_texte || m.point_operationnel_nom) { <span>{{ m.point_operationnel_nom || m.lieu_texte }}</span> }
          </figcaption>
        </figure>
        <p class="discret petit">L'écran reste allumé tant que le QR code est affiché. Montez la luminosité si la lecture peine.</p>
      }
      @if (attestations().length > 1) {
        <h3>Mes autres attestations</h3>
        <ul class="autres">
          @for (a of attestations(); track a.id) {
            @if (a.id !== montree()?.id) {
              <li><button type="button" (click)="choisie.set(a.id)">
                {{ a.crise_nom }} · {{ a.type_demande_libelle }}@if (a.statut !== 'ACTIVE') { <span class="revoquee"> (révoquée)</span> }
              </button></li>
            }
          }
        </ul>
      }
    }
    @if (scannerOuvert()) {
      <app-scanner-mobilisation (ferme)="scannerOuvert.set(false)" />
    }
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    h2 { font-size: 1.05rem; margin: 20px 0 8px; }
    h3 { font-size: .95rem; margin: 16px 0 6px; }
    .principal { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; border: 0;
                 border-radius: 10px; padding: 14px; font: inherit; font-weight: 600; cursor: pointer;
                 background: var(--brand-primary, #2563eb); color: #fff; }
    .qr { margin: 0; background: #fff; border-radius: 12px; padding: 12px; border: 1px solid var(--ac-border, #e5e7eb); }
    .qr img { display: block; width: 100%; max-width: 360px; margin: 0 auto; image-rendering: pixelated; }
    figcaption { display: flex; flex-direction: column; align-items: center; gap: 2px; margin-top: 8px; text-align: center;
                 color: #1f2937; font-size: .88rem; }
    figcaption strong { color: #166534; font-size: 1rem; }
    .revoquee, figcaption strong.revoquee { color: #b91c1c; }
    .autres { list-style: none; padding: 0; margin: 0; }
    .autres button { width: 100%; text-align: left; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
                     border-radius: 10px; padding: 12px; margin-bottom: 6px; font: inherit; color: inherit; cursor: pointer; }
    .discret { color: var(--ac-text-muted, #6b7280); font-size: .85rem; margin: 4px 0; }
    .petit { font-size: .78rem; text-align: center; }
    .erreur { color: var(--ac-red-text, #b91c1c); }
    .copie { background: var(--ac-amber-bg, #fef3c7); color: var(--ac-amber-text, #92400e); border-radius: 8px;
             padding: 8px 10px; font-size: .85rem; }
  `],
})
export class TerrainQrComponent implements OnInit, OnDestroy {
  private service = inject(VerificationMobilisationService);
  private horsLigne = inject(HorsLigneService);
  readonly attestations = signal<MaMobilisation[]>([]);
  readonly choisie = signal<string | null>(null);
  readonly montree = computed(() => {
    const liste = this.attestations();
    return liste.find(a => a.id === this.choisie()) ?? liste.find(a => a.statut === 'ACTIVE') ?? liste[0] ?? null;
  });
  readonly scannerOuvert = signal(false);
  readonly copieDu = signal<string | null>(null);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  private verrou: VerrouEcran | null = null;

  async ngOnInit(): Promise<void> {
    // Le décodeur est chargé dès maintenant : il sera là même si le réseau tombe d'ici la lecture.
    creerLecteurQr().catch(() => {});
    try {
      const liste = await firstValueFrom(this.service.mesMobilisations());
      this.horsLigne.garder('mobilisations', liste).catch(() => {});
      this.attestations.set(liste);
    } catch (e) {
      const copie = HorsLigneService.estHorsLigne(e) ? await this.horsLigne.relire<MaMobilisation[]>('mobilisations') : null;
      if (copie) { this.attestations.set(copie.valeur); this.copieDu.set(copie.enregistree_le); }
      else this.erreur.set('Impossible de charger vos attestations. Vérifiez le réseau, puis réessayez.');
    }
    this.chargement.set(false);
    if (this.montree()) this.maintenirEcran();
  }

  ngOnDestroy(): void {
    this.verrou?.release().catch(() => {});
    this.verrou = null;
  }

  private async maintenirEcran(): Promise<void> {
    try {
      this.verrou = (await (navigator as NavigateurAvecVerrou).wakeLock?.request('screen')) ?? null;
    } catch { /* sans écran maintenu : la personne touchera l'écran */ }
  }
}
