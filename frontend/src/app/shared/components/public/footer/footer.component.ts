import { Component } from '@angular/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-footer',
  templateUrl: './footer.component.html',
  styleUrls: ['./footer.component.scss'],
  standalone: true,
  imports: [RouterModule],
})
export class FooterComponent {
  currentYear = new Date().getFullYear();

  emergencyLinks = [
    { label: 'SAMU',             number: '15',  url: 'tel:15'  },
    { label: 'Pompiers',         number: '18',  url: 'tel:18'  },
    { label: 'Police',           number: '17',  url: 'tel:17'  },
    { label: 'Urgence européen', number: '112', url: 'tel:112' },
  ];

  usefulLinks = [
    { label: 'Géorisques',     url: 'https://www.georisques.gouv.fr'  },
    { label: 'Météo France',   url: 'https://vigilance.meteofrance.fr' },
    { label: 'Vigicrues',      url: 'https://www.vigicrues.gouv.fr'   },
    { label: 'Sécurité civile',url: 'https://www.interieur.gouv.fr/Le-ministere/Securite-civile' },
  ];

  legalLinks = [
    { label: 'Mentions légales', route: '/mentions-legales' },
    { label: 'CGU',              route: '/cgu'              },
    { label: 'RGPD',             route: '/rgpd'             },
    { label: 'Crédits',          route: '/credits'          },
  ];

  contact = {
    email: 'contact@assista-crise.fr',
  };

  openEmail(address: string): void {
    window.location.href = `mailto:${address}`;
  }

  openUrl(url: string): void {
    window.open(url, '_blank', 'noopener noreferrer');
  }
}