import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CONTACT_ADRESSE, CONTACT_EMAIL, CONTACT_NOM } from '../../../shared/utils/contact-obfusque.util';

@Component({
  selector: 'app-rgpd',
  imports: [RouterLink],
  templateUrl: './rgpd.component.html',
  styleUrl: './rgpd.component.scss'
})
export class RgpdComponent {
  readonly contactNom = CONTACT_NOM;
  readonly contactAdresse = CONTACT_ADRESSE;
  readonly contactEmail = CONTACT_EMAIL;
}
