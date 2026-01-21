import { Component } from '@angular/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-footer',
  templateUrl: './footer.component.html',
  styleUrls: ['./footer.component.scss'],
  imports: [
    RouterModule
  ]
})
export class FooterComponent {
  currentYear = new Date().getFullYear();

  partners = [
    { icon: '🏛️', name: 'Ministère', link: '#' },
    { icon: '🏠', name: 'Préfecture', link: '#' },
    { icon: '👥', name: 'Commune', link: '#' },
    { icon: 'ℹ️', name: 'Information', link: '#' },
    { icon: '🆘', name: 'Urgences', link: '#' }
  ];

  openEmail(type: 'contact' | 'support'): void {
    const emails = {
      contact: 'contact@assistacrise.fr',
      support: 'support@assistacrise.fr'
    };
    window.location.href = `mailto:${emails[type]}`;
  }

  openSocialMedia(platform: string): void {
    const urls: { [key: string]: string } = {
      facebook: 'https://facebook.com/assistacrise',
      instagram: 'https://instagram.com/assistacrise',
      youtube: 'https://youtube.com/@assistacrise'
    };
    window.open(urls[platform], '_blank');
  }
}