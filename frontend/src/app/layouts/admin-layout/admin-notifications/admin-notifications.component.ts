import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { NotificationService } from '../../../services/notification.service';
import { AppNotification, ResumeNotifications } from '../../../shared/models/notification.model';
import { pollWhileVisible } from '../../../shared/utils/polling.util';
import {
  afficherNotificationNavigateur,
  demanderPermissionNotificationNavigateur,
} from '../../../shared/utils/browser-notification.util';

// Polling de la cloche, suspendu quand l'onglet est en arrière-plan (pollWhileVisible).
const INTERVALLE_POLLING_NOTIFICATIONS_MS = 20_000;

/** Cloche de l'en-tête admin : compteur, liste déroulante, notifications navigateur.
 * L'état ouvert/fermé appartient au layout (une seule liste déroulante ouverte à la fois). */
@Component({
  selector: 'app-admin-notifications',
  standalone: true,
  templateUrl: './admin-notifications.component.html',
  styleUrl: './admin-notifications.component.scss',
})
export class AdminNotificationsComponent implements OnInit, OnDestroy {
  @Input() ouvert = false;
  @Output() ouvertChange = new EventEmitter<boolean>();

  notifications: AppNotification[] = [];

  private pollingSub?: Subscription;
  // null avant le premier résumé : pas de notification navigateur au premier chargement.
  private dernierResume: ResumeNotifications | null = null;

  constructor(
    private notificationService: NotificationService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    demanderPermissionNotificationNavigateur();
    this.demarrerPolling();
  }

  ngOnDestroy(): void {
    this.pollingSub?.unsubscribe();
  }

  get nonLues(): number {
    return this.notifications.filter(n => !n.lu).length;
  }

  basculer(): void {
    this.ouvertChange.emit(!this.ouvert);
  }

  fermer(): void {
    this.ouvertChange.emit(false);
  }

  /** Poll léger du résumé (compteur + date) toutes les 20 s, suspendu en arrière-plan ; la liste
   * complète n'est rechargée que si le résumé change. */
  private demarrerPolling(): void {
    this.pollingSub = pollWhileVisible(
      () => this.notificationService.resume(), INTERVALLE_POLLING_NOTIFICATIONS_MS,
    ).subscribe({
      next: (resume) => {
        const changement = !this.dernierResume
          || resume.count_non_lues !== this.dernierResume.count_non_lues
          || resume.derniere_notification_le !== this.dernierResume.derniere_notification_le;
        const nouvellesNotifications = !!this.dernierResume && resume.count_non_lues > this.dernierResume.count_non_lues;
        this.dernierResume = resume;
        if (changement) {
          this.chargerNotifications(nouvellesNotifications && typeof document !== 'undefined' && document.hidden);
        }
      },
      error: () => {},
    });
  }

  /** Notification navigateur seulement s'il y a du nouveau et que l'onglet n'est pas au premier plan. */
  private chargerNotifications(notifierSiArrierePlan = false): void {
    this.notificationService.getAll().subscribe({
      next: (list) => {
        if (notifierSiArrierePlan) {
          const anciensIds = new Set(this.notifications.map(n => n.id));
          for (const n of list) {
            if (!n.lu && !anciensIds.has(n.id)) {
              afficherNotificationNavigateur(n.titre, { body: n.message });
            }
          }
        }
        this.notifications = list;
      },
      error: () => {},
    });
  }

  onNotificationClick(notification: AppNotification): void {
    this.fermer();
    // Une notification liée à une crise ouvre cette crise (?id=).
    if (notification.crise) {
      this.router.navigate(['/admin/crises'], { queryParams: { id: notification.crise } });
    }
    if (notification.lu) return;
    this.notificationService.markAsRead(notification.id).subscribe({
      next: (updated) => {
        const idx = this.notifications.findIndex(n => n.id === updated.id);
        if (idx !== -1) this.notifications[idx] = updated;
      },
    });
  }

  notificationTime(dateStr: string): string {
    const diffMs = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 1) return "à l'instant";
    if (minutes < 60) return `il y a ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `il y a ${hours} h`;
    const days = Math.floor(hours / 24);
    return `il y a ${days} j`;
  }
}
