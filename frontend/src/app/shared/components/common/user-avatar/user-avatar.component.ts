import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';

/** Affiche la photo de profil d'un utilisateur à partir de `photoUrl` (User.photo_url,
 * une URL de prévisualisation contrôlée type /api/users/<id>/preview/ — jamais un chemin
 * /media/ direct, voir UserSerializer.photo_url). L'endpoint exige une authentification par
 * en-tête, incompatible avec un simple <img src>, donc récupéré en blob ici puis transformé en
 * object URL (même patron que CrisisComponent.loadCrisisPhoto pour Crisis.preview). */
@Component({
  selector: 'app-user-avatar',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (objectUrl) {
      <img [src]="objectUrl" [alt]="alt" class="user-avatar-img">
    } @else {
      <span class="user-avatar-placeholder">{{ initiales }}</span>
    }
  `,
  styles: [`
    :host { display: contents; }
    .user-avatar-img { width: 100%; height: 100%; object-fit: cover; border-radius: 50%; }
    .user-avatar-placeholder {
      display: flex; align-items: center; justify-content: center;
      width: 100%; height: 100%; border-radius: 50%;
      background: #dbe4ec; color: #4a5a68; font-weight: 600; font-size: 0.85em;
    }
  `],
})
export class UserAvatarComponent implements OnChanges, OnDestroy {
  @Input() photoUrl: string | null | undefined = null;
  @Input() alt = 'Avatar';
  @Input() initiales = '';

  objectUrl: string | null = null;

  constructor(private http: HttpClient) {}

  ngOnChanges(changes: SimpleChanges): void {
    if ('photoUrl' in changes) this.load();
  }

  private load(): void {
    this.clear();
    if (!this.photoUrl) return;
    this.http.get(this.photoUrl, { responseType: 'blob' }).subscribe({
      next: (blob) => this.objectUrl = URL.createObjectURL(blob),
      error: () => {},
    });
  }

  private clear(): void {
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
  }

  ngOnDestroy(): void {
    this.clear();
  }
}
