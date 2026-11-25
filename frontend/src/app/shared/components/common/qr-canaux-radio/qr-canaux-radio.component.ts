import { Component, Input, OnChanges, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { environment } from '../../../../../environments/environment';

interface ReponseLien {
  meshtastic_lien: string | null;
  meshtastic: (string | { role: string; nom: string })[];
  meshcore: (string | { role: string; nom: string; cle_hex?: string })[];
  qr_svg: string | null;
  avertissement?: string;
}

/**
 * QR code des canaux radio (25/11/2026, conseil d'Olivier F4GLD) : un intervenant qui arrive
 * avec son propre boîtier et l'application Meshtastic officielle le scanne et se retrouve sur
 * les bons canaux, sans effacer les siens (lien en mode « ajouter »). Le QR est fabriqué par
 * notre serveur (aucun service extérieur). `crise` : canaux publics de la crise ; `equipe` :
 * canaux d'urgence de l'équipe (contient sa clé : gestionnaires seulement, côté serveur).
 */
@Component({
  selector: 'app-qr-canaux-radio',
  standalone: true,
  template: `
    @if (!ouvert) {
      <button class="btn-secondary sm" type="button" (click)="afficher()">
        <span class="material-icons">qr_code_2</span> {{ libelle }}
      </button>
    } @else {
      <div class="qr-bloc">
        @if (erreur) { <p class="qr-erreur" role="alert">{{ erreur }}</p> }
        @if (qr) {
          <div class="qr" [innerHTML]="qr" role="img" aria-label="QR code des canaux radio"></div>
          <p class="qr-texte">À scanner avec l'application Meshtastic : canaux {{ noms(donnees?.meshtastic) }}. Elle les ajoute sans effacer les autres.</p>
          @if (equipe) { <p class="qr-alerte">Contient la clé de l'équipe : ne le montrez qu'à ses membres.</p> }
          @if (donnees?.avertissement) { <p class="qr-texte">{{ donnees?.avertissement }}</p> }
          @if (meshcoreAvecCle().length) {
            <p class="qr-texte">MeshCore (à saisir) :
              @for (c of meshcoreAvecCle(); track c.nom) { <code>{{ c.nom }}</code> clé <code>{{ c.cle_hex }}</code> ; }
            </p>
          } @else if (donnees?.meshcore?.length) {
            <p class="qr-texte">MeshCore : canal {{ noms(donnees?.meshcore) }}.</p>
          }
        }
        <button class="btn-secondary sm" type="button" (click)="ouvert = false">Masquer</button>
      </div>
    }
  `,
  styles: [`
    .qr-bloc { display: grid; gap: .4rem; justify-items: start; }
    .qr { width: 220px; height: 220px; background: #fff; padding: 6px; border-radius: 6px; }
    .qr :is(svg) { width: 100%; height: 100%; }
    .qr-texte { font-size: .85rem; margin: 0; }
    .qr-alerte { font-size: .85rem; margin: 0; color: #b91c1c; }
    .qr-erreur { color: #b91c1c; }
    code { font-size: .8rem; word-break: break-all; }
  `],
})
export class QrCanauxRadioComponent implements OnChanges {
  @Input() crise: string | null = null;
  @Input() equipe: string | null = null;
  @Input() libelle = 'QR code des canaux radio';

  private readonly http = inject(HttpClient);
  private readonly sanitizer = inject(DomSanitizer);
  ouvert = false;
  qr: SafeHtml | null = null;
  donnees: ReponseLien | null = null;
  erreur = '';

  ngOnChanges(): void { this.ouvert = false; this.qr = null; this.donnees = null; }

  afficher(): void {
    this.ouvert = true;
    this.erreur = '';
    const url = this.equipe
      ? `${environment.apiUrl}/teams/${this.equipe}/lien-canaux/`
      : `${environment.apiUrl}/radio/lien-crise/?crise=${this.crise}`;
    this.http.get<ReponseLien>(url).subscribe({
      next: (r) => {
        this.donnees = r;
        // SVG fabriqué par notre serveur (qrcode), jamais par une saisie : sûr à insérer.
        this.qr = r.qr_svg ? this.sanitizer.bypassSecurityTrustHtml(r.qr_svg) : null;
        if (!r.qr_svg) this.erreur = 'Aucun canal Meshtastic à partager.';
      },
      error: (e) => { this.erreur = e?.error?.error ?? e?.error?.detail ?? 'QR code indisponible.'; },
    });
  }

  noms(liste?: (string | { nom: string })[]): string {
    return (liste ?? []).map(c => typeof c === 'string' ? c : c.nom).join(', ');
  }

  meshcoreAvecCle(): { nom: string; cle_hex: string }[] {
    return (this.donnees?.meshcore ?? []).filter((c): c is { role: string; nom: string; cle_hex: string } =>
      typeof c !== 'string' && !!c.cle_hex);
  }
}
