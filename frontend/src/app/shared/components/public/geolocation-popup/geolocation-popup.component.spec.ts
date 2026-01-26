import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GeolocalisationPopupComponent } from './geolocation-popup.component';

describe('GeolocalisationPopupComponent', () => {
  let component: GeolocalisationPopupComponent;
  let fixture: ComponentFixture<GeolocalisationPopupComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GeolocalisationPopupComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(GeolocalisationPopupComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
