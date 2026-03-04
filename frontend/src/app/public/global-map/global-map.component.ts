import { Component } from '@angular/core';
import { MapComponent } from '../../shared/components/common/map/map.component';

@Component({
  selector: 'app-global-map',
  standalone: true,
  imports: [MapComponent],
  templateUrl: './global-map.component.html',
  styleUrl: './global-map.component.scss'
})
export class GlobalMapComponent {}